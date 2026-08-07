#!/usr/bin/env bash
set -euo pipefail

# =============================================================
# BOMatch 数据库备份
# 使用 Python sqlite3 在线安全备份（正确处理 WAL，无需额外依赖）
#
# 用法:
#   bash backup.sh [应用目录] [备份目录] [保留份数]
#   默认: 当前目录 / 应用目录/backups / 保留 30 份
#
# cron 示例（每天 03:00 备份，追加日志）:
#   0 3 * * * /opt/bomatch/deploy/backup.sh >> /opt/bomatch/backups/backup.log 2>&1
# =============================================================

APP_DIR="${1:-$(pwd)}"
BACKUP_DIR="${2:-$APP_DIR/backups}"
KEEP="${3:-30}"
DB="$APP_DIR/data/bomatch.db"

if [ ! -f "$DB" ]; then
  echo "[$(date '+%F %T')] 错误: 未找到数据库 $DB" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
DEST="$BACKUP_DIR/bomatch_$STAMP.db"

python3 - "$DB" "$DEST" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
src_con = sqlite3.connect(src)
dst_con = sqlite3.connect(dst)
try:
    src_con.backup(dst_con)
finally:
    dst_con.close()
    src_con.close()
PY

echo "[$(date '+%F %T')] 备份完成: $DEST"

# 清理旧备份，仅保留最近 KEEP 份
ls -1t "$BACKUP_DIR"/bomatch_*.db 2>/dev/null \
  | tail -n +$((KEEP + 1)) \
  | xargs -r rm -f

echo "[$(date '+%F %T')] 已保留最近 $KEEP 份备份于 $BACKUP_DIR"
