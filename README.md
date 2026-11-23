# kddash: KDE desktops dashboard

A live dashboard of your KDE Plasma virtual desktops and the Claude Code sessions running on them, made
for a tablet (or any browser) on your local network. Tap a card to switch to that desktop on the PC.

- One card per desktop that has windows, sized to fill the screen.
- Each Claude Code session shows its project and task title, and a pixel crab that acts out what it's
  doing and wears a hat for its kind of work (see [The crabs](#the-crabs)). Its box's edge and card
  show its status:
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
- The **+ New desktop** bar at the bottom opens a launcher: pick a named Claude Code session that isn't
  running and a desktop, and it opens there in kitty (see [Launching sessions](#launching-sessions)).
  **Just go to desktop N** switches to the next empty desktop instead.
- **⚙ Sessions** in the top bar sets the desktop each named session opens on.
- The **Tasks** tab shows today's tasks from [TaskHub](../taskhub) (see [Tasks tab](#tasks-tab)).
- **⛶ Fullscreen** in the top bar hides the browser and Android bars.
- **▦ Even / ▦ Dynamic** in the top bar switches the card layout, remembered per device:
  - **Even** (default): all cards the same size, in a grid.
  - **Dynamic**: cards stay in desktop order, in rows. A card gets wider for each Claude session on it, and
    its sessions sit side by side. Cards without sessions are narrower.
- **☾ Sleep** in the top bar turns the tablet's screen off, for tablets kept always on (see
  [Turning the tablet screen off](#turning-the-tablet-screen-off)).
- Every kitty window with a Claude session gets a faint background pattern for its kind of work, so you
  can see at a glance which session you're in (see [Kitty patterns by kind](#kitty-patterns-by-kind)).
- A widget for the KDE panel shows the same Desktops screen in a popup (see [Panel widget](#panel-widget)).
- Optional: an MCP server lets a voice assistant (StackChan / XiaoZhi) list the sessions and switch
  desktops for you (see [Voice control](#voice-control-stackchan-mcp)).

No app to install on the tablet: it's a web page served by the PC.

### The crabs

Every Claude session gets a pixel crab. Its pose shows what the session is doing:

| Session | Crab |
|---|---|
| Editing files or running commands | Works with the tools of its kind of work (below) |
| Reading files | Scans a page with a magnifier |
| On the web | Watches a turning globe |
| Planning (todo list) | Ticks boxes on a clipboard |
| Running subagents | Walks with a small crab in tow |
| Thinking | Looks up, thought bubbles rising |
| Any other tool (MCP…) | Walks along, "…" |
| Needs you | Arms up under a blinking "?" ("!" for a permission prompt) |
| Just finished | Hops waving a checkered flag for 6 s, then holds the flag up until you get to it |
| Marked idle | Greyed out and asleep, "z z" |

Its hat and tools show the kind of work:

| Kind | Hat | Tools |
|---|---|---|
| Software | Beanie | A terminal with a blinking cursor |
| Firmware | Headband with an antenna, its LED blinking while it works | A chip with a status LED |
| PCB | Headband with a jeweller's loupe | A board and a soldering iron, sparks and smoke |
| CAD / mechanical | Hard hat | A turning wireframe cube |

The kind comes from the session's folder. The deepest folder in its path named like `firmware`, `fw`,
`hardware`, `pcb`, `kicad`, `mechanical`, `cad`, `3d-printing` or `software` (a number prefix such as
`01-firmwares` is fine) decides it. Otherwise the files in the folder do: a `.kicad_pro` means PCB,
`sdkconfig` or `platformio.ini` means firmware, and `.FCStd`, `.step`, `.scad` or `.3mf` mean CAD.
Otherwise a session name starting `fw-` or `pcb-` decides, and anything else is software. To set it
yourself, add folders to `~/.config/kddash/kinds.json`; they apply to everything under them:

```json
{"~/work/odd-project": "pcb", "~/playground/printer": "cad"}
```

What a working session is doing comes from the end of its transcript
(`~/.claude/projects/*/<session id>.jsonl`): the last tool it called. Open the dashboard with `#crabs`
at the end of the address for a page with every crab.

The style is inspired by the critters of [agents-deck](https://github.com/brushknight/agents-deck); the
sprites here are drawn from scratch (`static/crabs.js`).

### Kitty patterns by kind

kddash gives every kitty window that runs a Claude session a background pattern for its kind of work,
about a second after Claude starts. The background stays your theme's colour; only the pattern's lines
are coloured. That covers sessions opened from the dashboard, from `ccm` or by typing `claude` yourself.

| Kind | Pattern | Line colour (dark / light theme) |
|---|---|---|
| PCB | `pin-grid`: chip footprints, ball grids and pins over a faint dot grid | `#4a3560` / `#d9c3e6` purple |
| Firmware | `hex-dump`: scattered columns of hex bytes | `#2f5a3c` / `#bfdcc4` green |
| Software | `icon-graph`: a network of links with Linux, Git, Python, KDE, Claude, Arch, GitHub, Bash, KiCad, Espressif, C and FreeCAD icons | `#33476b` / `#c2d1ec` blue |
| CAD / mechanical | `iso-blocks`: wireframe blocks of different sizes and heights, in loose clusters on an isometric floor | `#5c4a22` / `#e8d39a` amber |

- `patterns.py` draws each pattern as a seamless tile on kitty's own background colour. kddash renders
  the tiles it needs into `~/.cache/kddash/patterns/` with `rsvg-convert` (part of librsvg), and again
  when `patterns.py` changes. Run `python3 patterns.py OUTDIR [--light]` to look at them.
- kddash picks the dark or light colours from kitty's background, including its automatic dark/light
  themes; it checks every 60 s.
- kitty sets background images per window, not per tab. A window whose tabs are of different kinds shows
  the pattern of its active tab, and switches when you change tabs.
- When the window's sessions exit, the pattern goes.
- It works through kitty's remote control (see
  [Opening as a tab](#opening-as-a-tab-kitty-remote-control)). Kitty windows without it stay as they
  are.

**Turning it on or off:** use the **Kitty background pattern by kind** checkbox at the top of
**⚙ Sessions**. Turning it off removes every pattern straight away. The setting and any colours of your
own live in `~/.config/kddash/backgrounds.json`:

```json
{"enabled": true, "pcb": "#5a4070", "pcb-light": "#e0cce9", "software": null}
```

A kind set to `null` gets no pattern.

The software icons are from [Simple Icons](https://simpleicons.org) (CC0), in `patterns/icons/`. The
logos themselves belong to their projects.

## Panel widget

`plasmoid/` is a Plasma 6 widget, **Claude Desktops**, for the top bar or any panel:

- **The panel icon** is a crab. Its yellow badge counts the sessions that need you, the same ones that
  blink on the tablet, and blinks while one of them waits on a permission or a question. A blue dot
  means something is working and nothing needs you. Hover it for the counts.
- **Click the crab** for a popup with the dashboard's Desktops screen: the same page as the tablet.
  - Click a card to go to that desktop, or a session to focus its window. The popup closes as KWin
    switches.
  - Right-click a desktop for **Mark idle** and **Open Claude session here**.
  - **+ New desktop** launches a session.
  - **⚙ Sessions** has the session desktops and the kitty pattern switch.
  - The Tasks tab works too. Fullscreen and tablet sleep are hidden in the popup.
  - Drag the popup's edge to resize it.

Install it, then add it in the panel's **Edit Mode → Add Widgets…** by searching "Claude Desktops":

```bash
kpackagetool6 -t Plasma/Applet -i plasmoid    # first time
kpackagetool6 -t Plasma/Applet -u plasmoid    # after changing it; then restart plasmashell:
systemctl --user restart plasma-plasmashell
```

It needs the kddash service running and reads its token from `~/.config/kddash/token`. Its settings have
the service's address, by default `http://127.0.0.1:8765`.

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

### Turning the tablet screen off

A web page can't turn the screen off by itself, so the PC does it. **☾ Sleep** asks kddash to send the
sleep key to the tablet over network ADB (`adb connect <tablet>:5555`, then
`input keyevent KEYCODE_SLEEP`). The button only shows on a device whose ADB port answers, and it acts on
the device that tapped it, so there is nothing to configure.

- The PC needs `adb` (Arch: `sudo pacman -S android-tools`).
- The tablet needs ADB over the network. Wall-mounted Android panels usually have it on. On a normal
  tablet, turn on wireless debugging (Developer options), or connect it by USB once and run
  `adb tcpip 5555`.
- The first time, the tablet may ask to **Allow USB debugging** from this PC. Tick "Always allow".

kddash also wakes the tablet when you unlock the PC. It listens for Plasma's
`org.freedesktop.ScreenSaver.ActiveChanged(false)` signal. To turn that off, set
`KDDASH_WAKE_ON_UNLOCK=0` in the service:

```bash
systemctl --user edit kddash
# add these two lines in the editor:
#   [Service]
#   Environment=KDDASH_WAKE_ON_UNLOCK=0
```

To turn the screen back on by hand, touch it. That works on many panels, but some ignore touch while the
screen is off. Otherwise press the tablet's power button, or wake it from the PC. kddash remembers the
last tablet that opened the dashboard:

```bash
curl -X POST "http://127.0.0.1:8765/api/tablet/wake?t=$(cat ~/.config/kddash/token)"
```

The StackChan tool `set_tablet_screen` does the same by voice ("turn off the tablet").

**Security:** anyone on your network can use an open ADB port to fully control the tablet, with or
without kddash. That's how these panels ship; keep them on a network you trust.

## Tasks tab

**Tasks** in the top bar shows your [TaskHub](../taskhub) tasks for today; its badge counts the open ones.
Swipe left or right anywhere on the page to switch between Desktops and Tasks, or tap the tab names. The tablet remembers which tab you left it on, and `…/#tasks` opens it directly. While Tasks is showing,
any Claude session changing status (starting, finishing its turn, asking for permission) switches back
to Desktops.

A task shows when it isn't done and one of these is true:

- it's in progress;
- it's due today or overdue;
- its start date has come (blocked tasks only show then too).

Tasks you finished today stay at the bottom, crossed out. That's the same "today" the StackChan voice
agent uses. Tasks are grouped into **Overdue**, **Due today**, **In progress**, **Blocked**, **Started**
and **Done today**, most urgent first (priority, then deadline). Each card shows the project color,
priority, due date, repo and checklist progress. Tap one for its checklist and description. The tab is
read-only: change tasks in TaskHub itself.

kddash uses the TaskHub CLI's config, `~/.config/taskhub/config.toml` (`url` and `token`; see the TaskHub
README), or the `TASKHUB_URL` / `TASKHUB_TOKEN` environment variables. It refreshes every minute while
the page is open; **↻ Refresh** fetches right away.

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

A session opens in its saved `cwd`, with two exceptions, and in both the list's `cwd` is corrected so
`ccm` follows too:
- If you have since resumed the session from another folder (Claude records where you start it in
  `~/.claude/history.jsonl`), the newest such folder wins.
- If the saved folder is gone, the folder the session itself records is used.

A saved folder the session has never run in counts as set on purpose and is kept.

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

## Sessions marking themselves idle (Claude Code MCP)

`claude_session_mcp.py` is a small MCP server for Claude Code itself, with one tool,
`mark_this_session_idle`. Ask a session to "set yourself idle" (or tell it you're done with it for now)
and it marks itself idle on the dashboard.

- **When the mark starts:** the session is still working while it calls the tool, so the mark starts
  when its turn finishes.
- **When it clears:** at your next prompt, like a mark set from the dashboard.
- **Finding the session:** Claude Code runs its MCP servers as child processes, so the server finds its
  session by walking up to the nearest `claude` process.

It uses only the Python standard library. Register it once for every session:

```bash
claude mcp add --scope user kddash -- python3 /path/to/kde-desktops-dashboard/claude_session_mcp.py
```

Sessions that are already running pick it up after `/mcp` → reconnect, or a restart.

## Voice control (StackChan MCP)

`kddash_mcp.py` is an MCP server (stdio) with these tools:

| Tool | Example request |
|---|---|
| `list_claude_sessions` | "What are my Claude sessions doing?": status, kind of work, and what a working one is doing |
| `go_to_desktop(number)` | "Go to desktop 3" |
| `go_to_claude_session(project)` | "Show me the air hub session" |
| `go_to_waiting_claude_session` | "Take me to the one that needs me" |
| `mark_claude_session_idle(project)` | "This session is finished", "mark all idle": stops the blinking |
| `list_launchable_claude_sessions` | "Which sessions can I open?": named sessions that aren't running, most used first |
| `launch_claude_session(name, desktop)` | "Open cert manager", "start the ccm session on desktop 5" |
| `set_tablet_screen(on)` | "Turn off the tablet", "wake the dashboard screen" |

`launch_claude_session` works like the dashboard's launcher. It opens the session on the desktop you
name, or on its saved desktop, or on the next empty desktop. It doesn't change the saved desktop.

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
- While a session works, kddash reads the last 64 KB of its transcript (only when the file has changed)
  to see which tool it's using. `kinds.py` works out the kind of work. Each session in the state carries `kind` (`software`, `firmware`, `pcb`
  or `cad`) and `activity` (`read`, `write`, `bash`, `web`, `plan`, `delegate`, `think`, `run`, or
  `null` when it isn't working).
- It also re-checks every second, because status changes in an unfocused split don't cause any KWin
  event. When the Claude sessions in kitty change, it lists that kitty's windows and tabs over its
  socket and sets their background pattern with `kitten @ set-background-image`.
- Switching desktops or focusing a window runs a short one-off KWin script.
- `launcher.py` lists named sessions (session names and titles from `~/.claude/projects/*/*.jsonl`, plus
  `ccm`'s saved list) and builds the kitty commands. New kitty windows are started with
  `systemd-run --user --scope`, so they keep running when the service restarts.
- `static/index.html` is the whole front end, with the crab sprites in `static/crabs.js`: no build step,
  no dependencies. The crabs are drawn once per pose on a canvas and animated with CSS, so they keep
  moving smoothly while the cards re-render.

### HTTP API

Every endpoint except the static files needs `?t=<token>`.

| Endpoint | Purpose |
|---|---|
| `GET /events` | Server-Sent Events stream of the full state (JSON) |
| `GET /api/state` | Current state as JSON |
| `POST /api/activate?desktop=<id>` or `?window=<id>` | Switch desktop, or focus a window |
| `POST /api/snooze?pid=<claude pid>&on=1\|0[&after_turn=1]` | Mark a session idle, or unmark it. `after_turn=1`: from the session itself, idle once its current turn finishes. 404 for an unknown pid |
| `GET /api/sessions` | Named sessions (saved desktop, running or not) and desktops (empty, has a kitty that accepts tabs) |
| `POST /api/sessions/desktop?key=<key>&desktop=<n>` | Save a session's desktop (`0` clears it) |
| `POST /api/launch?key=<key>&desktop=<n>&remember=1\|0` | Open a session on a desktop, as a tab or a new kitty window |
| `GET /api/tasks[?refresh=1]` | Today's TaskHub tasks by section (cached for 60 s) |
| `GET /api/tablet` | `{"sleep": true}` if the requesting device's ADB port answers (and remembers it) |
| `POST /api/tablet/sleep`, `POST /api/tablet/wake` | Screen off / on for the requesting device; from the PC itself, the remembered tablet |
| `GET /api/kitty-colors`, `POST /api/kitty-colors?enabled=1\|0` | Kitty patterns by kind: whether they're on, the line colours and the pattern per kind. Turning them off removes every pattern |

## Limitations

- Session status comes from `~/.claude/sessions/<pid>.json`, an internal Claude Code file. A Claude Code
  update could change its format; the title glyph is used as a fallback. The crab's activity reads the
  transcript format, which could change too; the crab then just walks while the session works.
- One kitty process can own several windows, for example after you drag a tab out of a window or onto
  another desktop. kddash then asks kitty, over its remote-control socket, which tabs each window holds,
  and matches the windows to KWin's by title. Without remote control (see
  [Launching sessions](#opening-as-a-tab-kitty-remote-control)), or if two of its windows show the same
  title, each of those windows shows all of that process's Claude sessions. The same goes for other
  terminals that run several windows from one process, such as Konsole.
- "Idle" marks are kept in memory, so restarting the service clears them.
- The page is plain HTTP on your LAN, protected by the token in the URL. Don't expose the port to the
  internet.

## Files

| Path | What it is |
|---|---|
| `kddash.py` | Service: D-Bus listener, session detection, launching, HTTP/SSE server |
| `kinds.py` | Kind of work per session folder, and the kitty pattern and colours for each kind |
| `patterns.py`, `patterns/icons/` | Draws the kitty background patterns; the software pattern's icons (Simple Icons, CC0) |
| `plasmoid/` | Plasma panel widget: crab icon with a badge, the dashboard page in its popup |
| `launcher.py` | Named sessions, saved desktops (shared with `ccm`), kitty launch commands |
| `tasks.py` | Today's tasks from TaskHub, for the Tasks tab |
| `kwin/kddash.js` | KWin script that pushes window/desktop snapshots |
| `static/` | The dashboard page, the crab sprites (`crabs.js`), PWA manifest and icon |
| `kddash_mcp.py` | Optional MCP server for voice assistants |
| `claude_session_mcp.py` | MCP server for Claude Code sessions: mark this session idle |
| `install.sh` | Installs or uninstalls the systemd user service |
