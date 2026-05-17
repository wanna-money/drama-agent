#!/bin/bash
# Start Drama Agent — backend (port 8000) + frontend dev server (port 5173)
set -e

# Activate venv if present
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# Create data directories
mkdir -p data/uploads data/outputs data/chroma

# Start FastAPI backend in background
echo "Starting backend on http://localhost:8000 ..."
uv run uvicorn drama_agent.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --reload \
    --reload-dir src &
BACKEND_PID=$!

# Start frontend dev server
echo "Starting frontend on http://localhost:5173 ..."
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "Drama Agent is running:"
echo "  Frontend: http://localhost:5173"
echo "  Backend:  http://localhost:8000"
echo "  API docs: http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop both servers."

# Wait for both, stop both on Ctrl+C
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT TERM
wait $BACKEND_PID $FRONTEND_PID
