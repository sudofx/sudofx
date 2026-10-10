#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="$ROOT/.data/conversation.sqlite"
PID_FILE="/tmp/sudofx-conversation.pid"
LOG_FILE="/tmp/sudofx-conversation.log"
PORT=8765
RESET=false

usage() {
  cat <<'EOF'
Usage: scripts/conversation.sh [--reset]

Without --reset:
  stop any running Conversation server and start a new server.

With --reset:
  stop the server, delete Conversation SQLite state, and start fresh.

Git pull/push is an explicit VS Code Git operation. Starting the app never
changes branches or waits for GitHub, so it also works while offline.
EOF
}

case "${1:-}" in
  "")
    ;;
  --reset|—reset)
    RESET=true
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    echo "Unknown option: $1" >&2
    usage >&2
    exit 2
    ;;
esac

if [[ $# -gt 1 ]]; then
  echo "Only one optional argument is supported." >&2
  usage >&2
  exit 2
fi

cd "$ROOT"

# Load shell-compatible quoting from the repository's local environment file.
# Docker's env-file parser passes quoted API keys literally, causing provider
# authentication failures even though the key appears to be configured.
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ROOT/.env"
  set +a
fi

echo "Stopping any running Conversation server..."
if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    for _ in {1..20}; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.1
    done
  fi
  rm -f "$PID_FILE"
fi
pkill -f 'python .*applications\.conversation\.server' 2>/dev/null || true

if [[ "$RESET" == true ]]; then
  echo "Resetting Conversation SQLite authority..."
  rm -f "$DB" "$DB-wal" "$DB-shm"
fi

mkdir -p "$ROOT/.data"

if [[ -z "${GEMINI_API_KEY:-}" ]]; then
  echo "WARNING: GEMINI_API_KEY is not set; the server will start, but provider turns will fail." >&2
fi

export GEMINI_MODEL="${GEMINI_MODEL:-gemini-3.5-flash-lite}"

echo "Starting Conversation server on port $PORT..."
nohup env PYTHONPATH=src:. \
  GEMINI_MODEL="$GEMINI_MODEL" \
  python -m applications.conversation.server \
  --host 0.0.0.0 \
  --port "$PORT" \
  > "$LOG_FILE" 2>&1 &

pid=$!
echo "$pid" > "$PID_FILE"

sleep 0.3
if ! kill -0 "$pid" 2>/dev/null; then
  echo "Conversation server failed to start. Log:" >&2
  cat "$LOG_FILE" >&2 || true
  exit 1
fi

echo
echo "Conversation server started."
echo "PID: $pid"
echo "Port: $PORT"
echo "SQLite: $DB"
echo "Log: $LOG_FILE"
if [[ -n "${CODESPACE_NAME:-}" && -n "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-}" ]]; then
  echo "Open Conversation: https://${CODESPACE_NAME}-${PORT}.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}/conversation"
else
  echo "Open Conversation: http://localhost:$PORT/conversation"
fi
