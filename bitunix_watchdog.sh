#!/bin/bash
# ─────────────────────────────────────────────────────────────
# Bitunix ICT 24/7 Watchdog
# نگه می‌داره پروسه همیشه زنده باشه — اگر کرش کرد restart می‌کنه
# ─────────────────────────────────────────────────────────────

DIR="/home/user/ComfyUI-WanVideoWrapper"
LOG="$DIR/logs/bitunix_live.log"
WLOG="$DIR/logs/watchdog.log"
PIDFILE="$DIR/logs/bitunix.pid"
RESTART_DELAY=15   # ثانیه بین restart
MAX_LOG_MB=50      # حداکثر حجم log قبل از rotate

mkdir -p "$DIR/logs"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

rotate_log() {
    if [ -f "$LOG" ]; then
        size_mb=$(du -m "$LOG" 2>/dev/null | cut -f1)
        if [ "${size_mb:-0}" -ge "$MAX_LOG_MB" ]; then
            mv "$LOG" "${LOG}.$(date +%Y%m%d_%H%M%S).bak"
            # Keep only last 3 backups
            ls -t ${LOG}.*.bak 2>/dev/null | tail -n +4 | xargs rm -f 2>/dev/null
            echo "[$(ts)] Log rotated" >> "$WLOG"
        fi
    fi
}

start_bot() {
    rotate_log
    echo "[$(ts)] Starting bitunix scanner (top 100, auto mode)..." >> "$WLOG"
    cd "$DIR"
    nohup python -m bitunix_scanner.main --live --auto >> "$LOG" 2>&1 &
    echo $! > "$PIDFILE"
    echo "[$(ts)] Started PID=$(cat $PIDFILE)" >> "$WLOG"
}

is_running() {
    if [ ! -f "$PIDFILE" ]; then return 1; fi
    pid=$(cat "$PIDFILE")
    kill -0 "$pid" 2>/dev/null
}

echo "[$(ts)] Watchdog started (PID=$$)" >> "$WLOG"
echo $$ > "$DIR/logs/watchdog.pid"

# Kill any existing instance first
if [ -f "$PIDFILE" ]; then
    old_pid=$(cat "$PIDFILE")
    kill "$old_pid" 2>/dev/null
    sleep 2
fi

start_bot
sleep 10

while true; do
    if ! is_running; then
        echo "[$(ts)] Process died — restarting in ${RESTART_DELAY}s..." >> "$WLOG"
        sleep "$RESTART_DELAY"
        start_bot
        sleep 10
    fi
    sleep 30
done
