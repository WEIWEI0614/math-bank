#!/usr/bin/env bash
# 把 5.5GB 原卷图推到一个独立的 public GitHub 仓库，供 jsDelivr CDN 引用。
# 一次性操作，之后图片更新才需要重跑。
#
# 为什么不进主仓库：主仓库已 942MB，图片 3GB+（工作区，另有 2.5GB 本地 git 历史）；
# GitHub 单文件 100MB 硬限（最大图 3MB，通过）但总容量逼近上限。
#
# 做法：硬链接到临时目录做 orphan 提交（不带原来 2.5GB 的 git 历史），
#       不动 site/data/img/.git 本身。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
IMG="$ROOT/site/data/img"
REPO="math-bank-img"

echo "==> 检查 gh"
command -v gh >/dev/null || { echo "先 brew install gh && gh auth login"; exit 1; }
OWNER="$(gh api user -q .login)"
echo "    账号: $OWNER"

echo "==> 建仓库（已存在则跳过）"
gh repo create "$REPO" --public --description "math-bank original paper images (jsDelivr CDN)" 2>/dev/null \
  || echo "    仓库已存在，继续"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "==> 硬链接图片到临时目录（不占额外磁盘，秒级）"
mkdir -p "$TMP/$REPO"
# -a 保留结构；--exclude 去掉 .git 与说明文件
rsync -a --exclude '.git' --exclude 'README.md' "$IMG/" "$TMP/$REPO/"

cd "$TMP/$REPO"
git init -q
git checkout -q -b main 2>/dev/null || true
git add -A
git -c user.email="$OWNER@users.noreply.github.com" -c user.name="$OWNER" commit -qm "original paper images"
git remote add origin "https://github.com/$OWNER/$REPO.git"

echo "==> 推送（约 3GB，家庭宽带约 15-40 分钟，断线就重跑本脚本，幂等）"
# GitHub 对大 push 有 HTTP/2 framing bug，强制 HTTP/1.1 + 大缓冲区是标准解法
git config http.version HTTP/1.1
git config http.postBuffer 524288000
git push -u origin main --force

cat <<DONE

完成。验证 jsDelivr 是否已索引（推送后通常几分钟内可用）：

  curl -sI "https://cdn.jsdelivr.net/gh/$OWNER/$REPO@main/$(ls "$IMG" | grep -v README | head -1)" | head -3

图片 URL 规则：https://cdn.jsdelivr.net/gh/$OWNER/$REPO@main/<原相对路径>
（index.html 的 IMG_BASE 与 serve.py 的 IMG_CDN_BASE 已按此配置，
 默认仓库名 WEIWEI0614/math-bank-img；若你的 GitHub 账号不是这个，改这两处。）

注意：jsDelivr 索引大仓库需要时间，刚推完可能 404，等几分钟再验证。
DONE
