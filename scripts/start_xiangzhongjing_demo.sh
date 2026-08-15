#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME_DIR="$HOME/Library/Caches/xiangzhongjing-demo"
LABEL="com.xiangzhongjing.demo"
PYTHON_BIN="/Library/Developer/CommandLineTools/usr/bin/python3"
STDOUT_LOG="/tmp/xiangzhongjing-8860.log"
STDERR_LOG="/tmp/xiangzhongjing-8860.err"
URL="http://127.0.0.1:8860/xiangzhongjing-demo"

mkdir -p "$RUNTIME_DIR"
rsync -a --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '.mcp-venv' \
  --exclude '.pytest_cache' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '*.log' \
  --exclude 'dist' \
  --exclude 'artifacts' \
  --exclude 'backups' \
  --exclude 'demo_screenshots' \
  --exclude 'prd_screenshots' \
  "$ROOT_DIR/" "$RUNTIME_DIR/"

launchctl remove "$LABEL" >/dev/null 2>&1 || true
for pid in ${(f)"$(lsof -tiTCP:8860 -sTCP:LISTEN 2>/dev/null || true)"}; do
  [[ -n "$pid" ]] && kill "$pid" >/dev/null 2>&1 || true
done
for _ in {1..40}; do
  if ! launchctl list "$LABEL" >/dev/null 2>&1 \
    && ! lsof -nP -iTCP:8860 -sTCP:LISTEN >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
: > "$STDOUT_LOG"
: > "$STDERR_LOG"
launchctl submit \
  -l "$LABEL" \
  -p "$PYTHON_BIN" \
  -o "$STDOUT_LOG" \
  -e "$STDERR_LOG" \
  -- "$PYTHON_BIN" "$RUNTIME_DIR/main.py"
launchctl start "$LABEL"

for _ in {1..20}; do
  if launchctl list "$LABEL" 2>/dev/null | grep -q '"PID"' \
    && curl -fsS "$URL" >/dev/null; then
    print "$URL"
    exit 0
  fi
  sleep 0.25
done

print -u2 "Xiangzhongjing demo failed to start. See $STDERR_LOG"
exit 1
