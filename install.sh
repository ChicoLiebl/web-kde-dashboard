#!/usr/bin/env bash
# Install (or uninstall) kddash as a systemd user service that starts with the Plasma session.
#
#   ./install.sh               install / update and (re)start the service
#   KDDASH_PORT=9000 ./install.sh   same, on another port
#   ./install.sh --uninstall   stop and remove the service
set -euo pipefail

SERVICE=kddash.service
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="$UNIT_DIR/$SERVICE"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${KDDASH_PORT:-8765}"
TOKEN_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/kddash/token"

die() { echo "error: $*" >&2; exit 1; }

if [[ "${1:-}" == "--uninstall" ]]; then
    systemctl --user disable --now "$SERVICE" 2>/dev/null || true
    rm -f "$UNIT"
    systemctl --user daemon-reload
    echo "kddash service removed. (The access token in $TOKEN_FILE was kept.)"
    exit 0
fi

# --- checks
command -v systemctl >/dev/null || die "systemd is required"
PYTHON="$(command -v python3)" || die "python3 not found"
"$PYTHON" -c "import dbus_next" 2>/dev/null \
    || die "Python package dbus-next is missing. Arch: sudo pacman -S python-dbus-next  |  Debian/Ubuntu: sudo apt install python3-dbus-next  |  pip: pip install --user dbus-next"
[[ "${XDG_SESSION_TYPE:-}" == "wayland" ]] || echo "warning: this was built for Plasma 6 on Wayland; XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-unset}" >&2

# --- unit
mkdir -p "$UNIT_DIR"
cat > "$UNIT" <<EOF
[Unit]
Description=kddash: KDE desktops + Claude Code sessions dashboard
Documentation=file://$REPO/README.md
# Needs KWin and the session D-Bus, so it lives and dies with the graphical session.
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=simple
ExecStart=$PYTHON $REPO/kddash.py
Environment=KDDASH_PORT=$PORT
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical-session.target
EOF

systemctl --user daemon-reload
systemctl --user enable "$SERVICE" >/dev/null
systemctl --user restart "$SERVICE"
echo "Installed $UNIT"

# --- wait for it to come up and show the URL
up=0
for _ in $(seq 40); do
    if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then up=1; break; fi
    systemctl --user is-failed --quiet "$SERVICE" && break
    sleep 0.25
done
((up)) || die "service failed to start; see: journalctl --user -u $SERVICE -n 50"

IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") print $(i + 1)}')"
URL="http://${IP:-<this-pc-ip>}:$PORT/?t=$(cat "$TOKEN_FILE")"
echo
echo "kddash is running. Open this on your tablet (same network):"
echo "  $URL"
command -v qrencode >/dev/null && qrencode -t ansiutf8 "$URL"

if systemctl is-active --quiet firewalld 2>/dev/null; then
    echo
    echo "firewalld is active. If the tablet can't connect, open the port in your network's zone, e.g.:"
    echo "  sudo firewall-cmd --permanent --zone=home --add-port=$PORT/tcp && sudo firewall-cmd --reload"
fi
