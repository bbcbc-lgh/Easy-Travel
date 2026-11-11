#!/usr/bin/env bash
# 一键启动开发环境（macOS / Linux）
# 用法：bash scripts/dev.sh

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backend="$root/backend"
frontend="$root/frontend"
python="$backend/.venv/bin/python"

if [ ! -x "$python" ]; then
  echo "[setup] creating virtualenv ..."
  python3 -m venv "$backend/.venv"
fi

echo "[setup] installing backend dependencies ..."
"$python" -m pip install -q -r "$backend/requirements.txt"

if [ ! -f "$backend/.env" ]; then
  cp "$backend/.env.example" "$backend/.env"
  echo "[setup] created backend/.env — fill in LLM_API_KEY / AMAP_WEB_KEY, then restart."
fi

if [ ! -d "$frontend/node_modules" ]; then
  echo "[setup] installing frontend dependencies ..."
  (cd "$frontend" && npm install)
fi

echo "[run] backend  http://127.0.0.1:8000  (docs: /docs)"
(cd "$backend" && "$python" -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000 --reload) &
backend_pid=$!

cleanup() {
  kill "$backend_pid" 2>/dev/null || true
  echo "[stop] services stopped."
}
trap cleanup EXIT INT TERM

echo "[run] frontend http://127.0.0.1:5173"
cd "$frontend"
npm run dev
