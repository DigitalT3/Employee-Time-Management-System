#!/usr/bin/env bash
# Shared settings for local runtime scripts (DEC-01). Sourced, not executed.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PG_BIN="${PG_BIN:-/usr/lib/postgresql/16/bin}"
PGPORT="${PGPORT:-5433}"
# The repository sits on a FUSE mount that does not persist chmod, and
# PostgreSQL requires PGDATA to be 0700. The cluster therefore lives in a
# user-owned directory outside the repo (override with ETMS_LOCALDB).
LOCALDB="${ETMS_LOCALDB:-$HOME/.etms-localdb}"
PGDATA="$LOCALDB/data"
PGSOCK="$LOCALDB/run"
PGLOG="$LOCALDB/log"
PGUSER_LOCAL="${PGUSER_LOCAL:-$(id -un)}"
export PGPORT
pg_ready() { "$PG_BIN/pg_isready" -q -h "$PGSOCK" -p "$PGPORT"; }
psql_local() { "$PG_BIN/psql" -h "$PGSOCK" -p "$PGPORT" -U "$PGUSER_LOCAL" -d postgres -v ON_ERROR_STOP=1 -qAt "$@"; }
