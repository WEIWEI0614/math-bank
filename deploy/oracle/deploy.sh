#!/usr/bin/env bash
# 从开发机一键部署到 Oracle VM。用法：
#   ./deploy.sh ubuntu@<公网IP>
#
# 做三件事：
#   1. sqlite3 .backup 在线一致性备份题库（直接 cp WAL 模式的库可能丢数据）
#   2. rsync site/ + 题库到 VM（排除开发机的临时脚本和几十 GB 备份文件）
#   3. 重启服务 + 健康检查
set -euo pipefail

TARGET="${1:?用法: ./deploy.sh ubuntu@公网IP}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "==> 1/3 SQLite 在线备份（WAL 一致性）"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
sqlite3 "$ROOT/bank.sqlite" ".backup '$TMP/bank.sqlite'"
ls -lh "$TMP/bank.sqlite"

echo "==> 2/3 上传 site/ 与题库到 $TARGET:/opt/mathbank/"
# 排除清单：开发机上 _*.py/_*.json 是导题管线脚本、bank.sqlite.bak-* 是 30GB 级
# 历史备份、publish/ 是 Render 时代的发布包，全都不上生产
rsync -avz --progress \
  --exclude 'bank.sqlite*' \
  --exclude '_*' \
  --exclude '*.bak*' \
  --exclude '__pycache__' \
  --exclude '.DS_Store' \
  --exclude 'output/' --exclude 'publish/' --exclude 'publish_img_v1/' \
  --exclude 'adapted/' --exclude 'shots/' --exclude 'selfcheck/' --exclude 'tmp/' \
  --exclude '.git/' --exclude '*.log' --exclude '*.csv' --exclude '*.png' \
  --exclude 'index.html.bak*' --exclude 'serve.py.bak*' \
  "$ROOT/site/" "$TARGET:/opt/mathbank/site/"
rsync -avz --progress "$TMP/bank.sqlite" "$TARGET:/opt/mathbank/bank.sqlite"

echo "==> 3/3 重启服务并健康检查"
ssh "$TARGET" 'sudo systemctl restart mathbank && sleep 2 && sudo systemctl is-active mathbank'
ssh "$TARGET" 'curl -fsS http://127.0.0.1:8770/api/me && echo " <- 本地健康检查通过"'

echo
echo "部署完成。验收："
echo "  curl -fsS https://你的域名/api/me   # 应返回 {\"role\":null}"
echo "  sudo journalctl -u mathbank -f      # 看日志"
