# Mac mini 部署步驟（Phase 4）

在 Mac mini 上以 `horacemac` 登入，開終端機操作。路徑都是 mini 上的路徑。每一步跑完看輸出再做下一步。

本資料夾內容：

- `com.horaceweng.english-app.plist`：開機／登入後自動跑 `scripts/start-prod.sh`（綁 127.0.0.1:8000），掛了自動重啟
- `com.horaceweng.english-app-backup.plist`：每天 04:00 跑 `scripts/backup.sh`

## 0. 先確認

```bash
cd /Users/HoracePro/IT/English/english-app 2>/dev/null || cd ~/IT/English/english-app
pwd   # 應該是 /Users/horacemac/IT/English/english-app
git status --short
git branch --show-current
which uv node npm sqlite3 ffmpeg   # uv 可能在 /opt/homebrew/bin 或 ~/.local/bin，兩處 plist 的 PATH 都有
```

之後的指令都假設在 repo 根目錄：

```bash
cd ~/IT/English/english-app
```

## 1. 停掉手動啟動的伺服器

目前是在某個終端機用 `./scripts/start.sh` 跑的。

```bash
pgrep -fl "uvicorn app.main:app"      # 看是哪個程序
lsof -nP -iTCP:8000 -sTCP:LISTEN      # 確認誰佔著 8000
pkill -f "uvicorn app.main:app"       # 停掉（或到那個終端機按 Ctrl+C）
sleep 2
pgrep -fl "uvicorn app.main:app" || echo "已停止"
```

## 2. 備份現有資料庫

多使用者版會改資料庫結構，先留一份（`.backup` 在伺服器停掉或執行中都安全）：

```bash
sqlite3 backend/data/app.sqlite ".backup backend/data/app.before-multiuser.sqlite"
sqlite3 backend/data/app.before-multiuser.sqlite "PRAGMA integrity_check;"   # 要印出 ok
ls -lh backend/data/app*.sqlite
```

## 3. 更新程式

```bash
git fetch origin
git checkout multi-user        # 若已合併進 master 就用：git checkout master
git pull
cd backend && uv sync && cd ..
cd frontend && npm ci && npm run build && cd ..
```

## 4. 建立管理員帳號

```bash
cd backend
uv run python scripts/create_admin.py horace
cd ..
```

互動式輸入密碼（不會顯示）。

## 5. 建立 log 資料夾、安裝 LaunchAgent

```bash
mkdir -p ~/Library/Logs/EnglishApp ~/Backups/english-app
cp deploy/macmini/com.horaceweng.english-app.plist deploy/macmini/com.horaceweng.english-app-backup.plist ~/Library/LaunchAgents/
plutil -lint ~/Library/LaunchAgents/com.horaceweng.english-app*.plist
chmod +x scripts/start-prod.sh scripts/backup.sh

launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.horaceweng.english-app.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.horaceweng.english-app-backup.plist
launchctl print gui/$(id -u)/com.horaceweng.english-app | head -20
```

若 `bootstrap` 說已載入，先 `launchctl bootout gui/$(id -u)/com.horaceweng.english-app` 再來一次。

等 10 秒（第一次可能要建置前端），然後：

```bash
curl -s http://127.0.0.1:8000/api/health
tail -n 30 ~/Library/Logs/EnglishApp/out.log ~/Library/Logs/EnglishApp/err.log
```

`/api/health` 要回 JSON。沒回應就看 `err.log`。常見原因：找不到 `uv`（log 會寫）、8000 還被舊程序佔著（回到步驟 1）。

**試跑備份一次**（不用等到 04:00）：

```bash
launchctl kickstart gui/$(id -u)/com.horaceweng.english-app-backup
sleep 5
ls -lh ~/Backups/english-app/
tail -n 10 ~/Library/Logs/EnglishApp/backup.log   # 要看到 integrity_check: ok、備份完成
```

**Ollama 登入時自動開啟**：系統設定 → 一般 → 登入項目與延伸功能 → 加入 Ollama.app。

## 6. Tailscale Funnel（對外）

macOS App 版的 Tailscale CLI 不一定在 PATH 裡，找不到 `tailscale` 就用：

```bash
alias tailscale=/Applications/Tailscale.app/Contents/MacOS/Tailscale
```

先在 Tailscale 管理後台（https://login.tailscale.com/admin）：

1. Access controls（ACL）：在 `nodeAttrs` 加入 funnel 權限，例如
   ```json
   "nodeAttrs": [
     { "target": ["autogroup:member"], "attr": ["funnel"] }
   ]
   ```
2. Machines → mini → 選單 → Disable key expiry（關閉金鑰過期）。

然後在 mini 上：

```bash
tailscale funnel --bg 8000
tailscale funnel status
```

`funnel status` 應該只有一個 `https://horacemac-mini.tailcf37df.ts.net` → `http://127.0.0.1:8000`。**確認 4321 與 8500 沒有出現**（那是其他服務）。若出現：`tailscale funnel --https=<port> off`，或用 `tailscale funnel reset` 後只重開 8000。

驗證：手機關 Wi-Fi 用行動網路開 `https://horacemac-mini.tailcf37df.ts.net/`，看得到登入頁、登入後麥克風可用。

## 7. 你自己要做的（sudo／系統設定，Plan 4.6）

```bash
sudo pmset -a autorestart 1     # 停電後自動開機
```

- 系統設定 → 一般 → 軟體更新 → 自動更新的 ⓘ：關閉「安裝 macOS 更新」自動安裝
- 系統設定 → 網路 → 防火牆：開啟
- 考慮購買 UPS
- 讓 LaunchAgent 在沒人操作時也會跑：系統設定 → 使用者與群組 → 自動登入 horacemac（LaunchAgent 要登入後才會啟動）

## 8. 驗收

重開 mini，不登入任何東西（或只自動登入），3 分鐘內外網應能開啟登入頁。隔天 `ls ~/Backups/english-app/` 應有 `app-YYYYMMDD.sqlite`。

管理員頁（使用者）也會顯示 `data/` 大小與剩餘空間；剩餘低於 20 GB（`backend/.env` 的 `MIN_FREE_DISK_GB` 可調）時，所有人都不能新增影片、Podcast、音檔、書籍。

## 日常指令

```bash
launchctl kickstart -k gui/$(id -u)/com.horaceweng.english-app   # 重啟 app（更新程式後）
tail -f ~/Library/Logs/EnglishApp/err.log
```

## 回復（rollback）

```bash
# 1. 停掉並移除 LaunchAgent
launchctl bootout gui/$(id -u)/com.horaceweng.english-app
launchctl bootout gui/$(id -u)/com.horaceweng.english-app-backup
rm ~/Library/LaunchAgents/com.horaceweng.english-app.plist ~/Library/LaunchAgents/com.horaceweng.english-app-backup.plist

# 2. 停止對外
tailscale funnel reset      # 這會清掉所有 funnel 設定；之後如有別的服務要對外再自己開

# 3. 還原多使用者前的資料庫（確定沒有程序在用它）
pkill -f "uvicorn app.main:app" || true
cp backend/data/app.sqlite backend/data/app.multiuser-failed.sqlite   # 留存，以防萬一
cp backend/data/app.before-multiuser.sqlite backend/data/app.sqlite
rm -f backend/data/app.sqlite-wal backend/data/app.sqlite-shm

# 4. 回到多使用者之前的程式
git log --oneline master | head        # 找到合併／部署前的 commit
git checkout master~N                  # N 依上面的 log 決定（或直接 git checkout <commit>）
cd frontend && npm ci && npm run build && cd ..

# 5. 照舊手動啟動
./scripts/start.sh
```
