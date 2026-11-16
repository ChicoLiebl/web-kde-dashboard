#!/usr/bin/env python3
"""kddash — serve a live summary of KDE virtual desktops (and the Claude Code
sessions running in them) to a tablet on the LAN, and switch desktops on tap.

KWin pushes window/desktop snapshots to us over D-Bus (see kwin/kddash.js);
we enrich them with /proc info (which windows host a `claude` process, its cwd)
and Claude Code's own per-process state (~/.claude/sessions/<pid>.json), and
stream the result to browsers via Server-Sent Events.
"""
import asyncio
import itertools
import json
import os
import secrets
import signal
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from dbus_next import NameFlag, RequestNameReply
from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, method

import launcher

HERE = Path(__file__).resolve().parent
KWIN_SCRIPT = HERE / "kwin" / "kddash.js"
# A fresh KWin plugin name per run: KWin can get stuck on a name after a quick unload/reload and
# then never runs a script loaded under it. The name in use is recorded so the next run can
# unload it if this one dies without cleaning up.
KWIN_PLUGIN = f"kddash_{os.getpid()}"
KWIN_PLUGIN_FILE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "kddash-kwin-plugin"
STATIC = HERE / "static"
PORT = int(os.environ.get("KDDASH_PORT", "8765"))
BROADCAST_DELAY = 0.3  # seconds
POLL_INTERVAL = 1.0  # seconds; catches Claude status changes that cause no KWin event (unfocused kitty splits)
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "kddash"

SESSIONS_DIR = Path.home() / ".claude" / "sessions"

# Claude Code's session status -> dashboard status ("shell" = running a shell command; Claude's
# own UI shows it as working). "done" = turn finished, waiting for a prompt;
# "blocked" = waiting on you mid-turn (permission, question).
SESSION_STATUS = {"busy": "working", "shell": "working", "waiting": "blocked", "idle": "done"}

# Fallback when there is no session file: Claude Code puts a status glyph at the start
# of the terminal title, "✳" when idle, an animated spinner glyph while working.
IDLE_GLYPHS = {"✳"}

state = {"current": None, "desktops": [], "windows": []}
raw_state = None
broadcast_pending = False
last_msg = None
snoozed: dict[int, str] = {}  # claude pid -> status it was marked idle in; cleared when the status changes
last_title: dict[int, str] = {}  # claude pid -> last task title seen in its window caption
clients: set[asyncio.Queue] = set()
bus: MessageBus | None = None


# ---------------------------------------------------------------- /proc helpers

def process_tree():
    children, comm = {}, {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            stat = Path(f"/proc/{d}/stat").read_text()
        except OSError:
            continue
        # comm may contain spaces/parens; it's delimited by the first "(" and last ")"
        name = stat[stat.index("(") + 1: stat.rindex(")")]
        ppid = int(stat[stat.rindex(")") + 2:].split()[1])
        pid = int(d)
        comm[pid] = name
        children.setdefault(ppid, []).append(pid)
    return children, comm


def claude_pids_under(pid, children, comm):
    out, stack = [], list(children.get(pid, []))
    while stack:
        p = stack.pop()
        if comm.get(p) == "claude":
            out.append(p)
            continue  # don't descend into claude's own subprocesses
        stack.extend(children.get(p, []))
    return sorted(out)


def caption_status(caption):
    glyph = caption[:1]
    if glyph in IDLE_GLYPHS:
        return "done"
    if glyph and not glyph.isalnum() and ord(glyph) > 127:
        return "working"
    return None


def session_info(pid, caption, only_session):
    try:
        meta = json.loads((SESSIONS_DIR / f"{pid}.json").read_text())
    except (OSError, ValueError):
        meta = {}
    try:
        cwd = meta.get("cwd") or os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        cwd = ""
    from_caption = caption_status(caption)
    status = SESSION_STATUS.get(meta.get("status")) or from_caption or "unknown"
    # The window caption only reflects the focused kitty split, so it can only be
    # attributed to this session when it's the window's only Claude session.
    if only_session and from_caption:
        last_title[pid] = caption[1:].strip()
    if pid in snoozed and snoozed[pid] != status:
        del snoozed[pid]
    return {
        "pid": pid, "sessionId": meta.get("sessionId"), "cwd": cwd, "project": Path(cwd).name or cwd,
        "title": last_title.get(pid) or meta.get("name") or "",
        "waitingFor": meta.get("waitingFor"),
        "status": status, "snoozed": pid in snoozed,
    }


def enrich(raw):
    children, comm = process_tree()
    windows, seen = [], set()
    for w in raw["windows"]:
        w = dict(w)
        pids = claude_pids_under(w["pid"], children, comm)
        if pids:
            w["claude"] = [session_info(p, w["caption"], len(pids) == 1) for p in pids]
            seen.update(pids)
        windows.append(w)
    for d in (snoozed, last_title):  # forget sessions that have exited
        for pid in d.keys() - seen:
            del d[pid]
    return {**raw, "windows": windows, "host": socket.gethostname()}


# ---------------------------------------------------------------- D-Bus / KWin

class KddashIface(ServiceInterface):
    def __init__(self):
        super().__init__("org.kddash")

    @method()
    def Push(self, payload: "s"):
        # Claude's title spinner makes KWin push many times per second;
        # coalesce bursts into at most one broadcast per BROADCAST_DELAY.
        global raw_state, broadcast_pending
        try:
            raw_state = json.loads(payload)
        except ValueError as e:
            print("bad snapshot:", e, file=sys.stderr)
            return
        if not broadcast_pending:
            broadcast_pending = True
            asyncio.get_running_loop().call_later(BROADCAST_DELAY, broadcast)


def broadcast():
    global state, broadcast_pending, last_msg
    broadcast_pending = False
    if raw_state is None:
        return
    try:
        state = enrich(raw_state)
    except Exception as e:  # never let a bad snapshot kill the service
        print("bad snapshot:", e, file=sys.stderr)
        return
    msg = json.dumps(state)
    if msg == last_msg:
        return
    last_msg = msg
    for q in list(clients):
        if q.full():
            q.get_nowait()
        q.put_nowait(msg)


async def poll():
    while True:
        await asyncio.sleep(POLL_INTERVAL)
        broadcast()


def snooze(pid, on):
    for w in state["windows"]:
        for sess in w.get("claude", []):
            if sess["pid"] == pid:
                if on:
                    snoozed[pid] = sess["status"]
                else:
                    snoozed.pop(pid, None)
    broadcast()


async def kwin_call(path, iface, member, signature="", body=()):
    from dbus_next import Message, MessageType
    reply = await bus.call(Message(destination="org.kde.KWin", path=path, interface=iface,
                                   member=member, signature=signature, body=list(body)))
    if reply.message_type == MessageType.ERROR:
        raise RuntimeError(f"KWin {member}: {reply.error_name} {reply.body}")
    return reply.body


async def load_kwin_script(path, plugin):
    scripting = ("/Scripting", "org.kde.kwin.Scripting")
    await kwin_call(*scripting, "unloadScript", "s", [plugin])
    for _ in range(10):  # an unload finishes asynchronously; until then KWin refuses the name (-1)
        (sid,) = await kwin_call(*scripting, "loadScript", "ss", [str(path), plugin])
        if sid >= 0:
            break
        await asyncio.sleep(0.2)
    else:
        raise RuntimeError(f"KWin refused to load {path}")
    # Scripting.start() runs every loaded script that isn't running yet. Not /Scripting/Script<id>.run:
    # KWin reuses ids, and after an unload a stale object can keep that path, so run() goes nowhere.
    await kwin_call(*scripting, "start")


async def ensure_kwin_script():
    """Load the snapshot script and make sure snapshots arrive; reload it if none show up."""
    try:
        stale = KWIN_PLUGIN_FILE.read_text().strip()
    except OSError:
        stale = ""
    for name in {stale, "kddash"} - {"", KWIN_PLUGIN}:  # left by a previous run ("kddash": older versions)
        await kwin_call("/Scripting", "org.kde.kwin.Scripting", "unloadScript", "s", [name])
    KWIN_PLUGIN_FILE.write_text(KWIN_PLUGIN)
    for attempt in range(1, 6):
        await load_kwin_script(KWIN_SCRIPT, KWIN_PLUGIN)
        for _ in range(30):
            if raw_state is not None:
                if attempt > 1:
                    print(f"KWin snapshots arriving (attempt {attempt})", file=sys.stderr)
                return
            await asyncio.sleep(0.1)
        print(f"no snapshot from KWin after loading its script (attempt {attempt}); reloading", file=sys.stderr)
    print("KWin never sent a snapshot; the dashboard will stay empty", file=sys.stderr)


_script_ids = itertools.count()


async def run_oneshot(js, hold=0.2):
    """Run a throwaway KWin script, keeping it loaded for `hold` seconds (for scripts that wait on signals)."""
    plugin = f"kddash_oneshot_{next(_script_ids)}"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(js)
    try:
        await load_kwin_script(f.name, plugin)
        await asyncio.sleep(hold)
        await kwin_call("/Scripting", "org.kde.kwin.Scripting", "unloadScript", "s", [plugin])
    finally:
        os.unlink(f.name)


async def activate(window_id=None, desktop_id=None):
    if window_id:
        js = f"""
        for (const w of workspace.windowList()) {{
            if (w.internalId.toString() !== {json.dumps(window_id)}) continue;
            if (!w.onAllDesktops && w.desktops.length) workspace.currentDesktop = w.desktops[0];
            w.minimized = false;
            workspace.activeWindow = w;
        }}"""
    else:
        js = f"""
        for (const d of workspace.desktops)
            if (d.id === {json.dumps(desktop_id)}) workspace.currentDesktop = d;"""
    await run_oneshot(js)


# ---------------------------------------------------------------- launching saved/named sessions

# Waits for the new kitty window (by pid), puts it on the target desktop and into the rightmost
# tile of that desktop's KWin tiling layout (Meta+T), or quick-tiles it right if there is none.
PLACE_JS = """
const PID = %(pid)d, DESK = workspace.desktops[%(index)d];
let done = false;
function rightTile(w) {
    let root = null;
    try { root = workspace.rootTile(w.output, DESK); } catch (e) {}
    if (!root) { try { root = workspace.tilingForScreen(w.output).rootTile; } catch (e) {} }
    if (!root || !root.tiles || root.tiles.length < 2) return null;
    let best = null;
    for (const t of root.tiles)
        if (!best || t.absoluteGeometry.x > best.absoluteGeometry.x) best = t;
    return best;
}
function place(w) {
    if (done || !w || w.pid !== PID || !w.normalWindow) return;
    done = true;
    if (DESK) { w.desktops = [DESK]; workspace.currentDesktop = DESK; }
    const t = rightTile(w);
    if (t) w.tile = t;
    else { workspace.activeWindow = w; workspace.slotWindowQuickTileRight(); }
    workspace.activeWindow = w;
}
for (const w of workspace.windowList()) place(w);
workspace.windowAdded.connect(place);
"""


async def kitten(sock, *args):
    proc = await asyncio.create_subprocess_exec(
        "kitten", "@", "--to", f"unix:{sock}", *args,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = await asyncio.wait_for(proc.communicate(), timeout=5)
    if proc.returncode:
        raise RuntimeError(f"kitten @ {args[0]}: {err.decode().strip() or proc.returncode}")
    return out.decode().strip()


async def open_tab(sock, session):
    wid = None
    for args in launcher.tab_commands(session):
        out = await kitten(sock, *[a.replace("{wid}", wid or "") for a in args])
        wid = wid or out


def spawn_window(session):
    """Start a kitty window for the session in its own systemd scope, so it outlives this service."""
    cmd = launcher.window_command(session)
    if shutil.which("systemd-run"):
        cmd = ["systemd-run", "--user", "--scope", "--quiet", "--collect", "--slice=app.slice", *cmd]
    return subprocess.Popen(cmd, cwd=session["cwd"], start_new_session=True,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def launch_session(key, number, remember):
    """Open a saved/named session on desktop `number` (1-based). Returns {"how": "focused"|"tab"|"window"}."""
    session = launcher.find(key)
    if session is None:
        raise LookupError("unknown session")
    if not os.path.isdir(session["cwd"]):
        raise LookupError(f"folder does not exist: {session['cwd']}")
    desktops = state["desktops"]
    if not 1 <= number <= len(desktops):
        raise LookupError(f"there is no desktop {number}")
    if remember:
        launcher.set_desktop(key, number)

    # Already running (e.g. started elsewhere since the list was loaded): just focus it.
    for w in state["windows"]:
        if any(c.get("sessionId") == session["session_id"] for c in w.get("claude", [])):
            await activate(window_id=w["id"])
            return {"how": "focused"}

    target = desktops[number - 1]
    kitties = [w for w in state["windows"] if target["id"] in w["desktops"]
               and w["cls"] in launcher.KITTY_CLASSES]
    kitties.sort(key=lambda w: not w["active"])  # prefer the focused one
    for w in kitties:
        sock = launcher.kitty_socket(w["pid"])
        if not sock:
            continue
        try:
            await open_tab(sock, session)
        except (RuntimeError, asyncio.TimeoutError, OSError) as e:
            print(f"tab in kitty {w['pid']} failed, trying next: {e}", file=sys.stderr)
            continue
        await activate(window_id=w["id"])
        return {"how": "tab"}

    proc = spawn_window(session)
    # With systemd-run --scope, the scope's process *is* kitty (systemd-run execs it), so the pid matches.
    asyncio.create_task(run_oneshot(PLACE_JS % {"pid": proc.pid, "index": number - 1}, hold=8))
    await activate(desktop_id=target["id"])
    return {"how": "window"}


def sessions_payload():
    windows = state["windows"]
    desktops = []
    for i, d in enumerate(state["desktops"]):
        wins = [w for w in windows if d["id"] in w["desktops"]]
        desktops.append({
            "number": i + 1, "id": d["id"], "name": d["name"], "empty": not wins,
            "tab": any(w["cls"] in launcher.KITTY_CLASSES and launcher.kitty_socket(w["pid"]) for w in wins),
            "kitty": any(w["cls"] in launcher.KITTY_CLASSES for w in wins),
        })
    return {"sessions": launcher.catalog(), "desktops": desktops}


# ---------------------------------------------------------------- HTTP

def token():
    f = CONFIG / "token"
    if not f.exists():
        CONFIG.mkdir(parents=True, exist_ok=True)
        f.write_text(secrets.token_urlsafe(12))
        f.chmod(0o600)
    return f.read_text().strip()


TOKEN = token()
CTYPES = {".html": "text/html; charset=utf-8", ".json": "application/manifest+json",
          ".svg": "image/svg+xml", ".js": "text/javascript"}


async def respond(writer, status, body=b"", ctype="text/plain", extra=""):
    if isinstance(body, str):
        body = body.encode()
    writer.write(f"HTTP/1.1 {status}\r\nContent-Type: {ctype}\r\nContent-Length: {len(body)}\r\n"
                 f"Cache-Control: no-store\r\nConnection: close\r\n{extra}\r\n".encode() + body)
    await writer.drain()


async def handle(reader, writer):
    try:
        head = await reader.readuntil(b"\r\n\r\n")
        method_, target, _ = head.split(b"\r\n", 1)[0].decode().split(" ", 2)
        url = urlsplit(target)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        path = url.path

        if path in ("/", "/index.html", "/manifest.json", "/icon.svg"):
            f = STATIC / ("index.html" if path == "/" else path.lstrip("/"))
            return await respond(writer, "200 OK", f.read_bytes(), CTYPES[f.suffix])

        if q.get("t") != TOKEN:
            return await respond(writer, "403 Forbidden", "bad token")

        if path == "/events":
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n"
                         b"Cache-Control: no-store\r\nConnection: keep-alive\r\n\r\n")
            queue = asyncio.Queue(maxsize=1)
            clients.add(queue)
            try:
                msg = json.dumps(state)
                while True:
                    writer.write(f"data: {msg}\n\n".encode())
                    await writer.drain()
                    while True:
                        try:
                            msg = await asyncio.wait_for(queue.get(), timeout=20)
                            break
                        except asyncio.TimeoutError:
                            writer.write(b": keepalive\n\n")
                            await writer.drain()
            finally:
                clients.discard(queue)

        if path == "/api/state":
            return await respond(writer, "200 OK", json.dumps(state), "application/json")

        if path == "/api/activate" and method_ == "POST":
            await activate(q.get("window"), q.get("desktop"))
            return await respond(writer, "204 No Content")

        if path == "/api/snooze" and method_ == "POST":
            snooze(int(q.get("pid", 0)), q.get("on") == "1")
            return await respond(writer, "204 No Content")

        if path == "/api/sessions":
            return await respond(writer, "200 OK", json.dumps(sessions_payload()), "application/json")

        if path == "/api/sessions/desktop" and method_ == "POST":
            try:
                launcher.set_desktop(q.get("key", ""), int(q.get("desktop") or 0) or None)
            except KeyError:
                return await respond(writer, "404 Not Found", "unknown session")
            return await respond(writer, "204 No Content")

        if path == "/api/launch" and method_ == "POST":
            try:
                result = await launch_session(q.get("key", ""), int(q.get("desktop") or 0), q.get("remember") == "1")
            except (LookupError, OSError, RuntimeError) as e:
                return await respond(writer, "409 Conflict", json.dumps({"error": str(e)}), "application/json")
            return await respond(writer, "200 OK", json.dumps(result), "application/json")

        await respond(writer, "404 Not Found", "not found")
    except (ConnectionError, asyncio.IncompleteReadError, ValueError):
        pass
    finally:
        writer.close()


def lan_ip():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


async def main():
    global bus
    bus = await MessageBus().connect()
    bus.export("/", KddashIface())
    # KWin pushes snapshots to whoever owns the name; refuse to run as a silent second copy.
    if await bus.request_name("org.kddash", NameFlag.DO_NOT_QUEUE) != RequestNameReply.PRIMARY_OWNER:
        sys.exit("kddash: another kddash already owns org.kddash on the session bus "
                 "(stop it first: systemctl --user stop kddash)")

    server = await asyncio.start_server(handle, "0.0.0.0", PORT)
    tasks = [asyncio.create_task(ensure_kwin_script()), asyncio.create_task(poll())]  # noqa: F841 (keep references)
    url = f"http://{lan_ip()}:{PORT}/?t={TOKEN}"
    print(f"kddash serving on {url}", flush=True)
    if shutil.which("qrencode") and sys.stdout.isatty():
        subprocess.run(["qrencode", "-t", "ansiutf8", url])
    # Stop cleanly on SIGTERM (systemctl stop/restart) so the KWin script gets unloaded.
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        # Don't wait for clients to disconnect: browsers hold their /events stream open forever.
        server.close()
        if hasattr(server, "close_clients"):  # Python 3.13+
            server.close_clients()
        try:
            await kwin_call("/Scripting", "org.kde.kwin.Scripting", "unloadScript", "s", [KWIN_PLUGIN])
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
