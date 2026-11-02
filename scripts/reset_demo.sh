#!/usr/bin/env bash
# Recreate the local development database and install reproducible demo data.
# Run with: bash scripts/reset_demo.sh
set -euo pipefail

source "$(dirname "$0")/_common.sh"

pg_ready || bash "$REPO_ROOT/scripts/db_start.sh"
bash "$REPO_ROOT/scripts/gen_env.sh"

"$PG_BIN/dropdb" --if-exists -f -h "$PGSOCK" -p "$PGPORT" -U "$PGUSER_LOCAL" etms_dev
"$PG_BIN/createdb" -h "$PGSOCK" -p "$PGPORT" -U "$PGUSER_LOCAL" etms_dev

cd "$REPO_ROOT/backend"
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m app.seed --profile demo

echo "etms_dev rebuilt and seeded with the demo profile."
