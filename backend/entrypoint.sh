#!/bin/sh
set -e

echo "Running database migrations..."
alembic upgrade head

if [ "${AUTO_SEED}" = "true" ] || [ "${RUN_SEED}" = "true" ] || [ "${AUTO_SEED}" = "1" ]; then
    echo "AUTO_SEED is enabled. Seeding demo data..."
    python seed_demo.py
fi

echo "Starting backend server..."
exec "$@"
