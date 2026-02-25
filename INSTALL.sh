#!/usr/bin/env bash
set -euo pipefail

echo "=== EZAuth Installation ==="
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
check_cmd docker-compose || check_cmd "docker compose"

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
REQUIRED="3.11"
if [ "$(printf '%s\n' "$REQUIRED" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED" ]; then
    echo "Error: Python >= $REQUIRED is required (found $PYTHON_VERSION)"
    exit 1
fi

echo "[1/5] Prerequisites OK (Python $PYTHON_VERSION)"

# --- Start services ---

echo "[2/5] Starting PostgreSQL and Redis..."
if command -v docker-compose &>/dev/null; then
    docker-compose up -d
else
    docker compose up -d
fi

# Wait for Postgres to be ready
echo "       Waiting for PostgreSQL..."
for i in $(seq 1 30); do
    if docker-compose exec -T postgres pg_isready -U ezauth &>/dev/null 2>&1 || \
       docker compose exec -T postgres pg_isready -U ezauth &>/dev/null 2>&1; then
        break
    fi
    sleep 1
done

# --- Install Python dependencies ---

echo "[3/5] Installing Python dependencies..."
pip install -e ".[dev]" -q

# --- Set up environment ---

if [ ! -f .env ]; then
    echo "[4/5] Creating .env from .env.example..."
    cp .env.example .env
    # Generate a random dashboard secret key
    DASHBOARD_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s/change-me-in-production/$DASHBOARD_KEY/" .env
    else
        sed -i "s/change-me-in-production/$DASHBOARD_KEY/" .env
    fi
else
    echo "[4/5] .env already exists, skipping"
fi

# --- Run database migrations ---

echo "[5/5] Running database migrations..."
alembic upgrade head

echo ""
echo "=== Installation complete ==="
echo ""
echo "Start the server with:"
echo "  uvicorn ezauth.main:create_app --factory --reload"
echo ""
echo "Dashboard:    http://localhost:8000/dashboard"
echo "API:          http://localhost:8000/v1/"
echo "Hosted auth:  http://localhost:8000/auth/login"
echo ""
