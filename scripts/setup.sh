#!/usr/bin/env bash
# Non-interactive setup: backend venv + requirements, frontend node_modules,
# local cluster and backend/.env.
source "$(dirname "$0")/_common.sh"
cd "$REPO_ROOT/backend"
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/pip install -q --disable-pip-version-check -r requirements.txt
cd "$REPO_ROOT"
if [ -f frontend/package.json ]; then
  cd frontend
  if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; else npm install --no-audit --no-fund; fi
  cd "$REPO_ROOT"
else
  echo "frontend/package.json not present yet; skipping npm install"
fi
bash scripts/db_start.sh
bash scripts/gen_env.sh
