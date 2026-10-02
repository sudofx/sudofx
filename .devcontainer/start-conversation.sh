#!/usr/bin/env bash
set -euo pipefail

cd /workspaces/sudofx

if [[ -f /tmp/sudofx-conversation.pid ]] && kill -0 "$(cat /tmp/sudofx-conversation.pid)" 2>/dev/null; then
  exit 0
fi

mkdir -p .data
export GEMINI_MODEL="${GEMINI_MODEL:-gemini-3.5-flash-lite}"
nohup env PYTHONPATH=src:. GEMINI_MODEL="$GEMINI_MODEL" python -m applications.conversation.server \
  --host 0.0.0.0 \
  --port 8765 \
  > /tmp/sudofx-conversation.log 2>&1 &

echo $! > /tmp/sudofx-conversation.pid
echo "sudofx Conversation is starting on private forwarded port 8765."
echo "SQLite authority: /workspaces/sudofx/.data/conversation.sqlite"
echo "Gemini model: $GEMINI_MODEL"
if [[ -z "${GEMINI_API_KEY:-}" ]]; then
  echo "WARNING: GEMINI_API_KEY is not set. Add it as a GitHub Codespaces secret before sending a message."
fi
