#!/bin/sh
# IT Asset Manager - macOS / Linux agent installer
#
# Installs the inventory agent and schedules it as root: daily (randomised
# within 30 min) and shortly after boot. Then runs it once.
#
#   curl -fsSL http://itam.corp.local:8080/api/agents/download/install_agent.sh \
#     | sudo sh -s -- --server http://itam.corp.local:8080 --token <agent-token>
#   sudo sh install_agent.sh --uninstall
#
# If itam_agent.py sits next to this script it is used as-is (air-gapped
# installs); otherwise it is downloaded from the server.
#
#   Linux:  /opt/itam, token in /etc/itam/agent.env (0600), systemd timer (cron fallback)
#   macOS:  /Library/ITAM, token in /Library/ITAM/agent.env (0600), LaunchDaemon
set -eu

SERVER=""
TOKEN=""
UNINSTALL=0
while [ $# -gt 0 ]; do
    case "$1" in
        --server) SERVER="${2:-}"; shift 2 ;;
        --token) TOKEN="${2:-}"; shift 2 ;;
        --uninstall) UNINSTALL=1; shift ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root (sudo)." >&2
    exit 1
fi

OS="$(uname -s)"
if [ "$OS" = "Darwin" ]; then
    DIR="/Library/ITAM"
    ENV_FILE="$DIR/agent.env"
    PLIST="/Library/LaunchDaemons/com.itam.agent.plist"
else
    DIR="/opt/itam"
    ENV_FILE="/etc/itam/agent.env"
fi
SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd || echo "")"

uninstall() {
    if [ "$OS" = "Darwin" ]; then
        launchctl bootout system "$PLIST" 2>/dev/null || launchctl unload "$PLIST" 2>/dev/null || true
        rm -f "$PLIST"
    elif command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
        systemctl disable --now itam-agent.timer 2>/dev/null || true
        rm -f /etc/systemd/system/itam-agent.service /etc/systemd/system/itam-agent.timer
        systemctl daemon-reload
    fi
    rm -f /etc/cron.d/itam-agent
    rm -rf "$DIR" /etc/itam
    echo "ITAM agent removed."
}

if [ "$UNINSTALL" -eq 1 ]; then
    uninstall
    exit 0
fi

if [ -z "$SERVER" ] || [ -z "$TOKEN" ]; then
    echo "Usage: install_agent.sh --server http://itam.corp.local:8080 --token <agent-token>" >&2
    exit 2
fi
SERVER="${SERVER%/}"

# Python 3.7+. On macOS use the system interpreter (launchd runs as root
# without the admin's PATH or Homebrew).
if [ "$OS" = "Darwin" ]; then
    PYTHON="/usr/bin/python3"
else
    PYTHON="$(command -v python3 || true)"
fi
if [ -z "$PYTHON" ] || ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 7))' 2>/dev/null; then
    echo "Python 3.7+ is required (macOS: install the Command Line Tools: xcode-select --install)." >&2
    exit 1
fi

mkdir -p "$DIR" "$(dirname "$ENV_FILE")"
chmod 755 "$DIR"
if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/itam_agent.py" ]; then
    cp "$SCRIPT_DIR/itam_agent.py" "$DIR/itam_agent.py"
    echo "Using agent from $SCRIPT_DIR"
elif command -v curl >/dev/null 2>&1; then
    curl -fsSL "$SERVER/api/agents/download/itam_agent.py" -o "$DIR/itam_agent.py"
    echo "Downloaded agent from $SERVER"
else
    wget -qO "$DIR/itam_agent.py" "$SERVER/api/agents/download/itam_agent.py"
    echo "Downloaded agent from $SERVER"
fi
chmod 755 "$DIR/itam_agent.py"

# Token stays out of process lists and world-readable unit files.
umask 077
printf 'ITAM_SERVER=%s\nITAM_TOKEN=%s\n' "$SERVER" "$TOKEN" > "$ENV_FILE"
chmod 600 "$ENV_FILE"
umask 022

RUN="set -a; . $ENV_FILE; exec $PYTHON $DIR/itam_agent.py"

if [ "$OS" = "Darwin" ]; then
    cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.itam.agent</string>
    <key>ProgramArguments</key>
    <array><string>/bin/sh</string><string>-c</string><string>sleep \$((RANDOM % 1800)); $RUN</string></array>
    <key>StartCalendarInterval</key>
    <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
    <key>StandardOutPath</key><string>$DIR/agent.log</string>
    <key>StandardErrorPath</key><string>$DIR/agent.log</string>
</dict>
</plist>
PLISTEOF
    chown root:wheel "$PLIST"
    chmod 644 "$PLIST"
    launchctl bootout system "$PLIST" 2>/dev/null || true
    launchctl bootstrap system "$PLIST" 2>/dev/null || launchctl load -w "$PLIST"
    echo "LaunchDaemon com.itam.agent installed (daily ~09:00)."
elif command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
    cat > /etc/systemd/system/itam-agent.service <<UNITEOF
[Unit]
Description=IT Asset Manager inventory agent
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
EnvironmentFile=$ENV_FILE
ExecStart=$PYTHON $DIR/itam_agent.py
UNITEOF
    cat > /etc/systemd/system/itam-agent.timer <<UNITEOF
[Unit]
Description=Daily IT Asset Manager inventory

[Timer]
OnBootSec=10min
OnCalendar=daily
RandomizedDelaySec=30min
Persistent=true

[Install]
WantedBy=timers.target
UNITEOF
    systemctl daemon-reload
    systemctl enable --now itam-agent.timer
    echo "systemd timer itam-agent.timer enabled (daily + 10 min after boot)."
else
    # No systemd (containers, older distros): cron.
    MINUTE=$(awk 'BEGIN { srand(); print int(rand() * 60) }')
    printf '%s 9 * * * root /bin/sh -c "%s"\n' "$MINUTE" "$RUN" > /etc/cron.d/itam-agent
    chmod 644 /etc/cron.d/itam-agent
    echo "cron job /etc/cron.d/itam-agent installed (daily 09:$MINUTE)."
fi

echo "Running a first inventory now..."
if /bin/sh -c "$RUN"; then
    echo "Done. This machine will report daily."
else
    echo "The first report failed (see above). The schedule will retry; check the server address and token." >&2
fi
