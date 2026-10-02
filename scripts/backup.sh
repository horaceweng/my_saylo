#!/usr/bin/env bash
# Daily backup (run by launchd at 04:00): an online-safe copy of app.sqlite (sqlite3 .backup, fine while the app
# writes), an integrity check of that copy, the newest 14 copies kept, and the recordings folder mirrored with rsync.
# Goes to ~/Backups/english-app, deliberately NOT under ~/MEGA (syncing a live SQLite file corrupts it).
# Overridable for tests: DATA_DIR (default <repo>/backend/data), BACKUP_DIR, BACKUP_KEEP, BACKUP_LOG.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="${DATA_DIR:-$ROOT/backend/data}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/Backups/english-app}"
KEEP="${BACKUP_KEEP:-14}"
LOG="${BACKUP_LOG:-$HOME/Library/Logs/EnglishApp/backup.log}"
SQLITE="${SQLITE3:-sqlite3}"

mkdir -p "$BACKUP_DIR" "$(dirname "$LOG")"
exec 3>&2  # the original stderr (launchd's backup.err.log): failures are repeated there
exec >>"$LOG" 2>&1
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }
fail() { log "備份失敗：$*"; echo "english-app backup FAILED: $*" >&3; exit 1; }
TMP=""
trap 'rm -f "$TMP"; log "備份失敗（第 $LINENO 行）"; echo "english-app backup FAILED at line $LINENO" >&3' ERR

log "開始備份：$DATA_DIR -> $BACKUP_DIR"
[ -f "$DATA_DIR/app.sqlite" ] || fail "找不到 ${DATA_DIR}/app.sqlite"

STAMP="$(date +%Y%m%d)"
DEST="$BACKUP_DIR/app-$STAMP.sqlite"
TMP="$DEST.partial"
rm -f "$TMP"
# Written under a temporary name and moved into place only after it checks out, so a bad copy never replaces a good one
# (running twice in a day simply replaces that day's copy).
"$SQLITE" "$DATA_DIR/app.sqlite" ".backup '$TMP'"
RESULT="$("$SQLITE" "$TMP" "PRAGMA integrity_check;")"
if [ "$RESULT" != "ok" ]; then
  rm -f "$TMP"
  fail "完整性檢查失敗：${RESULT}"
fi
mv -f "$TMP" "$DEST"
log "資料庫已備份：${DEST}（integrity_check: ok）"

# Keep the newest $KEEP copies (names sort by date).
COUNT=0
for f in $(ls -1 "$BACKUP_DIR"/app-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].sqlite | sort -r); do
  COUNT=$((COUNT + 1))
  if [ "$COUNT" -gt "$KEEP" ]; then
    rm -f "$f"
    log "刪除舊備份：${f}"
  fi
done

if [ -d "$DATA_DIR/recordings" ]; then
  mkdir -p "$BACKUP_DIR/recordings"
  rsync -a "$DATA_DIR/recordings/" "$BACKUP_DIR/recordings/"
  log "錄音已同步"
fi
log "備份完成"
