#!/usr/bin/env python3
"""kddash — serve a live summary of KDE virtual desktops (and the Claude Code
sessions running in them) to a tablet on the LAN, and switch desktops on tap.

KWin pushes window/desktop snapshots to us over D-Bus (see kwin/kddash.js);
we enrich them with /proc info (which windows host a `claude` process, its cwd)
and Claude Code's own per-process state (~/.claude/sessions/<pid>.json), and
stream the result to browsers via Server-Sent Events.
"""
import asyncio
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, method

HERE = Path(__file__).resolve().parent
KWIN_SCRIPT = HERE / "kwin" / "kddash.js"
KWIN_PLUGIN = "kddash"
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
        "pid": pid, "cwd": cwd, "project": Path(cwd).name or cwd,
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
    from dbus_next import Message
    reply = await bus.call(Message(destination="org.kde.KWin", path=path, interface=iface,
                                   member=member, signature=signature, body=list(body)))
    return reply.body


async def load_kwin_script(path, plugin):
    scripting = ("/Scripting", "org.kde.kwin.Scripting")
    await kwin_call(*scripting, "unloadScript", "s", [plugin])
    (sid,) = await kwin_call(*scripting, "loadScript", "ss", [str(path), plugin])
    await kwin_call(f"/Scripting/Script{sid}", "org.kde.kwin.Script", "run")


async def run_oneshot(js):
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(js)
    try:
        await load_kwin_script(f.name, "kddash_oneshot")
        await asyncio.sleep(0.2)
        await kwin_call("/Scripting", "org.kde.kwin.Scripting", "unloadScript", "s", ["kddash_oneshot"])
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
    await bus.request_name("org.kddash")
    await load_kwin_script(KWIN_SCRIPT, KWIN_PLUGIN)

    server = await asyncio.start_server(handle, "0.0.0.0", PORT)
    poller = asyncio.create_task(poll())  # noqa: F841 (keep a reference)
    url = f"http://{lan_ip()}:{PORT}/?t={TOKEN}"
    print(f"kddash serving on {url}", flush=True)
    if shutil.which("qrencode") and sys.stdout.isatty():
        subprocess.run(["qrencode", "-t", "ansiutf8", url])
    try:
        async with server:
            await server.serve_forever()
    finally:
        try:
            await kwin_call("/Scripting", "org.kde.kwin.Scripting", "unloadScript", "s", [KWIN_PLUGIN])
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
