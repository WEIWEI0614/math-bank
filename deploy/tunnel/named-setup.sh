#!/usr/bin/env bash
# Named Tunnel 一条龙：固定域名 + 开机自启。
# 前提（各 2 分钟，人工）：
#   1. Cloudflare 账号：https://dash.cloudflare.com/sign-up（免费计划，无需信用卡）
#   2. 域名：CF 面板 → Registrar → Register Domain → .com 约 $9.77/年（成本价）
#      —— 域名必须注册/托管在 Cloudflare，脚本才能自动配 DNS
#
# 用法: ./named-setup.sh [子域名] [隧道名]
#   ./named-setup.sh                  # 交互式，问子域名
#   ./named-setup.sh math.example.com mathbank
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CF="${CLOUDFLARED:-$(command -v cloudflared 2>/dev/null || echo "$HOME/bin/cloudflared")}"
[ -x "$CF" ] || { echo "缺 cloudflared，先装（见 README）" >&2; exit 1; }

HOSTNAME="${1:-}"
TUNNEL="${2:-mathbank}"
PORT="${PORT:-8770}"

# ---------- 1. 域名 ----------
if [ -z "$HOSTNAME" ]; then
  echo "Named Tunnel 配置"
  echo "----------------"
  echo "域名要已经托管在 Cloudflare（ Registrar 买的自动托管；"
  echo "别处买的要改 NS 到 Cloudflare 分配的 ns.cloudflare.com）。"
  read -rp "输入练习站的完整域名（如 math.example.com）: " HOSTNAME
fi
[ -n "$HOSTNAME" ] || { echo "没域名没法配" >&2; exit 1; }

# ---------- 2. 授权（唯一需要浏览器的一步） ----------
if [ ! -f "$HOME/.cloudflared/cert.pem" ]; then
  echo
  echo "==> 打开浏览器授权 Cloudflare 账号（免费计划即可）"
  echo "    如果浏览器没自动打开，手动复制上面的 URL 访问。"
  "$CF" tunnel login
fi
[ -f "$HOME/.cloudflared/cert.pem" ] || { echo "授权未完成（~/.cloudflared/cert.pem 不存在）" >&2; exit 1; }

# ---------- 3. 建隧道（幂等） ----------
if ! "$CF" tunnel list 2>/dev/null | grep -q "$TUNNEL"; then
  echo "==> 创建隧道: $TUNNEL"
  "$CF" tunnel create "$TUNNEL"
fi
TID="$("$CF" tunnel list --output json 2>/dev/null | /usr/bin/python3 -c "
import sys, json
for t in json.load(sys.stdin):
    if t.get('name') == '$TUNNEL':
        print(t['id']); break
" || true)"
[ -n "$TID" ] || { echo "拿不到隧道 ID，手动跑: cloudflared tunnel list" >&2; exit 1; }
CRED="$HOME/.cloudflared/$TID.json"
[ -f "$CRED" ] || { echo "缺凭据 $CRED" >&2; exit 1; }
echo "    隧道 ID: $TID"

# ---------- 4. 写配置 ----------
mkdir -p "$HOME/.cloudflared"
cat > "$HOME/.cloudflared/config.yml" <<EOF
# 由 deploy/tunnel/named-setup.sh 生成。练习站：$HOSTNAME -> 127.0.0.1:$PORT
tunnel: $TID
credentials-file: $CRED

ingress:
  - hostname: $HOSTNAME
    service: http://127.0.0.1:$PORT
  # 兜底：其他 Host 一律 404，别把服务暴露给随机域名
  - service: http_status:404
EOF
echo "==> 配置已写入 ~/.cloudflared/config.yml"

# ---------- 5. 配 DNS（CNAME 到隧道） ----------
# 域名在 Cloudflare 面板下 → route dns 全自动。
# 免费域名（is-a.dev / afraid.org 等）NS 不在 CF → 自动失败，
# 没关系，拿隧道 ID 去域名面板手动加一条 CNAME 即可，效果一样。
echo "==> 配 DNS: $HOSTNAME -> 隧道"
if "$CF" tunnel route dns "$TUNNEL" "$HOSTNAME" 2>&1; then
  echo "    DNS 已自动配置"
else
  SUB="$(echo "$HOSTNAME" | cut -d. -f1)"
  cat <<MANUAL

    自动配 DNS 失败（域名不在 Cloudflare，免费域名都这样）。手动加一条 CNAME：

      类型: CNAME
      主机: $SUB            （有的面板要求填全名 $HOSTNAME，按面板提示）
      目标: $TID.cfargotunnel.com

    去你的域名 DNS 面板加（is-a.dev 是给 GitHub 仓库提 PR 加 CNAME 文件；
    afraid.org 在 Subdomains 页面加），TTL 默认即可。
MANUAL
  read -rp "加好了按回车继续（没加也能往下走，只是域名暂不通）: "
fi

# ---------- 6. 停掉旧的 Quick Tunnel（如果还在跑） ----------
pkill -f "tunnel --url http://127.0.0.1" 2>/dev/null && echo "==> 已停旧 Quick Tunnel" || true

# ---------- 7. 装 launchd（开机自启 + 崩溃自拉） ----------
PLIST="$HOME/Library/LaunchAgents/com.mathbank.tunnel.plist"
sed -e "s|REPLACE_WITH_PROJECT_PATH|$ROOT|g" \
    -e "s|REPLACE_WITH_TUNNEL_NAME|$TUNNEL|g" \
    "$ROOT/deploy/tunnel/com.mathbank.plist" > "$PLIST"
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "==> launchd 已安装（开机自启 + 挂了自动拉）: $PLIST"

# ---------- 8. 验证 ----------
echo "==> 等隧道就绪并验证..."
for i in $(seq 1 20); do
  R=$(curl -s --max-time 8 "https://$HOSTNAME/api/me" 2>/dev/null || true)
  [ -n "$R" ] && break
  sleep 2
done

cat <<DONE

  ╔════════════════════════════════════════════════════════════╗
  ║  固定地址（以后重启不变，开机自启）：                      ║
  ║                                                            ║
  ║    https://$HOSTNAME
  ║                                                            ║
  ╚════════════════════════════════════════════════════════════╝

验证响应: ${R:-（还没通，等 1 分钟或看日志）}
日志:     $ROOT/deploy/tunnel/tunnel.log
停服:     launchctl unload $PLIST
DONE
