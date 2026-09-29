#!/bin/sh
set -eu

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-8000}"

echo "[PROD] Running migrations: alembic upgrade head"
cd "$REPO_ROOT/backend/ai"
python -m alembic upgrade head

echo "[PROD] Starting FastAPI on 0.0.0.0:${PORT}"
cd "$REPO_ROOT/backend"
exec python -m uvicorn ai.main:app --host 0.0.0.0 --port "$PORT"
