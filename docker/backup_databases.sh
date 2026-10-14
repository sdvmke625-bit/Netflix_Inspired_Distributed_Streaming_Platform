#!/bin/sh
set -eu

stamp="$(date -u +%Y%m%dT%H%M%SZ)-$(cat /proc/sys/kernel/random/uuid)"
mkdir -p /backups
export PGPASSWORD="$MOVIE_DB_PASSWORD"
pg_dump -h postgres_movies -U "$MOVIE_DB_USER" -d "$MOVIE_DB_NAME" -Fc \
  -f "/backups/movies-${stamp}.dump"
export PGPASSWORD="$SESSION_DB_PASSWORD"
pg_dump -h postgres_sessions -U "$SESSION_DB_USER" -d "$SESSION_DB_NAME" -Fc \
  -f "/backups/sessions-${stamp}.dump"
echo "Created movies-${stamp}.dump and sessions-${stamp}.dump in the backups volume."
