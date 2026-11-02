#!/usr/bin/env bash
# Start the FastAPI backend on :8000 (run in background by caller).
source "$(dirname "$0")/_common.sh"
pg_ready || bash "$REPO_ROOT/scripts/db_start.sh"
cd "$REPO_ROOT/backend"
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${BACKEND_PORT:-8000}"
