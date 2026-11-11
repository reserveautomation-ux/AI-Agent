#!/usr/bin/env bash
# Start (or stop) a throwaway local Postgres for running the test suite without
# Supabase or Docker. Prints the DATABASE_URL to export as TEST_DATABASE_URL.
#
#   scripts/test-db.sh start   # init + start on port 54329
#   scripts/test-db.sh stop
#
# Tests create their own fresh database per run and apply supabase/tests/supabase_stub.sql
# followed by supabase/migrations/*.sql, so this only needs a running server.
set -euo pipefail

PGBIN="${PGBIN:-$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1)}"
DATA_DIR="${TEST_PGDATA:-${TMPDIR:-/tmp}/workforce-test-pg}"
PORT="${TEST_PGPORT:-54329}"
RUN_AS=()
if [ "$(id -u)" = "0" ]; then
  RUN_AS=(runuser -u postgres --)
fi

case "${1:-start}" in
  start)
    if [ ! -d "$DATA_DIR" ]; then
      mkdir -p "$DATA_DIR"
      [ "$(id -u)" = "0" ] && chown postgres "$DATA_DIR"
      "${RUN_AS[@]}" "$PGBIN/initdb" -D "$DATA_DIR" -U postgres --auth=trust -E UTF8 --locale=C >/dev/null
    fi
    "${RUN_AS[@]}" "$PGBIN/pg_ctl" -D "$DATA_DIR" -o "-p $PORT -k /tmp" -l "$DATA_DIR/log" -w start >/dev/null
    echo "postgresql://postgres@localhost:$PORT/postgres"
    ;;
  stop)
    "${RUN_AS[@]}" "$PGBIN/pg_ctl" -D "$DATA_DIR" -w stop >/dev/null
    ;;
  *)
    echo "usage: $0 start|stop" >&2
    exit 1
    ;;
esac
