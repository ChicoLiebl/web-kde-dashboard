#!/usr/bin/env python3
"""MCP server (stdio) for Claude Code sessions themselves: lets a session mark itself idle on the
kddash dashboard when the user asks ("set yourself idle", "I'm done with this one").

Claude Code starts its MCP servers as child processes, so the session is the nearest `claude`
process above this one. The mark starts when the session's turn finishes (it's still working while
it calls the tool) and clears at the next prompt, like a mark set on the dashboard.

Standard library only. Register it once for all sessions:

    claude mcp add --scope user kddash -- python3 /path/to/claude_session_mcp.py

It needs the kddash service running and reads its token from ~/.config/kddash/token (override with
KDDASH_TOKEN / KDDASH_URL).
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

KDDASH_URL = os.environ.get("KDDASH_URL", "http://127.0.0.1:8765")
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "kddash"

TOOLS = [{
    "name": "mark_this_session_idle",
    "description": (
        "Mark this Claude Code session idle on the user's desktops dashboard (kddash), so it stops "
        "blinking as 'waiting' once this turn ends. Use when the user asks you to set or mark yourself, "
        "or this session, idle, or says they're done with this session for now. The mark clears by "
        "itself at the user's next prompt."),
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
}]


def session_pid():
    """The `claude` process this server runs under."""
    pid = os.getppid()
    while pid > 1:
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
        except OSError:
            return None
        name = stat[stat.index("(") + 1: stat.rindex(")")]
        if name == "claude":
            return pid
        pid = int(stat[stat.rindex(")") + 2:].split()[1])
    return None


def mark_idle():
    pid = session_pid()
    if not pid:
        return "This server isn't running under a Claude Code session, so there is no session to mark.", True
    try:
        token = os.environ.get("KDDASH_TOKEN") or (CONFIG / "token").read_text().strip()
    except OSError:
        return "kddash isn't set up on this PC (no ~/.config/kddash/token).", True
    query = urllib.parse.urlencode({"t": token, "pid": pid, "on": 1, "after_turn": 1})
    try:
        urllib.request.urlopen(urllib.request.Request(f"{KDDASH_URL}/api/snooze?{query}", method="POST"),
                               timeout=3).close()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return ("The dashboard doesn't see this session (it only knows sessions in a terminal window "
                    "on the desktop), so it wasn't marked."), True
        return f"The dashboard refused: HTTP {e.code}.", True
    except OSError as e:
        return f"Couldn't reach the kddash service at {KDDASH_URL}: {e}.", True
    return "Marked idle: the dashboard shows this session as idle once this turn ends, until the next prompt.", False


def reply(msg_id, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": msg_id}
    msg.update({"error": error} if error else {"result": result})
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        method, msg_id = msg.get("method"), msg.get("id")
        if msg_id is None:  # a notification (initialized, cancelled…): nothing to answer
            continue
        if method == "initialize":
            reply(msg_id, {
                "protocolVersion": (msg.get("params") or {}).get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "kddash", "version": "1.0"},
            })
        elif method == "tools/list":
            reply(msg_id, {"tools": TOOLS})
        elif method == "tools/call":
            name = (msg.get("params") or {}).get("name")
            if name != "mark_this_session_idle":
                reply(msg_id, error={"code": -32602, "message": f"unknown tool {name!r}"})
                continue
            text, is_error = mark_idle()
            reply(msg_id, {"content": [{"type": "text", "text": text}], "isError": is_error})
        elif method == "ping":
            reply(msg_id, {})
        else:
            reply(msg_id, error={"code": -32601, "message": f"method not found: {method}"})


if __name__ == "__main__":
    main()
