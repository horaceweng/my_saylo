#!/usr/bin/env bash
# The public (Mac mini) way to run the app: like start.sh, but it only listens on this machine (127.0.0.1:8000),
# so the only way in from outside is the Tailscale Funnel proxy, which comes from 127.0.0.1 and adds the caller's
# address in X-Forwarded-For. The login cookie stays Secure (https from the Funnel), unlike start.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Under launchd the PATH is minimal: make sure Homebrew (node, ffmpeg, uv) and uv's own installer folder are on it.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "找不到 uv（已找過 ~/.local/bin 與 /opt/homebrew/bin）" >&2
  exit 1
fi

if ! curl -s -m 2 http://localhost:11434/api/tags >/dev/null; then
  echo "⚠️  Ollama 沒有在執行：翻譯與 AI 功能暫時無法使用（另開終端機執行 ollama serve）"
fi

if [ ! -e /opt/homebrew/lib/libespeak-ng.dylib ] && [ ! -e /usr/local/lib/libespeak-ng.dylib ]; then
  echo "⚠️  沒有安裝 espeak-ng：自然語音朗讀暫時無法使用（brew install espeak-ng）"
fi

cd "$ROOT/frontend"
# No terminal under launchd: never wait for input (stdin from /dev/null, no prompts, no progress bars).
export CI=true
[ -d node_modules ] || npm install --no-audit --no-fund </dev/null
if [ ! -f dist/index.html ] || [ -n "$(find src index.html package.json -newer dist/index.html -print -quit)" ]; then
  echo "建置前端…"
  npm run build </dev/null
fi

cd "$ROOT/backend"
# COOKIE_SECURE is deliberately left alone (default: on). A COOKIE_SECURE=false left in the environment or .env would
# send the login cookie over plain http, so refuse to start with it.
if [ "${COOKIE_SECURE:-true}" = "false" ] || grep -qiE '^[[:space:]]*COOKIE_SECURE[[:space:]]*=[[:space:]]*(false|0|no|off)' .env 2>/dev/null; then
  echo "COOKIE_SECURE 被設成 false：對外開放時登入 cookie 必須是 Secure，請移除這個設定" >&2
  exit 1
fi
echo "開啟 http://127.0.0.1:8000（只有本機可連，外部經由 Tailscale Funnel；之後這裡只會顯示警告與錯誤，按 Ctrl+C 結束）"
# Quiet unless something goes wrong: no start-up banner, no line per request; warnings and errors still show.
exec uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1 --log-level warning --no-access-log
