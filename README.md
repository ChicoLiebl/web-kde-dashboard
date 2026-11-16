# kddash: KDE desktops dashboard

A live dashboard of your KDE Plasma virtual desktops and the Claude Code sessions running on them, made
for a tablet (or any browser) on your local network. Tap a card to switch to that desktop on the PC.

- One card per desktop that has windows, sized to fill the screen.
- Each Claude Code session shows its project, task title and status:
  - **working** (blue)
  - **waiting** (yellow, blinks): the turn finished and Claude is waiting for a prompt.
  - **needs you** (yellow, blinks): blocked on a permission prompt or a question.
  - **idle** (grey): you marked the session idle.
- Tap a card to switch to its desktop, or tap a session or window to focus it.
- Hold a card (or right-click it) for its popup:
  - **Mark idle** stops a session blinking. The mark clears itself the next time that session's status
    changes.
  - **Open Claude session here** opens the launcher with that desktop already chosen.
  - **Go to desktop** switches to it.
- The last tile, **+ New desktop**, opens a launcher: pick a named Claude Code session that isn't
  running and a desktop, and it opens there in kitty (see [Launching sessions](#launching-sessions)).
  **Just go to desktop N** switches to the next empty desktop instead.
- **⚙ Sessions** in the top bar sets the desktop each named session opens on.
- **⛶ Fullscreen** in the top bar hides the browser and Android bars.
- Optional: an MCP server lets a voice assistant (StackChan / XiaoZhi) list the sessions and switch
  desktops for you (see [Voice control](#voice-control-stackchan-mcp)).

No app to install on the tablet: it's a web page served by the PC.

## Requirements

- KDE Plasma 6 on Wayland (built and tested on Plasma 6.7).
- Python 3 with [`dbus-next`](https://pypi.org/project/dbus-next/):
  - Arch: `sudo pacman -S python-dbus-next`
  - Debian/Ubuntu: `sudo apt install python3-dbus-next`
  - Any: `pip install --user dbus-next`
- systemd, for running it as a service.
- kitty, for launching sessions. To open sessions as tabs in an existing kitty window, kitty needs remote
  control turned on (see [Launching sessions](#launching-sessions)).
- Optional: `qrencode` to print a QR code of the dashboard URL.

## Install

```bash
./install.sh
```

The script:

1. Checks the requirements.
2. Writes the systemd **user** service `~/.config/systemd/user/kddash.service`. It's a user service, not a
   system one, because it needs your session's KWin and D-Bus. It starts with the Plasma session, stops
   at logout, and restarts if it crashes.
3. Starts the service and prints the dashboard URL (plus a QR code if `qrencode` is installed).

The service runs the code from this folder, so keep the repository where it is. If you move it, run
`./install.sh` again. Re-run the script after pulling changes too: it restarts the service.

Use another port with `KDDASH_PORT=9000 ./install.sh`.

### Firewall

The tablet connects to the PC on TCP port 8765. If you use firewalld, open the port in the zone your
home network uses:

```bash
sudo firewall-cmd --permanent --zone=home --add-port=8765/tcp && sudo firewall-cmd --reload
```

Check which zone your network interface is in with `firewall-cmd --get-active-zones`.

## Open it on the tablet

1. Open the URL printed by `install.sh`, `http://<pc-ip>:8765/?t=<token>`, in Chrome on the tablet.
   Scanning the QR code is easiest. Lost the URL? Run `journalctl --user -u kddash | grep serving`.
2. Use **Add to Home screen** in Chrome's menu so it opens like an app. The page remembers the token, so
   the shortcut keeps working.
3. Tap **⛶ Fullscreen**. Android drops fullscreen when you switch apps or the screen turns off, so tap it
   again after that.

The token is created on first run and stored in `~/.config/kddash/token`. Delete that file and restart
the service to generate a new one; open the new URL on the tablet afterwards.

## Launching sessions

Tap **+ New desktop** to open a Claude Code session that isn't running:

- **Session:** every named session on this computer that isn't running. A session is named when it was
  started with `claude -n NAME` or renamed with `/rename`. Sessions saved with
  [`ccm`](../claude-manager) are listed too. The list scrolls and has two orders:
  - **Most used** (default): counts the prompts you typed into each session (from
    `~/.claude/history.jsonl`), each prompt's weight halving every 14 days. Sessions you use a lot lately
    come first; a session you used heavily months ago drops down.
  - **Recent**: by your last prompt.

  Each row shows the folder, the prompt count and when you last used it.
- **Desktop:** defaults to the session's saved desktop, or the next empty desktop if it has none. Tick
  **Save desktop N for this session** to remember a different choice.
- **Launch:**
  - If the desktop has a kitty window with remote control on, the session opens as a **new tab** in it.
  - Otherwise it opens a **new kitty window** on that desktop, placed in the rightmost tile of the
    desktop's tiling layout (Meta+T), or the right half if there is none.

  Either way you get Claude on top and a shell in the same folder below (30% of the height), and Claude
  resumes with `claude --resume <id> -n <name>`. If the session started running meanwhile, its window is
  focused instead.

**⚙ Sessions** lists all named sessions with a desktop picker for each, saved as soon as you change it.

Saved desktops live in `~/.config/ccm/sessions.json`, the same list the `ccm` command from
`../claude-manager` uses. `ccm set-desktop NAME N` and this page change the same setting:

```json
{ "air-hub": { "cwd": "/home/me/air-hub", "session_id": "…", "desktop": 3, "shell_pct": 30 } }
```

### Opening as a tab: kitty remote control

The dashboard opens a tab through kitty's remote control socket, which is off by default. Add this to
`~/.config/kitty/kitty.conf`:

```conf
allow_remote_control socket-only
listen_on unix:${XDG_RUNTIME_DIR}/kitty-{kitty_pid}.sock
```

Each kitty process then listens on its own socket in `$XDG_RUNTIME_DIR`, which only you can access.
Kitty windows that were already open before the change don't have one, so the dashboard opens a new
window on their desktops until you restart them. Windows the dashboard opens always have remote control
on, so later sessions for that desktop open as tabs in them.

## Voice control (StackChan MCP)

`kddash_mcp.py` is an MCP server (stdio) with four tools:

| Tool | Example request |
|---|---|
| `list_claude_sessions` | "What are my Claude sessions doing?" |
| `go_to_desktop(number)` | "Go to desktop 3" |
| `go_to_claude_session(project)` | "Open the air hub session" |
| `go_to_waiting_claude_session` | "Take me to the one that needs me" |
| `mark_claude_session_idle(project)` | "This session is finished", "mark all idle": stops the blinking |

It needs the kddash service running. It reads the token from `~/.config/kddash/token` and talks to
`http://127.0.0.1:8765`; override these with `KDDASH_TOKEN` and `KDDASH_URL`. It needs Python with
`fastmcp`.

To use it with the StackChan bridge (`mcp_pipe.py` from
[78/mcp-calculator](https://github.com/78/mcp-calculator)), add it to the bridge's `mcp_config.json` and
restart the bridge:

```json
"kde-desktops": {
  "type": "stdio",
  "command": "python",
  "args": ["/path/to/kde-desktops-dashboard/kddash_mcp.py"]
}
```

List the tools without the cloud: `fastmcp inspect kddash_mcp.py`.

**Privacy:** what these tools return (project folder names and Claude task titles, cut to 60
characters) is sent to the XiaoZhi cloud.

## Managing the service

```bash
systemctl --user status kddash        # is it running?
journalctl --user -u kddash -f        # logs
systemctl --user restart kddash       # restart
./install.sh --uninstall              # stop and remove the service (keeps the token)
```

To run it by hand instead, for development: `python3 kddash.py` (stop the service first, since both use
the same port).

## How it works

```
KWin ──(kwin/kddash.js pushes window/desktop snapshots over D-Bus)──▶ kddash.py ──(SSE)──▶ browser
                                                                       │    ▲
             /proc process tree + ~/.claude/sessions/<pid>.json ───────┘    └── tap: POST /api/activate
```

- `kddash.py` owns the D-Bus name `org.kddash` and loads `kwin/kddash.js` into KWin. The script sends a
  snapshot of all windows and desktops whenever one changes.
- For each window, kddash walks the process tree under the window's PID to find `claude` processes. Each
  process's status comes from Claude Code's own state file `~/.claude/sessions/<pid>.json`. That works
  for kitty splits that aren't focused, where the window title shows another split. If the file is
  missing, kddash falls back to the status glyph Claude puts in the terminal title.
- It also re-checks every second, because status changes in an unfocused split don't cause any KWin
  event.
- Switching desktops or focusing a window runs a short one-off KWin script.
- `launcher.py` lists named sessions (session names and titles from `~/.claude/projects/*/*.jsonl`, plus
  `ccm`'s saved list) and builds the kitty commands. New kitty windows are started with
  `systemd-run --user --scope`, so they keep running when the service restarts.
- `static/index.html` is the whole front end: no build step, no dependencies.

### HTTP API

Every endpoint except the static files needs `?t=<token>`.

| Endpoint | Purpose |
|---|---|
| `GET /events` | Server-Sent Events stream of the full state (JSON) |
| `GET /api/state` | Current state as JSON |
| `POST /api/activate?desktop=<id>` or `?window=<id>` | Switch desktop, or focus a window |
| `POST /api/snooze?pid=<claude pid>&on=1\|0` | Mark a session idle, or unmark it |
| `GET /api/sessions` | Named sessions (saved desktop, running or not) and desktops (empty, has a kitty that accepts tabs) |
| `POST /api/sessions/desktop?key=<key>&desktop=<n>` | Save a session's desktop (`0` clears it) |
| `POST /api/launch?key=<key>&desktop=<n>&remember=1\|0` | Open a session on a desktop, as a tab or a new kitty window |

## Limitations

- Session status comes from `~/.claude/sessions/<pid>.json`, an internal Claude Code file. A Claude Code
  update could change its format; the title glyph is used as a fallback.
- Terminals that run several windows from one process (Konsole, `kitty --single-instance`) show all of
  that process's Claude sessions on each of their windows. Separate kitty processes, the default, are
  fine.
- "Idle" marks are kept in memory, so restarting the service clears them.
- The page is plain HTTP on your LAN, protected by the token in the URL. Don't expose the port to the
  internet.

## Files

| Path | What it is |
|---|---|
| `kddash.py` | Service: D-Bus listener, session detection, launching, HTTP/SSE server |
| `launcher.py` | Named sessions, saved desktops (shared with `ccm`), kitty launch commands |
| `kwin/kddash.js` | KWin script that pushes window/desktop snapshots |
| `static/` | The dashboard page, PWA manifest and icon |
| `kddash_mcp.py` | Optional MCP server for voice assistants |
| `install.sh` | Installs or uninstalls the systemd user service |
