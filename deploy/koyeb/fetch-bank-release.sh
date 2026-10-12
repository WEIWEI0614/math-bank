#!/usr/bin/env bash
# 把本地题库上传为 GitHub Release（tag: bank-latest），供 Koyeb 容器启动时下载。
# 题库更新流程：本地改库 → 跑这个脚本 → Koyeb 重新部署（自动拉新版）。
#
# 前提：已安装 gh（brew install gh）并 gh auth login。
# 注意：银行级口径——上传的是含 12064 道真题的库，仓库是 public，
# release asset 同样是公开可下载。若不愿公开题库，改用 R2/OSS 私有桶 +
# entrypoint 里带 token 下载。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TAG="bank-latest"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "==> SQLite 在线备份（WAL 一致性，别直接 cp）"
sqlite3 "$ROOT/bank.sqlite" ".backup '$TMP/bank.sqlite'"

echo "==> 压缩（sqlite 压缩率约 3-4 倍，56MB → ~15MB，上传快）"
gzip -6 -c "$TMP/bank.sqlite" > "$TMP/bank.sqlite.gz"
ls -lh "$TMP/bank.sqlite.gz"

echo "==> 创建/更新 release: $TAG"
# --clobber 覆盖同名 asset；tag 固定为 bank-latest 意味着容器永远拉最新版
gh release create "$TAG" "$TMP/bank.sqlite.gz" \
  --title "题库快照 $(date +%Y-%m-%d)" \
  --notes "Koyeb 部署用题库快照。生成时间：$(date '+%Y-%m-%d %H:%M')" \
  --clobber 2>/dev/null || \
gh release upload "$TAG" "$TMP/bank.sqlite.gz" --clobber

URL="https://github.com/$(gh repo view --json nameWithOwner -q .nameWithOwner)/releases/download/$TAG/bank.sqlite.gz"
echo
echo "完成。容器启动时会下载并解压："
echo "  $URL"
echo
echo "⚠️ entrypoint.sh 目前下载的是未压缩 .sqlite。若上传 .gz，"
echo "   把 Dockerfile 的 BANK_URL 改成上面的 URL，并在 entrypoint 里加一行解压："
echo "   gunzip -c /app/bank.sqlite.gz > /app/bank.sqlite"
