#!/usr/bin/env python3
"""MCP server (stdio) that lets a voice agent (StackChan / XiaoZhi) list the running
Claude Code sessions and switch KDE virtual desktops, via the local kddash service.

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

mcp = FastMCP("KDEDesktops")


def _token():
    return os.environ.get("KDDASH_TOKEN") or (CONFIG / "token").read_text().strip()


def _request(path, params=None, method="GET"):
    query = urllib.parse.urlencode({"t": _token(), **(params or {})})
    req = urllib.request.Request(f"{KDDASH_URL}{path}?{query}", method=method)
    with urllib.request.urlopen(req, timeout=3) as r:
        body = r.read()
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
                "task": c["title"][:TITLE_MAX],
                "_window": w["id"],
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
    its project name, its status (working, needs your input, finished and waiting, marked idle)
    and a short description of its task. Also returns how many are working or waiting.
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
