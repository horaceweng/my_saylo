#!/usr/bin/env bash
# One command to run the whole app: builds the frontend when needed, then serves everything on http://localhost:8000
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if ! curl -s -m 2 http://localhost:11434/api/tags >/dev/null; then
  echo "⚠️  Ollama 沒有在執行：翻譯與 AI 功能暫時無法使用（另開終端機執行 ollama serve）"
fi

if [ ! -e /opt/homebrew/lib/libespeak-ng.dylib ] && [ ! -e /usr/local/lib/libespeak-ng.dylib ]; then
  echo "⚠️  沒有安裝 espeak-ng：自然語音朗讀暫時無法使用（brew install espeak-ng）"
fi

cd "$ROOT/frontend"
[ -d node_modules ] || npm install
if [ ! -f dist/index.html ] || [ -n "$(find src index.html package.json -newer dist/index.html -print -quit)" ]; then
  echo "建置前端…"
  npm run build
fi

cd "$ROOT/backend"
# This is plain http on localhost, where a Secure login cookie would never be sent back.
export COOKIE_SECURE="${COOKIE_SECURE:-false}"
echo "開啟 http://localhost:8000（之後這裡只會顯示警告與錯誤，按 Ctrl+C 結束）"
# Quiet unless something goes wrong: no start-up banner, no line per request; warnings and errors still show.
exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level warning --no-access-log
