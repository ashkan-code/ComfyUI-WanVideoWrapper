"""
Watchdog — keeps the ICT scanner alive 24/7.
Restart on crash, rotate log at 50 MB.
"""

import os
import subprocess
import sys
import time
from datetime import datetime

DIR      = os.path.dirname(os.path.abspath(__file__))
LOG      = os.path.join(DIR, "logs", "bitunix_live.log")
PIDFILE  = os.path.join(DIR, "logs", "bitunix.pid")
WLOG     = os.path.join(DIR, "logs", "watchdog.log")
WPID     = os.path.join(DIR, "logs", "watchdog.pid")
MAX_LOG  = 50 * 1024 * 1024   # 50 MB
CMD      = [sys.executable, "-m", "bitunix_scanner.main", "--live", "--auto"]
RESTART_DELAY = 15


def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def wlog(msg):
    line = f"[{ts()}] {msg}\n"
    sys.stdout.write(line)
    sys.stdout.flush()
    try:
        with open(WLOG, "a") as f:
            f.write(line)
    except Exception:
        pass


def rotate_log():
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > MAX_LOG:
            os.rename(LOG, LOG + ".old")
            wlog("Log rotated")
    except Exception:
        pass


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def read_pid():
    try:
        return int(open(PIDFILE).read().strip())
    except Exception:
        return None


def start_scanner():
    rotate_log()
    lf = open(LOG, "a")
    p  = subprocess.Popen(CMD, cwd=DIR, stdout=lf, stderr=lf,
                           start_new_session=True)
    with open(PIDFILE, "w") as f:
        f.write(str(p.pid))
    wlog(f"Scanner started  PID={p.pid}")
    return p.pid


def main():
    os.makedirs(os.path.join(DIR, "logs"), exist_ok=True)

    # Write own PID
    with open(WPID, "w") as f:
        f.write(str(os.getpid()))

    wlog(f"Watchdog started  PID={os.getpid()}")

    pid = read_pid()
    if not (pid and alive(pid)):
        pid = start_scanner()

    while True:
        time.sleep(30)
        pid = read_pid()
        if not (pid and alive(pid)):
            wlog("Scanner died — restarting …")
            time.sleep(RESTART_DELAY)
            pid = start_scanner()


if __name__ == "__main__":
    main()
