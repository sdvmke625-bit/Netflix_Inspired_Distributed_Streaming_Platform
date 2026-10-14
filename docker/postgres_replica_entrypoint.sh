#!/bin/sh
set -eu

: "${PRIMARY_HOST:?PRIMARY_HOST is required}"
: "${REPLICATION_USER:?REPLICATION_USER is required}"
: "${REPLICATION_PASSWORD:?REPLICATION_PASSWORD is required}"

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  export PGPASSWORD="$REPLICATION_PASSWORD"
  until pg_isready -h "$PRIMARY_HOST" -p 5432 -U "$REPLICATION_USER" >/dev/null 2>&1; do
    sleep 2
  done
  pg_basebackup -h "$PRIMARY_HOST" -p 5432 -U "$REPLICATION_USER" \
    -D "$PGDATA" -Fp -Xs -P -R
  chmod 700 "$PGDATA"
fi

exec docker-entrypoint.sh postgres
