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
echo "開啟 http://localhost:8000"
exec uv run fastapi run app/main.py --port 8000
