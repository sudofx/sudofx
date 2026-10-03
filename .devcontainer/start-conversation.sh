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
if [[ -n "${CODESPACE_NAME:-}" && -n "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-}" ]]; then
  echo "Open Conversation: https://${CODESPACE_NAME}-8765.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}/conversation"
else
  echo "Open Conversation: http://localhost:8765/conversation"
fi
if [[ -z "${GEMINI_API_KEY:-}" ]]; then
  echo "Gemini key: MISSING"
  echo "WARNING: Add GEMINI_API_KEY as a GitHub Codespaces secret, then restart this Codespace."
else
  echo "Gemini key: SET"
fi
