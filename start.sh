#!/usr/bin/env bash
# Start the backend (FastAPI :8000) and frontend (Vite :5173) in one terminal.
# Ctrl+C stops both.
#
#   ./start.sh            # start both
#   ./start.sh --setup    # also (re)install backend + frontend dependencies first
#   BACKEND_PORT=8100 FRONTEND_PORT=5200 ./start.sh   # use other ports

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

BLUE=$'\033[34m'; GREEN=$'\033[32m'; RED=$'\033[31m'; BOLD=$'\033[1m'; RESET=$'\033[0m'
die() { echo "${RED}error:${RESET} $*" >&2; exit 1; }

# ---- preflight -------------------------------------------------------------
command -v node >/dev/null || die "node is not installed"
command -v npm  >/dev/null || die "npm is not installed"

FORCE_SETUP=0
[[ "${1:-}" == "--setup" ]] && FORCE_SETUP=1

if [[ ! -x "$ROOT/backend/venv/bin/uvicorn" || $FORCE_SETUP == 1 ]]; then
  echo "${BOLD}Setting up backend venv...${RESET}"
  PY="$(command -v python3.14 || command -v python3)" || die "python3 not found"
  [[ -d "$ROOT/backend/venv" ]] || "$PY" -m venv "$ROOT/backend/venv" || die "venv creation failed"
  "$ROOT/backend/venv/bin/pip" install -q -r "$ROOT/backend/requirements.txt" || die "pip install failed"
fi

if [[ ! -d "$ROOT/frontend/node_modules" || $FORCE_SETUP == 1 ]]; then
  echo "${BOLD}Installing frontend dependencies...${RESET}"
  (cd "$ROOT/frontend" && npm install) || die "npm install failed"
fi

[[ -f "$ROOT/backend/.env"  ]] || die "backend/.env missing (copy backend/.env.example and fill it in)"
[[ -f "$ROOT/frontend/.env" ]] || die "frontend/.env missing (copy frontend/.env.example and fill it in)"

for port in $BACKEND_PORT $FRONTEND_PORT; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    die "port $port is already in use (is the app already running? try: lsof -nP -iTCP:$port -sTCP:LISTEN)"
  fi
done

# ---- run -------------------------------------------------------------------
PIDS=()

# Kill a process and all of its descendants (uvicorn --reload and npm spawn children).
kill_tree() {
  local pid=$1 child
  for child in $(pgrep -P "$pid" 2>/dev/null); do kill_tree "$child"; done
  kill "$pid" 2>/dev/null
}

cleanup() {
  trap '' INT TERM EXIT
  echo; echo "${BOLD}Stopping services...${RESET}"
  for pid in "${PIDS[@]}"; do kill_tree "$pid"; done
  wait 2>/dev/null
  exit 0
}
trap cleanup INT TERM EXIT

# Prefix every output line with a coloured service label.
prefix() { local label=$1 color=$2; while IFS= read -r line; do printf '%s[%s]%s %s\n' "$color" "$label" "$RESET" "$line"; done; }

# Process substitution keeps $! pointing at the service itself, not the prefix filter.
(cd "$ROOT/backend" && exec venv/bin/uvicorn app.main:app --reload --port "$BACKEND_PORT") \
  > >(prefix backend "$BLUE") 2>&1 &
PIDS+=($!)

(cd "$ROOT/frontend" && exec npm run dev -- --port "$FRONTEND_PORT") > >(prefix frontend "$GREEN") 2>&1 &
PIDS+=($!)

echo "${BOLD}Backend:${RESET}  http://localhost:$BACKEND_PORT  (docs: /docs)"
echo "${BOLD}Frontend:${RESET} http://localhost:$FRONTEND_PORT"
echo "Press Ctrl+C to stop both."

# Exit (and clean up) as soon as either service dies.
while true; do
  for pid in "${PIDS[@]}"; do
    kill -0 "$pid" 2>/dev/null || { echo "${RED}A service exited; shutting down.${RESET}"; exit 1; }
  done
  sleep 1
done
