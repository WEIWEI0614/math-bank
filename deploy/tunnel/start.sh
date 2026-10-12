#!/usr/bin/env bash
# Cloudflare Tunnel 快速启动：serve.py（云模式，仅本机绑定）+ cloudflared 隧道
# 用法: ./start.sh            # Quick Tunnel，域名每次重启会变，适合测试
#       ./start.sh <Tunnel名>  # 具名隧道（固定域名），需先完成 README 第 4-5 步
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PORT="${PORT:-8770}"
TEACHER_KEY="${TEACHER_KEY:-$(cat "$ROOT/.teacher_key" 2>/dev/null || echo shuxue2026)}"
STUDENT_CODE="${STUDENT_CODE:-$(cat "$ROOT/.student_code" 2>/dev/null || echo banji2026)}"

cleanup() { [ -n "${SRV_PID:-}" ] && kill "$SRV_PID" 2>/dev/null || true; }
trap cleanup EXIT

# 云模式（PORT 存在触发）：Host/Origin 校验放宽为同源、限流 600/min；
# BIND_HOST=127.0.0.1：应用只监听本机，对外只暴露 cloudflared
PORT="$PORT" BIND_HOST=127.0.0.1 \
  TEACHER_KEY="$TEACHER_KEY" STUDENT_CODE="$STUDENT_CODE" \
  python3 site/serve.py --port "$PORT" &
SRV_PID=$!
sleep 1.5

if ! curl -fsS "http://127.0.0.1:$PORT/api/me" >/dev/null; then
  echo "serve.py 没起来，看上面的输出" >&2
  exit 1
fi
echo "本地服务就绪: http://127.0.0.1:$PORT"

if [ $# -ge 1 ]; then
  echo "具名隧道: $1"
  exec cloudflared tunnel run "$1"
else
  echo "Quick Tunnel（临时域名）:"
  exec cloudflared tunnel --url "http://127.0.0.1:$PORT"
fi
