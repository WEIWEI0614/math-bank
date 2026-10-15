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

cleanup() {
  [ -n "${SRV_PID:-}" ] && kill "$SRV_PID" 2>/dev/null
  [ -n "${CF_PID:-}" ] && kill "$CF_PID" 2>/dev/null
  return 0
}
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

# cloudflared 定位：系统 PATH 优先，其次 ~/bin（brew 装不了时的手动安装位）
CF="${CLOUDFLARED:-$(command -v cloudflared 2>/dev/null || echo "$HOME/bin/cloudflared")}"
if [ ! -x "$CF" ]; then
  echo "缺 cloudflared。安装（brew 在部分沙箱被拦，用二进制方式）：" >&2
  echo "  curl -fsSL -o /tmp/cf.tgz https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64.tgz" >&2
  echo "  tar -xzf /tmp/cf.tgz && mkdir -p ~/bin && mv cloudflared ~/bin/" >&2
  exit 1
fi

if [ $# -ge 1 ]; then
  echo "具名隧道: $1"
  exec "$CF" tunnel run "$1"
else
  # Quick Tunnel：cloudflared 后台跑、输出进日志文件，前台等 URL 出现后
  # 用方框醒目的打出来 —— 2026.10.0 实测 URL 行极易被它自己的连接日志刷掉，
  # 之前有用户因此以为隧道没建成（其实服务好着呢）。
  LOG="$ROOT/deploy/tunnel/tunnel.log"
  echo "Quick Tunnel 启动中（临时域名，重启会变；固定域名见 README）..."
  "$CF" tunnel --url "http://127.0.0.1:$PORT" --no-autoupdate >"$LOG" 2>&1 &
  CF_PID=$!
  URL=""
  for _ in $(seq 1 25); do
    URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$LOG" 2>/dev/null | head -1)
    [ -n "$URL" ] && break
    kill -0 "$CF_PID" 2>/dev/null || break
    sleep 1
  done
  echo
  if [ -n "$URL" ]; then
    echo "  ╔════════════════════════════════════════════════════════════╗"
    echo "  ║  发给学生的网址：                                          ║"
    echo "  ║                                                            ║"
    echo "  ║    $URL"
    echo "  ║                                                            ║"
    echo "  ╚════════════════════════════════════════════════════════════╝"
    echo "  （重启后地址会变；Ctrl+C 停止服务与隧道；日志: $LOG）"
  else
    echo "隧道 25 秒内没建立。诊断："
    echo "  tail -20 $LOG"
    echo "  curl -s http://127.0.0.1:20241/metrics | grep trycloudflare   # 已在跑的实例"
  fi
  # 前台驻留，等服务/隧道退出
  wait
fi
