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
            print("Movie Catalog database is ready.")
        break
    except psycopg.OperationalError:
        if attempt == 59:
            raise
        time.sleep(1)
PY

python manage.py migrate --noinput
python - <<'PY'
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.core.management import call_command
from movies.models import Movie

if not Movie.objects.exists():
    print("Loading initial movie fixtures...")
    call_command("loaddata", "movies/fixtures/initial_movies.json")
    print(f"Loaded {Movie.objects.count()} movies successfully.")
else:
    print(f"Movie Catalog already populated with {Movie.objects.count()} movies.")
PY
