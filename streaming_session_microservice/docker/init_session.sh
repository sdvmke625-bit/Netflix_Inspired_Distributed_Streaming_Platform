#!/bin/sh
set -eu

python - <<'PY'
import os
import time

import psycopg

connection_settings = {
    "host": os.environ["DB_HOST"],
    "port": os.environ["DB_PORT"],
    "dbname": os.environ["DB_NAME"],
    "user": os.environ["DB_USER"],
    "password": os.environ["DB_PASSWORD"],
    "connect_timeout": 2,
}

for attempt in range(60):
    try:
        with psycopg.connect(**connection_settings):
            print("Streaming Session database is ready.")
        break
    except psycopg.OperationalError:
        if attempt == 59:
            raise
        time.sleep(1)
PY

python manage.py migrate --noinput
exec daphne -b 0.0.0.0 -p 8001 config.asgi:application
