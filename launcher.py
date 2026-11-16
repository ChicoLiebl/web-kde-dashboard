"""Named Claude Code sessions: discovery, saved desktops and kitty launch commands.

Saved sessions live in ccm's registry (~/.config/ccm/sessions.json, see ../claude-manager), so the
`ccm` CLI and the dashboard share one list:

    { "air-hub": { "cwd": "/home/me/air-hub", "session_id": "…", "desktop": 3, "shell_pct": 30 } }

Sessions that were named (`claude -n NAME` or `/rename`) but never saved are offered too; saving a
desktop for one adds it to the registry.
"""
import json
import os
import re
import shlex
import time
from pathlib import Path

HOME = Path.home()
CLAUDE = HOME / ".claude"
PROJECTS = CLAUDE / "projects"
LIVE = CLAUDE / "sessions"
HISTORY = CLAUDE / "history.jsonl"  # one line per prompt you typed: {sessionId, timestamp, project, display}
USAGE_HALF_LIFE_DAYS = 14
REGISTRY = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "ccm" / "sessions.json"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", HOME / ".cache")) / "ccm"
RUNTIME = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
DEFAULT_SHELL_PCT = 30
KITTY_CLASSES = ("kitty", "ccm")  # ccm opens its windows with --class ccm

# kitty's remote-control socket for a kitty process; matches the listen_on line in kitty.conf
# (see README) and the --listen-on we pass to the kitty windows we start.
KITTY_LISTEN_ON = f"unix:{RUNTIME}/kitty-{{kitty_pid}}.sock"


def kitty_socket(pid):
    path = Path(RUNTIME) / f"kitty-{pid}.sock"
    return path if path.is_socket() else None


# ------------------------------------------------------------------ registry (shared with ccm)

def load_registry():
    try:
        return json.loads(REGISTRY.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def save_registry(reg):
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(REGISTRY)


# ------------------------------------------------------------------ Claude Code session files

_TITLE_RE = re.compile(rb'"type":"(custom-title|ai-title|agent-name)","(?:customTitle|aiTitle|agentName)":("(?:[^"\\]|\\.)*")')
_scan_cache: dict[Path, tuple[float, dict]] = {}


_CWD_RE = re.compile(rb'"cwd":("(?:[^"\\]|\\.)*")')


def _scan(path, mtime):
    """Folders and latest names/titles of a session .jsonl, cached by mtime: the folder it started in
    (head) and the folders recorded most recently (tail)."""
    hit = _scan_cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    first, recent, titles = None, [], {}
    try:
        with open(path, "rb") as fh:
            for i, line in enumerate(fh):
                if i > 200:
                    break
                m = _CWD_RE.search(line)
                if m:
                    first = json.loads(m.group(1))
                    break
            fh.seek(max(0, fh.seek(0, 2) - 256 * 1024))
            tail = fh.read()
        for value in _CWD_RE.findall(tail):
            c = json.loads(value)
            if c in recent:
                recent.remove(c)
            recent.append(c)  # distinct, oldest -> newest
        for kind, value in _TITLE_RE.findall(tail):
            titles[kind.decode()] = json.loads(value)
    except (OSError, ValueError):
        pass
    info = {"cwd_first": first, "cwd_recent": recent,
            "name": titles.get("agent-name") or titles.get("custom-title"),
            "title": titles.get("ai-title") or titles.get("custom-title") or ""}
    _scan_cache[path] = (mtime, info)
    return info


def _resolve_cwd(info):
    """The session's folder: where it started if that still exists; otherwise the most recently recorded
    folder that exists (Claude appends to the same file when a moved project is resumed from its new
    folder). Not cached: folders move."""
    first, recent = info["cwd_first"], info["cwd_recent"]
    if first and os.path.isdir(first):
        return first
    for c in reversed(recent):
        if os.path.isdir(c):
            return c
    return first or (recent[-1] if recent else None)


def session_file(sid):
    hits = list(PROJECTS.glob(f"*/{sid}.jsonl"))
    return hits[0] if hits else None


def named_sessions():
    """session id -> {name, cwd, title, mtime} for every session that has a name."""
    out = {}
    for f in PROJECTS.glob("*/*.jsonl"):
        try:
            mtime = f.stat().st_mtime
        except OSError:
            continue
        info = _scan(f, mtime)
        cwd = _resolve_cwd(info)
        if info["name"] and cwd:
            out[f.stem] = {"name": info["name"], "title": info["title"], "cwd": cwd, "mtime": mtime}
    return out


_usage_cache: dict = {"key": None, "times": {}}


def _prompt_times():
    """session id -> timestamps (s) of the prompts you typed into it, from ~/.claude/history.jsonl."""
    try:
        st = HISTORY.stat()
    except OSError:
        return {}
    if _usage_cache["key"] != (st.st_mtime, st.st_size):
        times = {}
        with open(HISTORY, "rb") as fh:
            for line in fh:
                m = re.search(rb'"timestamp":(\d+).*?"sessionId":"([^"]+)"', line)
                if m:
                    times.setdefault(m.group(2).decode(), []).append(int(m.group(1)) / 1000)
        _usage_cache.update(key=(st.st_mtime, st.st_size), times=times)
    return _usage_cache["times"]


def usage(sid):
    """{prompts, last_used, score}: score counts each prompt once, its weight halving every
    USAGE_HALF_LIFE_DAYS, so sessions you use a lot *lately* rank first."""
    times = _prompt_times().get(sid, [])
    now = time.time()
    score = sum(0.5 ** ((now - t) / 86400 / USAGE_HALF_LIFE_DAYS) for t in times)
    return {"prompts": len(times), "last_used": max(times, default=0), "score": round(score, 3)}


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def running_session_ids():
    """Ids of sessions with a live claude process: from their state file, or from the command line
    (`--resume ID`, `--session-id ID`) while the state file doesn't exist yet."""
    ids = set()
    for f in LIVE.glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if d.get("sessionId") and _pid_alive(int(d.get("pid", 0))):
            ids.add(d["sessionId"])
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            if (p / "comm").read_text().strip() != "claude":
                continue
            ids.update(a.decode() for a in (p / "cmdline").read_bytes().split(b"\0")
                       if re.fullmatch(rb"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", a))
        except OSError:
            continue
    return ids


# ------------------------------------------------------------------ catalog

def catalog():
    """Saved sessions (registry) plus named sessions that aren't saved, most used first (see usage())."""
    reg = load_registry()
    named = named_sessions()
    running = running_session_ids()
    out, seen = [], set()
    for name, e in reg.items():
        sid = e.get("session_id")
        info = named.get(sid, {})
        out.append({
            # A saved folder that's gone (moved by hand) loses to the one the session file now records.
            "key": sid or f"ccm:{name}", "name": name, "session_id": sid,
            "cwd": e["cwd"] if os.path.isdir(e["cwd"]) or not info.get("cwd") else info["cwd"],
            "desktop": e.get("desktop"), "shell_pct": e.get("shell_pct", DEFAULT_SHELL_PCT),
            "saved": True, "title": info.get("title", ""), "mtime": info.get("mtime", 0),
        })
        seen.add(sid)
    for sid, info in named.items():
        if sid in seen:
            continue
        out.append({
            "key": sid, "name": info["name"], "session_id": sid, "cwd": info["cwd"],
            "desktop": None, "shell_pct": DEFAULT_SHELL_PCT, "saved": False,
            "title": info["title"], "mtime": info["mtime"],
        })
    for s in out:
        s["running"] = bool(s["session_id"]) and s["session_id"] in running
        s["short_cwd"] = s["cwd"].replace(str(HOME), "~", 1)
        s["missing"] = not os.path.isdir(s["cwd"])
        s.update(usage(s["session_id"]))
        s["last_used"] = s["last_used"] or s["mtime"]  # never prompted (e.g. renamed only): file time
    out.sort(key=lambda s: (-s["score"], -s["last_used"]))
    return out


def find(key):
    return next((s for s in catalog() if s["key"] == key), None)


def set_desktop(key, desktop):
    """Save (or clear, with desktop=None) a session's desktop in the registry."""
    s = find(key)
    if s is None:
        raise KeyError(key)
    reg = load_registry()
    name = s["name"]
    if not s["saved"]:
        # A named session joins the registry; don't clobber a different session with the same name.
        base, n = name, 2
        while name in reg and reg[name].get("session_id") != s["session_id"]:
            name, n = f"{base} ({n})", n + 1
        reg[name] = {"cwd": s["cwd"], "session_id": s["session_id"]}
    if desktop:
        reg[name]["desktop"] = int(desktop)
    else:
        reg[name].pop("desktop", None)
    save_registry(reg)


# ------------------------------------------------------------------ kitty commands

def claude_cmd(s):
    name, sid = s["name"], s["session_id"]
    if sid and session_file(sid):
        return ["claude", "--resume", sid, "-n", name]
    if sid:  # saved with `ccm add --new`: created on first open
        return ["claude", "--session-id", sid, "-n", name]
    return ["claude", "-n", name]


def tab_commands(s):
    """`kitten @ …` argument lists that open the session as a new tab: Claude on top,
    a shell below (like ccm's window layout). `{wid}` is the id printed by the first launch."""
    name, cwd, pct = s["name"], s["cwd"], int(s["shell_pct"])
    return [
        ["launch", "--type=tab", "--cwd", cwd, "--tab-title", name, "--title", f"claude: {name}",
         "--var", "ccm=claude", *claude_cmd(s)],
        ["goto-layout", "--match", "window_id:{wid}", "splits"],
        ["launch", "--type=window", "--location=hsplit", f"--bias={pct}", "--cwd", cwd,
         "--title", f"shell: {name}", "--match", "window_id:{wid}"],
        ["focus-window", "--match", "id:{wid}"],
    ]


def window_command(s):
    """kitty command line for a new window with the session (ccm's split layout), with remote
    control on so later sessions for this desktop can open as tabs in it."""
    name, cwd = s["name"], s["cwd"]
    CACHE.mkdir(parents=True, exist_ok=True)
    session = CACHE / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', name)}.session"
    session.write_text("\n".join([
        "layout splits",
        f"cd {shlex.quote(cwd)}",
        f"launch --var ccm=claude --title {shlex.quote('claude: ' + name)} {shlex.join(claude_cmd(s))}",
        f"launch --location=hsplit --bias={int(s['shell_pct'])} --title {shlex.quote('shell: ' + name)}",
        "focus_matching_window var:ccm=claude",
        "",
    ]))
    return ["kitty", "--class", "ccm", "-o", "allow_remote_control=socket-only",
            "--listen-on", KITTY_LISTEN_ON, "--session", str(session)]
