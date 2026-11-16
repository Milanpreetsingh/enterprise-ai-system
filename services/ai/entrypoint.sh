#!/bin/bash
set -e

cleanup() {
    echo "[AI Entrypoint] Termination signal received. Initiating graceful shutdown..."
    kill -TERM "$GRPC_PID" 2>/dev/null || true
    kill -TERM "$UVICORN_PID" 2>/dev/null || true
    wait
    exit 0
}
trap cleanup SIGTERM SIGINT

echo "[AI Entrypoint] Launching Python AI gRPC server on port 50053..."
python app/grpc_server.py &
GRPC_PID=$!

echo "[AI Entrypoint] Launching FastAPI HTTP server on port 8000..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
UVICORN_PID=$!

# Wait for any process to exit
wait -n "$GRPC_PID" "$UVICORN_PID"

