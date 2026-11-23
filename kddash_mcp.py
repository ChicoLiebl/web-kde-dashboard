#!/usr/bin/env python3
"""MCP server (stdio) that lets a voice agent (StackChan / XiaoZhi) list the running
Claude Code sessions, mark them idle and switch KDE virtual desktops, via the local kddash service.

kddash.py must be running; this server only talks to its HTTP API on localhost.
"""
import functools
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from fastmcp import FastMCP

# stdout is the MCP channel: log to stderr only.
logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("KDEDesktops")

KDDASH_URL = os.environ.get("KDDASH_URL", "http://127.0.0.1:8765")
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "kddash"
TITLE_MAX = 60

# Dashboard status -> words that read well through TTS.
SPOKEN_STATUS = {
    "working": "working",
    "blocked": "needs your input",
    "done": "finished, waiting for you",
    "unknown": "unknown",
}
# What a working session is doing right now (the dashboard's crab pose) -> spoken words.
SPOKEN_ACTIVITY = {
    "read": "reading files", "write": "editing files", "bash": "running commands",
    "web": "searching the web", "delegate": "running subagents", "plan": "planning",
    "think": "thinking", "run": "using a tool",
}

mcp = FastMCP("KDEDesktops")


def _token():
    return os.environ.get("KDDASH_TOKEN") or (CONFIG / "token").read_text().strip()


def _request(path, params=None, method="GET", timeout=3):
    query = urllib.parse.urlencode({"t": _token(), **(params or {})})
    req = urllib.request.Request(f"{KDDASH_URL}{path}?{query}", method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
    except urllib.error.HTTPError as e:  # the API explains refusals as {"error": "..."}
        try:
            message = json.loads(e.read())["error"]
        except (ValueError, KeyError, TypeError):
            message = f"the dashboard answered {e.code}"
        raise RuntimeError(message) from None
    return json.loads(body) if body else None


def _state():
    state = _request("/api/state")
    if not state or not state.get("desktops"):
        raise RuntimeError("the desktop dashboard has no data yet")
    return state


def _sessions(state):
    """Flatten Claude sessions, with their 1-based desktop number and window id."""
    number = {d["id"]: i + 1 for i, d in enumerate(state["desktops"])}
    out = []
    for w in state["windows"]:
        for c in w.get("claude", []):
            out.append({
                "desktop": number.get(w["desktops"][0]) if w["desktops"] else None,
                "project": c["project"],
                "status": "marked idle" if c["snoozed"] else SPOKEN_STATUS.get(c["status"], c["status"]),
                "kind": c.get("kind", "software"),
                **({"doing": SPOKEN_ACTIVITY[c["activity"]]} if c.get("activity") in SPOKEN_ACTIVITY else {}),
                "task": c["title"][:TITLE_MAX],
                "_window": w["id"],
                "_pid": c["pid"],
                "_snoozed": c["snoozed"],
                "_alert": 0 if c["snoozed"] else {"blocked": 2, "done": 1}.get(c["status"], 0),
            })
    return sorted(out, key=lambda s: (s["desktop"] or 0, s["project"]))


def _public(session):
    return {k: v for k, v in session.items() if not k.startswith("_")}


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _errors(fn):
    """Turn connection/API failures into a speakable error result."""
    @functools.wraps(fn)  # keeps the signature/docstring FastMCP builds the schema from
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (urllib.error.URLError, OSError) as e:
            logger.warning(f"{fn.__name__}: kddash unreachable: {e}")
            return {"success": False, "error": "The desktop dashboard service on the PC is not running."}
        except RuntimeError as e:
            return {"success": False, "error": str(e)}
    return wrapper


@mcp.tool()
@_errors
def list_claude_sessions() -> dict:
    """List the Claude Code sessions running on the user's PC: which virtual desktop each is on,
    its project name, the kind of work (firmware, pcb, software or cad), its status (working, needs
    your input, finished and waiting, marked idle), what a working one is doing right now, and a
    short description of its task. Also returns how many are working or waiting.
    Use when the user asks about their Claude sessions, agents, what is running or working,
    whether anything is done or needs them, or which desktop something is on."""
    logger.info("list_claude_sessions()")
    state = _state()
    sessions = _sessions(state)
    current = next(i + 1 for i, d in enumerate(state["desktops"]) if d["id"] == state["current"])
    return {
        "success": True,
        "current_desktop": current,
        "working": sum(s["status"] == "working" for s in sessions),
        "waiting_for_user": sum(s["_alert"] > 0 for s in sessions),
        "sessions": [_public(s) for s in sessions],
    }


@mcp.tool()
@_errors
def go_to_desktop(number: int) -> dict:
    """Switch the PC to virtual desktop `number` (1 = first desktop).
    Use when the user asks to go to, switch to, show or open desktop N on the computer."""
    logger.info(f"go_to_desktop({number!r})")
    state = _state()
    desktops = state["desktops"]
    if not 1 <= number <= len(desktops):
        return {"success": False, "error": f"There is no desktop {number}; there are {len(desktops)} desktops."}
    _request("/api/activate", {"desktop": desktops[number - 1]["id"]}, method="POST")
    return {"success": True, "desktop": number}


@mcp.tool()
@_errors
def go_to_claude_session(project: str) -> dict:
    """Switch the PC to the desktop of the Claude Code session working on `project` and focus its
    terminal window. `project` is the session's project name as returned by list_claude_sessions
    (spoken forms like "air hub" for "air-hub" are fine).
    Use when the user asks to go to, open or show a specific Claude session or project."""
    logger.info(f"go_to_claude_session({project!r})")
    sessions = _sessions(_state())
    want = _norm(project)
    if not want:
        return {"success": False, "error": "Please say which project."}
    matches = [s for s in sessions if _norm(s["project"]) == want] \
        or [s for s in sessions if want in _norm(s["project"]) or _norm(s["project"]) in want]
    if not matches:
        names = ", ".join(sorted({s["project"] for s in sessions})) or "none"
        return {"success": False, "error": f"No Claude session matches {project!r}. Running projects: {names}."}
    if len({s["_window"] for s in matches}) > 1:
        return {"success": False, "error": "Several sessions match; say which one.",
                "candidates": [_public(s) for s in matches]}
    target = matches[0]
    _request("/api/activate", {"window": target["_window"]}, method="POST")
    return {"success": True, **_public(target)}


@mcp.tool()
@_errors
def mark_claude_session_idle(project: str) -> dict:
    """Mark a Claude Code session as idle on the dashboard, so it stops blinking yellow. `project` is the session's
    name as returned by list_claude_sessions (spoken forms are fine), or "all" for every session waiting for the user.
    Use when the user says a session is finished, done or can be ignored, or asks to mark it idle or stop it blinking.
    It clears by itself when that session's status changes again."""
    logger.info(f"mark_claude_session_idle({project!r})")
    sessions = _sessions(_state())
    waiting = [s for s in sessions if s["_alert"]]
    if _norm(project) in ("all", "everything", "todas", "tudo"):
        targets = waiting
    else:
        want = _norm(project)
        if not want:
            return {"success": False, "error": "Please say which session."}
        targets = [s for s in sessions if _norm(s["project"]) == want] \
            or [s for s in sessions if want in _norm(s["project"]) or _norm(s["project"]) in want]
        if not targets:
            names = ", ".join(sorted({s["project"] for s in sessions})) or "none"
            return {"success": False, "error": f"No Claude session matches {project!r}. Running: {names}."}
        if len(targets) > 1:
            return {"success": False, "error": "Several sessions match; say which one.",
                    "candidates": [_public(s) for s in targets]}
        if targets[0]["status"] == "working":
            return {"success": False, "error": f"{targets[0]['project']} is still working, so it can't be marked idle."}
    for s in targets:
        _request("/api/snooze", {"pid": s["_pid"], "on": 1}, method="POST")
    return {"success": True, "marked_idle": [s["project"] for s in targets]}


LIST_MAX = 15  # launchable sessions named in a reply: the most used ones


def _launchable(catalog):
    """Named sessions that can be opened (folder exists), most used first."""
    return [s for s in catalog["sessions"] if not s["missing"]]


@mcp.tool()
@_errors
def list_launchable_claude_sessions() -> dict:
    """List the named Claude Code sessions on the user's PC that are not running and can be opened with
    launch_claude_session, most used first, with the desktop each one opens on by default.
    Use when the user asks which Claude sessions or projects they can open, start or resume."""
    logger.info("list_launchable_claude_sessions()")
    sessions = [s for s in _launchable(_request("/api/sessions")) if not s["running"]]
    return {
        "success": True,
        "count": len(sessions),
        "sessions": [{"name": s["name"], "folder": s["short_cwd"], "saved_desktop": s["desktop"]}
                     for s in sessions[:LIST_MAX]],
    }


@mcp.tool()
@_errors
def launch_claude_session(name: str, desktop: int = 0) -> dict:
    """Open (resume) a named Claude Code session in a kitty terminal on the PC. `name` is the session's
    name as returned by list_launchable_claude_sessions (spoken forms like "air hub" for "air-hub" are
    fine). `desktop` is the virtual desktop to open it on (1 = first); leave it 0 to use the session's
    saved desktop, or the next empty desktop if it has none. It opens as a new tab when that desktop
    already has a kitty window, otherwise in a new window, and the PC switches to it. If the session is
    already running, its window is focused instead.
    Use when the user asks to open, start, launch, resume or continue a Claude session or project."""
    logger.info(f"launch_claude_session({name!r}, {desktop!r})")
    want = _norm(name)
    if not want:
        return {"success": False, "error": "Please say which session."}
    catalog = _request("/api/sessions")
    sessions = _launchable(catalog)
    matches = [s for s in sessions if _norm(s["name"]) == want] \
        or [s for s in sessions if want in _norm(s["name"]) or _norm(s["name"]) in want]
    if not matches:
        missing = [s for s in catalog["sessions"] if s["missing"] and _norm(s["name"]) == want]
        if missing:
            return {"success": False, "error": f"The folder of {missing[0]['name']} no longer exists: "
                                               f"{missing[0]['short_cwd']}."}
        names = ", ".join([s["name"] for s in sessions if not s["running"]][:LIST_MAX]) or "none"
        return {"success": False, "error": f"No Claude session is named {name!r}. Most used: {names}."}
    if len(matches) > 1:
        return {"success": False, "error": "Several sessions match; say which one.",
                "candidates": [s["name"] for s in matches[:LIST_MAX]]}
    session = matches[0]

    desktops = catalog["desktops"]
    if desktop:
        if not 1 <= desktop <= len(desktops):
            return {"success": False, "error": f"There is no desktop {desktop}; there are {len(desktops)} desktops."}
    elif session["desktop"] and session["desktop"] <= len(desktops):
        desktop = session["desktop"]
    else:  # like the dashboard: the first empty desktop after the current one, else the current one
        current = next(i for i, d in enumerate(desktops) if d["id"] == _state()["current"])
        ring = desktops[current + 1:] + desktops[:current + 1]
        desktop = next((d["number"] for d in ring if d["empty"]), current + 1)

    # Opening a tab or a new window and switching desktops takes a few seconds.
    result = _request("/api/launch", {"key": session["key"], "desktop": desktop, "remember": 0},
                      method="POST", timeout=20)
    how = {"focused": "already running, focused it", "tab": "opened as a new tab",
           "window": "opened in a new window"}.get(result.get("how"), result.get("how"))
    return {"success": True, "session": session["name"], "desktop": desktop, "result": how}


@mcp.tool()
@_errors
def set_tablet_screen(on: bool) -> dict:
    """Turn the dashboard tablet's screen off (on=false, sleep) or back on (on=true, wake). The tablet is
    the wall-mounted screen beside the PC that shows the desktops dashboard.
    Use when the user asks to turn off, sleep or switch off the tablet or dashboard screen (e.g. at
    bedtime), or to turn it back on or wake it."""
    logger.info(f"set_tablet_screen({on!r})")
    _request("/api/tablet/wake" if on else "/api/tablet/sleep", method="POST", timeout=20)
    return {"success": True, "screen": "on" if on else "off"}


@mcp.tool()
@_errors
def go_to_waiting_claude_session() -> dict:
    """Switch the PC to the Claude Code session that most needs the user: first one blocked on
    their input (e.g. a permission question), otherwise one that finished and is waiting.
    Use when the user says things like "take me to the session that needs me", "what's waiting",
    "go to the one that finished"."""
    logger.info("go_to_waiting_claude_session()")
    waiting = [s for s in _sessions(_state()) if s["_alert"]]
    if not waiting:
        return {"success": False, "error": "No Claude session is waiting for you right now."}
    target = max(waiting, key=lambda s: s["_alert"])
    _request("/api/activate", {"window": target["_window"]}, method="POST")
    return {"success": True, "others_waiting": len(waiting) - 1, **_public(target)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
