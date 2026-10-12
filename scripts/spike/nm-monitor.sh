#!/bin/bash
# Record timestamped `nmcli monitor` lines to /tmp/nm-monitor.log (no root needed).
# Runs as a transient user service because SteamOS sets KillUserProcesses=yes, which kills
# anything started from an SSH session as soon as that session ends.
#   bash nm-monitor.sh        start
#   bash nm-monitor.sh stop   stop
LOG=/tmp/nm-monitor.log
UNIT=nm-monitor

systemctl --user stop "$UNIT" 2>/dev/null
if [ "${1:-}" = "stop" ]; then
    echo "stopped"
    exit 0
fi

systemd-run --user --unit="$UNIT" --collect --quiet bash -c '
    nmcli monitor | while IFS= read -r line; do
        printf "%s %s\n" "$(date +%T.%3N)" "$line"
    done >>'"$LOG"' 2>&1
'
sleep 0.5
systemctl --user is-active --quiet "$UNIT" && echo "monitoring -> $LOG" || echo "failed to start"
