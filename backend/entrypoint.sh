#!/bin/sh
set -e

echo "Running database migrations..."
alembic upgrade head

if [ "${AUTO_SEED}" = "true" ] || [ "${RUN_SEED}" = "true" ] || [ "${AUTO_SEED}" = "1" ]; then
    echo "AUTO_SEED is enabled. Seeding demo data..."
    python seed_demo.py || echo "Warning: Seed script exited with non-zero status, continuing startup."
fi

echo "Starting backend server..."
exec "$@"
