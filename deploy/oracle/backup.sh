#!/usr/bin/env bash
# 每日 SQLite 在线备份，跑在 VM 的 cron 上（每天 03:00）。
# 本地保留 7 天；末尾的 rclone 行取消注释后可同步到 OCI Object Storage（免费 10GB）。
set -euo pipefail

DB=/opt/mathbank/bank.sqlite
DEST=/opt/mathbank/backups
KEEP_DAYS=7

mkdir -p "$DEST"
STAMP="$(date +%Y%m%d-%H%M)"

# .backup 是 SQLite 官方的在线备份命令，WAL 模式下也保证一致性，
# 不像 cp 那样可能拷到半个事务
sqlite3 "$DB" ".backup '$DEST/bank-$STAMP.sqlite'"
gzip -f "$DEST/bank-$STAMP.sqlite"

# 清理旧备份
find "$DEST" -name 'bank-*.sqlite.gz' -mtime "+$KEEP_DAYS" -delete

# 异地备份（可选）：先 rclone config 配好名为 oci 的 S3 远端，再取消下行注释
# rclone sync "$DEST" oci:mathbank-backups --include 'bank-*.gz'

# 磁盘余量告警：低于 1GB 时写日志
FREE="$(df -BG --output=avail /opt/mathbank | tail -1 | tr -d ' G')"
if [ "$FREE" -lt 1 ]; then
  echo "[$(date)] 警告：/opt/mathbank 剩余空间不足 1GB" >&2
fi

echo "[$(date)] 备份完成: bank-$STAMP.sqlite.gz ($(du -h "$DEST/bank-$STAMP.sqlite.gz" | cut -f1))"
