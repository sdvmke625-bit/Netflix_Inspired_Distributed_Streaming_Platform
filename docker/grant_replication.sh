#!/bin/sh
set -eu

# SQL values are quoted by psql/format, so environment values cannot inject SQL.
psql -v ON_ERROR_STOP=1 -h "$PRIMARY_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -v replication_user="$REPLICATION_USER" \
  -v replication_password="$REPLICATION_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I WITH LOGIN REPLICATION PASSWORD %L',
    :'replication_user', :'replication_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'replication_user')
\gexec
SELECT format('ALTER ROLE %I WITH LOGIN REPLICATION PASSWORD %L',
    :'replication_user', :'replication_password')
\gexec
SQL
