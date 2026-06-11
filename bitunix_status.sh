#!/bin/bash
# نمایش وضعیت سیستم
DIR="/home/user/ComfyUI-WanVideoWrapper"
PIDFILE="$DIR/logs/bitunix.pid"
WPIDFILE="$DIR/logs/watchdog.pid"
LOG="$DIR/logs/bitunix_live.log"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  BITUNIX ICT — وضعیت سیستم"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Watchdog
if [ -f "$WPIDFILE" ] && kill -0 "$(cat $WPIDFILE)" 2>/dev/null; then
    echo "  Watchdog  : ACTIVE  (PID=$(cat $WPIDFILE))"
else
    echo "  Watchdog  : STOPPED"
fi

# Scanner
if [ -f "$PIDFILE" ] && kill -0 "$(cat $PIDFILE)" 2>/dev/null; then
    pid=$(cat "$PIDFILE")
    uptime_sec=$(ps -o etimes= -p "$pid" 2>/dev/null | tr -d ' ')
    if [ -n "$uptime_sec" ]; then
        h=$((uptime_sec/3600)); m=$(((uptime_sec%3600)/60))
        echo "  Scanner   : ACTIVE  (PID=$pid  uptime=${h}h${m}m)"
    else
        echo "  Scanner   : ACTIVE  (PID=$pid)"
    fi
else
    echo "  Scanner   : STOPPED"
fi

echo ""
echo "  آخرین لاگ:"
tail -8 "$LOG" 2>/dev/null | sed 's/^/    /'
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
