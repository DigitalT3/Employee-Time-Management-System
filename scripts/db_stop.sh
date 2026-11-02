#!/usr/bin/env bash
# Stop the repository-local cluster if running.
source "$(dirname "$0")/_common.sh"
if [ -f "$PGDATA/PG_VERSION" ] && pg_ready; then
  "$PG_BIN/pg_ctl" -D "$PGDATA" -w -m fast stop >/dev/null && echo "Cluster stopped"
else
  echo "Cluster not running"
fi
