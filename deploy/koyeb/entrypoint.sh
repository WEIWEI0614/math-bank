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
  echo "[entrypoint] 题库不存在，尝试下载: $BANK_URL"
  if curl -fsSL --retry 3 --retry-delay 2 -o "$GZ" "$BANK_URL" 2>/dev/null && [ -s "$GZ" ]; then
    gunzip -c "$GZ" > "$DB"
    echo "[entrypoint] 题库就绪: $(du -h "$DB" | cut -f1)"
  else
    # 下载失败不致命：serve.py 的 ensure_db 会从镜像内的 site/data/*.js
    # 自举题库表（约 0.3s），服务照常起。损失的只是容器内的历史 attempt
    # （那本来就会随重部署丢失，靠教师机每日拉回兜底）。
    echo "[entrypoint] 题库下载失败，降级为自举模式（无历史作答）" >&2
  fi
else
  echo "[entrypoint] 复用容器内题库: $(du -h "$DB" | cut -f1)"
fi

# 启动前确保表结构存在（serve.py 的 db() 里也有 executescript，双保险）
exec python3 /app/site/serve.py --port "${PORT:-8000}"
