#!/bin/bash
set -e

echo "=== Warhammer Fantasy Professions Manager ==="
echo "Waiting for MySQL to be ready..."

until python -c "
import sys
import pymysql, os
try:
    url = os.environ.get('DATABASE_URL', '')
    # Parse user/pass/host/db from URL
    import re
    m = re.match(r'mysql\+pymysql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)', url)
    if m:
        conn = pymysql.connect(host=m.group(3), user=m.group(1), password=m.group(2), database=m.group(5), port=int(m.group(4)))
        conn.close()
        sys.exit(0)
except Exception as e:
    sys.exit(1)
"; do
    echo "Database not ready yet, retrying in 2s..."
    sleep 2
done

echo "Database is ready!"

echo "Running database migrations..."
flask db upgrade

echo "Creating default admin user if needed..."
flask create-admin

echo "Starting application..."
exec gunicorn --bind 0.0.0.0:5000 --workers 2 --timeout 120 --access-logfile - --error-logfile - run:app
