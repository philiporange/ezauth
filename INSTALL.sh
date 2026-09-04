#!/usr/bin/env bash
set -euo pipefail

echo "=== ezAuth installation ==="
echo ""

# --- Check prerequisites ---

check_cmd() {
    if ! command -v "$1" &>/dev/null; then
        echo "Error: $1 is not installed."
        exit 1
    fi
}

check_cmd python3
check_cmd pip
check_cmd docker

if docker compose version &>/dev/null; then
    COMPOSE=(docker compose)
elif command -v docker-compose &>/dev/null; then
    COMPOSE=(docker-compose)
else
    echo "Error: neither 'docker compose' nor 'docker-compose' is available."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
REQUIRED="3.11"
if [ "$(printf '%s\n' "$REQUIRED" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED" ]; then
    echo "Error: Python >= $REQUIRED is required (found $PYTHON_VERSION)"
    exit 1
fi

echo "[1/5] Prerequisites OK (Python $PYTHON_VERSION)"

# --- Set up environment ---
# .env comes first: docker compose reads the Postgres credentials from it.

if [ ! -f .env ]; then
    echo "[2/5] Creating .env from .env.example..."
    cp .env.example .env
else
    echo "[2/5] .env already exists, skipping"
fi

# --- Start services ---

for var in POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB; do
    if ! grep -q "^${var}=" .env; then
        echo "Error: ${var} is missing from .env. Copy the value from .env.example."
        exit 1
    fi
done

echo "[3/5] Starting PostgreSQL and Redis..."
"${COMPOSE[@]}" up -d postgres redis

echo "       Waiting for PostgreSQL..."
for _ in $(seq 1 60); do
    if "${COMPOSE[@]}" exec -T postgres pg_isready -q; then
        break
    fi
    sleep 1
done

# --- Install Python dependencies ---

echo "[4/5] Installing Python dependencies..."
pip install -e ".[dev]" -q

# --- Run database migrations ---

echo "[5/5] Running database migrations..."
alembic upgrade head

echo ""
echo "=== Installation complete ==="
echo ""
echo "Start the server with:"
echo "  uvicorn ezauth.main:create_app --factory --reload"
echo ""
echo "Or run the whole stack, migrations included, in Docker:"
echo "  ${COMPOSE[*]} up -d --build"
echo ""
echo "Dashboard:    http://localhost:8000/dashboard"
echo "API:          http://localhost:8000/v1/"
echo "Hosted auth:  http://localhost:8000/auth/login"
echo ""
