#!/usr/bin/env bash
# Oracle ARM VM 一次性初始化。在 VM 上以 sudo 执行：sudo bash setup.sh
set -euo pipefail

echo "==> 1/4 安装 Caddy / sqlite3 / 持久化防火墙工具"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  caddy sqlite3 iptables-persistent netfilter-persistent

echo "==> 2/4 放行本机防火墙 80/443"
# Oracle Ubuntu 镜像默认 iptables INPUT 末尾是 REJECT，-I 插到链首确保在 REJECT 之前生效
for PORT in 80 443; do
  if ! iptables -C INPUT -p tcp --dport "$PORT" -j ACCEPT 2>/dev/null; then
    iptables -I INPUT -p tcp --dport "$PORT" -j ACCEPT
  fi
done
netfilter-persistent save
echo "    已放行: $(iptables -L INPUT -n --line-numbers | grep -E 'dpt:(80|443)' | wc -l) 条规则"

echo "==> 3/4 创建运行目录"
mkdir -p /opt/mathbank/backups
chown -R "${SUDO_USER:-ubuntu}:${SUDO_USER:-ubuntu}" /opt/mathbank

echo "==> 4/4 安装 systemd unit"
cp mathbank.service /etc/systemd/system/mathbank.service
systemctl daemon-reload
systemctl enable mathbank

cat <<'DONE'

初始化完成。接下来：
  1. sudo tee /etc/mathbank.env  写入 TEACHER_KEY / STUDENT_CODE（chmod 600）
  2. 编辑 /etc/caddy/Caddyfile 把 math.example.com 换成真实域名，systemctl reload caddy
  3. 回到开发机跑 deploy/oracle/deploy.sh 上传代码和题库
  4. sudo systemctl start mathbank && sudo systemctl status mathbank

DONE
