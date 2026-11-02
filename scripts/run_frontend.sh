#!/usr/bin/env bash
# Start the Vite dev server on :3000 (proxies /api to the backend).
source "$(dirname "$0")/_common.sh"
cd "$REPO_ROOT/frontend"
exec npm run dev -- --host 0.0.0.0 --port "${FRONTEND_PORT:-3000}"
