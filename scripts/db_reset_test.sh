#!/usr/bin/env bash
# Drop and recreate etms_test (disposable test database).
source "$(dirname "$0")/_common.sh"
pg_ready || bash "$(dirname "$0")/db_start.sh"
"$PG_BIN/dropdb" --if-exists -f -h "$PGSOCK" -p "$PGPORT" -U "$PGUSER_LOCAL" etms_test
"$PG_BIN/createdb" -h "$PGSOCK" -p "$PGPORT" -U "$PGUSER_LOCAL" etms_test
echo "etms_test recreated"
