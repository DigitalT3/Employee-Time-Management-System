#!/usr/bin/env bash
# Start (initialising once) the local PostgreSQL 16 cluster and ensure
# etms_dev and etms_test exist. Never touches the system PostgreSQL service.
source "$(dirname "$0")/_common.sh"
mkdir -p "$PGSOCK"
if [ ! -f "$PGDATA/PG_VERSION" ]; then
  echo "Initialising cluster in $PGDATA"
  # trust auth is for local development only; listener bound to 127.0.0.1/socket.
  "$PG_BIN/initdb" -D "$PGDATA" -U "$PGUSER_LOCAL" -A trust -E UTF8 --locale=C.UTF-8 >/dev/null
fi
# PostgreSQL refuses to start unless PGDATA is 0700/0750.
chmod 700 "$PGDATA"
if pg_ready; then
  echo "Cluster already running on port $PGPORT"
else
  "$PG_BIN/pg_ctl" -D "$PGDATA" -l "$PGLOG" -w \
    -o "-p $PGPORT -k $PGSOCK -c listen_addresses=127.0.0.1" start >/dev/null
  echo "Cluster started on port $PGPORT"
fi
for db in etms_dev etms_test; do
  if [ "$(psql_local -c "SELECT 1 FROM pg_database WHERE datname='$db'")" != "1" ]; then
    "$PG_BIN/createdb" -h "$PGSOCK" -p "$PGPORT" -U "$PGUSER_LOCAL" "$db"
    echo "Created database $db"
  fi
done
pg_ready && echo "pg_isready OK ($PGSOCK:$PGPORT)"
