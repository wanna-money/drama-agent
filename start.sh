#!/bin/bash
# Start Drama Agent — backend (port 8888) + frontend dev server (port 5173).
# PIDs are written to .run/ so stop.sh can shut both down cleanly.
set -e

cd "$(dirname "$0")"

BACKEND_PORT=8888
FRONTEND_PORT=5173
RUN_DIR=".run"

# Activate venv if present
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

mkdir -p data/uploads data/outputs "$RUN_DIR"

# Start FastAPI backend in background
echo "Starting backend on http://localhost:${BACKEND_PORT} ..."
uv run uvicorn drama_agent.main:app \
    --host 0.0.0.0 \
    --port "$BACKEND_PORT" \
    --reload \
    --reload-dir src &
BACKEND_PID=$!
echo "$BACKEND_PID" > "$RUN_DIR/backend.pid"

# Start frontend dev server
echo "Starting frontend on http://localhost:${FRONTEND_PORT} ..."
(cd frontend && pnpm dev) &
FRONTEND_PID=$!
echo "$FRONTEND_PID" > "$RUN_DIR/frontend.pid"

echo ""
echo "Drama Agent is running:"
echo "  Frontend: http://localhost:${FRONTEND_PORT}"
echo "  Backend:  http://localhost:${BACKEND_PORT}"
echo "  API docs: http://localhost:${BACKEND_PORT}/docs"
echo ""
echo "Stop with Ctrl+C, or run ./stop.sh from another terminal."

# On Ctrl+C: stop both and clear PID files
cleanup() {
    kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
    rm -f "$RUN_DIR/backend.pid" "$RUN_DIR/frontend.pid"
    exit 0
}
trap cleanup INT TERM
wait $BACKEND_PID $FRONTEND_PID
