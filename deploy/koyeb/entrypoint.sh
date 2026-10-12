#!/bin/sh
# Koyeb 容器入口：题库不在镜像里，启动时从 GitHub Release 拉取。
#
# 容器重建（重新部署/扩容）后 /app/bank.sqlite 回到 release 版本，
# 容器内写入的 attempt 全部丢失——这是免费层无持久卷的已知代价，
# 由教师机每日 sync-back.sh 拉回兜底。本地权威数据始终在教师机。
set -e

DB=/app/bank.sqlite
GZ=/app/bank.sqlite.gz

if [ ! -f "$DB" ]; then
  echo "[entrypoint] 题库不存在，下载: $BANK_URL"
  curl -fsSL --retry 3 --retry-delay 2 -o "$GZ" "$BANK_URL" || {
    echo "[entrypoint] 题库下载失败：检查 BANK_URL 与 release 是否存在" >&2
    exit 1
  }
  # fetch-bank-release.sh 上传的是 gz（56MB → ~15MB，启动快）
  gunzip -c "$GZ" > "$DB"
  echo "[entrypoint] 题库就绪: $(du -h "$DB" | cut -f1)"
else
  echo "[entrypoint] 复用容器内题库: $(du -h "$DB" | cut -f1)"
fi

# 启动前确保表结构存在（serve.py 的 db() 里也有 executescript，双保险）
exec python3 /app/site/serve.py --port "${PORT:-8000}"
