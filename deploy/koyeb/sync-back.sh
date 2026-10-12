#!/usr/bin/env bash
# 教师机每日拉回：把 Koyeb 云端的作答增量拉回本地（Koyeb 免费层无持久卷，
# 容器重部署会丢数据，本地才是最终权威）。跑在教师机 cron 上。
#
# 首次使用：
#   1. 教师登录拿 token（见下）
#   2. 把 token 写进 ~/.mathbank_env（chmod 600），cron 里 source 它
#
# 拿 token：
#   curl -s -X POST https://<你的>.koyeb.app/api/login \
#     -H 'Content-Type: application/json' \
#     -d '{"role":"teacher","pass":"你的教师口令"}'
#
# 加 cron（每天 03:00）：
#   0 3 * * * /path/to/deploy/koyeb/sync-back.sh >> ~/mathbank-sync/sync.log 2>&1
set -euo pipefail

KOYEB_URL="${KOYEB_URL:?先 export KOYEB_URL=https://你的服务.koyeb.app}"
ENV_FILE="${HOME}/.mathbank_env"
[ -f "$ENV_FILE" ] && . "$ENV_FILE"
TEACHER_TOKEN="${TEACHER_TOKEN:?在 ~/.mathbank_env 里设 TEACHER_TOKEN=...}"

DEST="${HOME}/mathbank-sync"
mkdir -p "$DEST"
STAMP="$(date +%Y%m%d-%H%M)"

# since 参数做增量：把上一次成功拉取的时间戳记在 state 文件里
STATE="$DEST/.last_sync"
SINCE=""
[ -f "$STATE" ] && SINCE="?since=$(cat "$STATE")"

echo "[$(date)] 拉取 $KOYEB_URL/api/sync$SINCE"
curl -fsS "$KOYEB_URL/api/sync$SINCE" \
  -H "Authorization: Bearer $TEACHER_TOKEN" \
  -o "$DEST/sync-$STAMP.json"

# 记录本次最大时间戳，下次增量从此继续（接口回显的 since 即请求值，
# 真正的断点用响应里最后一条 attempt 的 ts）
LAST_TS="$(/usr/bin/python3 -c "
import json,sys
d=json.load(open('$DEST/sync-$STAMP.json'))
ats=d.get('attempts') or []
print(ats[-1]['ts'] if ats else '')
" 2>/dev/null || true)"
[ -n "$LAST_TS" ] && echo "$LAST_TS" > "$STATE"

# 本地保留 30 天归档，防云端数据被重部署清掉后无处找回
find "$DEST" -name 'sync-*.json' -mtime +30 -delete

N="$(/usr/bin/python3 -c "import json;print(len(json.load(open('$DEST/sync-$STAMP.json')).get('attempts') or []))" 2>/dev/null || echo '?')"
echo "[$(date)] 完成：$N 条新作答 → $DEST/sync-$STAMP.json"
