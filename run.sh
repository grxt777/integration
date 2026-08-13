#!/bin/bash
# Bank Intelligence Platform — Startup Script

echo "🚀 Starting Bank Intelligence Platform..."

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

echo "📦 Installing dependencies..."
python3 -m pip install -r requirements.txt

export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$(pwd)/api"

echo "🌐 Starting FastAPI server on http://localhost:8000"
echo "   Главная:        http://localhost:8000/dashboard/index.html"
echo "   Карта ATM:      http://localhost:8000/dashboard/map.html"
echo "   Кассиры:        http://localhost:8000/dashboard/cashiers.html"
echo "   Swagger:        http://localhost:8000/docs"
echo "================================================"

python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
