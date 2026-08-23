#!/bin/bash
# Stop Drama Agent — backend (port 8888) + frontend dev server (port 5173).
# Strategy: graceful kill by recorded PID first, then port-based fallback to
# reap any stragglers (e.g. a reloader child that outlived its parent).

cd "$(dirname "$0")"

BACKEND_PORT=8888
FRONTEND_PORT=5173
RUN_DIR=".run"

# Graceful TERM, wait briefly, then KILL if still alive.
stop_pid() {
    local pid="$1" name="$2"
    [ -z "$pid" ] && return 0
    if ! kill -0 "$pid" 2>/dev/null; then
        return 0  # already gone
    fi
    echo "Stopping ${name} (pid ${pid}) ..."
    kill "$pid" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        kill -0 "$pid" 2>/dev/null || return 0
        sleep 0.3
    done
    echo "  ${name} did not exit, sending KILL"
    kill -9 "$pid" 2>/dev/null || true
}

# Kill whatever is listening on a TCP port (macOS/Linux lsof).
stop_port() {
    local port="$1" name="$2"
    local pids
    pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
    [ -z "$pids" ] && return 0
    echo "Reaping ${name} listener(s) on :${port} -> ${pids}"
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 1
    pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        # shellcheck disable=SC2086
        kill -9 $pids 2>/dev/null || true
    fi
}

# 1) By recorded PID.
if [ -f "$RUN_DIR/backend.pid" ]; then
    stop_pid "$(cat "$RUN_DIR/backend.pid")" "backend"
    rm -f "$RUN_DIR/backend.pid"
fi
if [ -f "$RUN_DIR/frontend.pid" ]; then
    stop_pid "$(cat "$RUN_DIR/frontend.pid")" "frontend"
    rm -f "$RUN_DIR/frontend.pid"
fi

# 2) Port fallback — catches stragglers even if PID files are missing/stale.
stop_port "$BACKEND_PORT" "backend"
stop_port "$FRONTEND_PORT" "frontend"

echo "Drama Agent stopped."
