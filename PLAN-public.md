# English Lab 對外開放規劃（邀請制、多人）

> 規劃：Opus 5.5（2026-10-02）｜執行：Sonnet（程式）＋使用者（需要 sudo / 管理後台的步驟）
> 執行規則：每個 Phase 完成後勾選、跑驗證，**使用者確認後才進入下一個 Phase**。
> 程式在 MacBook 的 `~/IT/English/english-app` 開發（分支 `multi-user`），推到 GitHub，Mac mini（`ssh macmini`，`~/IT/English/english-app`，master）再 `git pull`。
> MacBook 上 `colab/batch_transcribe_translate.ipynb` 有未提交的修改，**不要動它、不要提交它**。

## 已定案的決策

| 題目 | 決定 |
|---|---|
| 對外方式 | **Tailscale Funnel** → `https://horacemac-mini.tailcf37df.ts.net/`（免費、自動 HTTPS，麥克風可用） |
| 資料分法 | **內容共享、學習紀錄分人**：影片/段落/書/章節/新聞源/Podcast/AI 快取全站共用；片語庫（含 SRS 進度）、錄音、使用量綁 `user_id` |
| 帳號 | 邀請制：管理員產生邀請碼 → 對方用邀請碼註冊。沒有公開註冊 |
| 費用 | 擁有者出；LLM 主力用 **OpenCode Zen `space-bunny-free`**（`https://opencode.ai/zen/v1`，OpenAI 相容；使用者已知 OpenCode 表明免費額度只限自家客戶端、可能隨時被擋，接受此風險），失敗退回本地 Ollama（建議 `gemma4:e4b`，比 qwen3:8b 小）並記錄失敗次數與原因；STT 用 Groq（$0.04/小時音訊），失敗退回本地 mlx-whisper；每人每日配額 |
| 設定 | `Setting` 表維持全站一份，**只有管理員**能看/改；一般使用者看不到任何 key |

OpenCode Zen 免費模型的注意事項（2026-10 查證）：免費模型是限時提供、會輪替；多數免費模型的輸入可能被拿去訓練（Space Bunny、LongCat 標示 zero-retention，優先選這兩個）；**沒有語音轉文字**。所以必須有退回本地的機制，且模型名要能在設定頁改。

---

## Phase 0 — 基準測試（Mac mini，主要由使用者執行）

- [x] 0.1 RAM 峰值：在 mini 上同時跑一支 10 分鐘影片轉錄（本地 whisper large-v3-turbo）＋連續 AI 句子說明（qwen3:8b），另開終端機 `vm_stat 5` / `memory_pressure`，記下是否進 swap、壓縮記憶體多少
  - **結果（2026-10-02）**：同時跑時記憶體壓力**全程黃色**；wired ≈ 7.2 GB（qwen3:8b 在 GPU 佔 5.6 GB）、壓縮區 ≈ 4.9 GB、free < 0.2 GB；每 5 秒寫出 swap 最多約 190 MB，測試期間共寫出約 2.6 GB。結論：**16 GB 不能同時載入 qwen3:8b + whisper large-v3-turbo**；本地只能當備援、一次只放一個模型在記憶體
- [x] 0.2 使用者到 opencode.ai 登入取得 Zen API key，到 Groq 取得 API key（只放 mini 的設定頁，不進 git）
- [x] 0.3 模型評估：用 `backend/data/model_compare.*` 的方式，拿 Space Bunny / LongCat / 一個 MiMo 免費模型各跑 20 句「句子說明 + 翻譯 + 單字解釋」，比較 JSON 解析成功率、繁中品質、延遲、是否被限流（429）
  - **結果（2026-10-02，詳見 `backend/data/model_compare_zen.md`）**：10 個免費模型中 9 個從 API 呼叫一律 403 `FreeTierError: OpenCode's free tier can only be used from within OpenCode`；只有 `space-bunny-free` 可用：31/31 次 JSON 第一次就合法、延遲中位 13.1 秒／p90 24.5 秒、0 次 429；說明文字偶有簡體字（构、调、强、赶），翻譯欄位全為繁體；品質優於本地 9B/4B，偶有不自然例句
- [x] 0.4 依結果決定：LLM 主模型、本地 fallback 模型、每日配額數字（寫回本檔「已定案的決策」）：主模型 `space-bunny-free`；本地備援建議 `gemma4:e4b`（需使用者在 mini 上 `ollama pull`）；配額先用 Phase 2 預設值，Phase 5 再依實際用量調整

驗證：本檔記錄 0.1 的數字與 0.3 選定的模型。

## Phase 1 — 帳號與資料分人（程式，Sonnet）

後端
- [x] 1.1 新增依賴 `pwdlib[argon2]`（argon2 雜湊）
- [x] 1.2 新表：`User(id, username unique, password_hash, is_admin, disabled, created_at)`、`Invite(code pk, created_by, used_by, created_at, expires_at)`、`AuthSession(token_hash pk, user_id, created_at, expires_at, last_seen)`
- [x] 1.3 `SavedPhrase`、`Recording` 加 `user_id`（經由 `db.py` 的 `_LATER_COLUMNS`，舊資料歸給第一個管理員）；`Media`、`Book`、`Feed` 加 `added_by`（只做紀錄/配額，不限制看得到）。錄音檔案路徑改 `data/recordings/<user_id>/`，舊檔不搬，路徑照 DB 記錄
- [x] 1.4 建立第一個管理員：`backend/scripts/create_admin.py <username>`（互動輸入密碼）；啟動時若沒有任何 User 就在 log 警告，不自動建立
- [x] 1.5 `app/routers/auth.py`：`POST /api/auth/login`、`POST /api/auth/logout`、`POST /api/auth/register`（需有效邀請碼）、`GET /api/auth/me`。Session 用隨機 token 存 HttpOnly + Secure + SameSite=Lax cookie，DB 只存 token 的 sha256；30 天到期
- [x] 1.6 `current_user` / `admin_user` dependency；除了 `/api/auth/*` 與精簡版 `/api/health`（未登入只回 `{ok}`）以外，所有 `/api/*` 都要登入。用 router 層級的 `dependencies=[...]` 套，不要每個端點各加
- [x] 1.7 片語、SRS 複習、錄音、shadowing 評語：查詢與修改都要以 `user_id` 過濾；存取別人的 id 回 404
- [x] 1.8 管理員限定：`/api/settings` 全部（讀和寫）、刪除共享內容（影片/書/新聞源/Podcast 頻道）、`/api/admin/*`（邀請碼產生/列表、使用者列表/停用）
- [x] 1.9 測試：`tests/conftest.py` 加已登入/管理員/另一位使用者的 client fixture；既有測試改用已登入 client；新增 `test_auth.py`（登入、錯誤密碼、邀請碼只能用一次、過期、停用帳號、session 過期）與「A 看不到 B 的片語/錄音」測試

前端
- [x] 1.10 登入頁、邀請碼註冊頁（`/register?code=…`）、右上角使用者名稱 + 登出
- [x] 1.11 `api/client.ts` 收到 401 → 導向登入頁；串流端點（ndjson）也要處理
- [x] 1.12 非管理員隱藏設定頁入口；管理員多一個「使用者」頁：產生邀請連結（可複製）、使用者列表、停用

驗證：`uv run pytest`、`npm run build`、`npm test` 全過；本機啟動後手動走一次：建管理員 → 產生邀請 → 無痕視窗註冊第二個帳號 → 兩邊各存片語互相看不到 → 第二個帳號看不到設定頁、打 `/api/settings` 回 403。

## Phase 2 — 運算佇列、模型路由、配額（程式，Sonnet）

- [x] 2.1 全域「本地重運算鎖」：本地 whisper、Ollama、本地 TTS、shadowing 的本地 STT 同時只跑一個（`threading.Semaphore(1)`，async 端用 `asyncio.to_thread` 取鎖）。先盤點所有呼叫點：`transcribe.py`、`llm.py`（Ollama provider）、`tts.py`、`shadowing.py`、`pipeline.py`、`explain_queue.py`。雲端呼叫不吃這把鎖
- [x] 2.1b 換模型前先釋放：要跑本地 whisper／TTS 前，先請 Ollama 卸載模型（`POST /api/generate {"model":…, "keep_alive":0}`）；whisper 用完也釋放（mlx 清快取）。Ollama 請求一律帶較短的 `keep_alive`（例如 60s），不要讓 5.6 GB 一直佔著（依 0.1 的實測結果）
- [x] 2.2 LLM 路由：`llm.py` 新增「主要 = cloud（OpenCode Zen）、失敗（連線錯誤、429、5xx、逾時、JSON 解析連續失敗）→ 本地 Ollama」的 fallback provider；設定頁加「失敗時改用本地模型」開關。AI 快取 key 已含模型名，不用改
- [x] 2.3 STT 路由：同樣做 cloud（Groq）→ 本地 mlx-whisper 的 fallback
- [x] 2.4 排隊狀態：影片處理佇列回報「排隊中，前面 N 個」；句子說明在等鎖時送一個 `{"type":"queued","position":N}` 事件；前端顯示，而不是空轉
- [x] 2.5 逾時：單一 LLM 請求 120 秒、單支媒體處理總時長上限（例如音訊長度 × 3 + 10 分鐘），逾時標記失敗並可重試
- [x] 2.6 `UsageEvent(id, user_id, kind, amount, created_at)` + 配額檢查（預設值放 `config.py`，Phase 0 後調整）：每日新增媒體 5 支、每日音訊 90 分鐘、每日 AI 請求 300 次、單檔上傳 100 MB、單支媒體最長 90 分鐘。超過回 429 + 中文說明；管理員不受限；AI 快取命中不計次
- [x] 2.7 簡單速率限制（in-memory）：登入/註冊每 IP 每分鐘 10 次；一般 API 每使用者每分鐘 120 次。注意 Funnel 進來的真實 IP 在 `X-Forwarded-For`，只在來源是 127.0.0.1 時信任這個 header
- [x] 2.8 管理員「使用者」頁顯示每人今日用量
- [x] 2.9 測試：fallback（mock provider 丟 429 → 改用本地）、配額邊界、鎖的互斥（兩個工作不重疊）、速率限制

驗證：pytest 全過；本機開兩個帳號同時送轉錄 + 句子說明，畫面出現排隊狀態、`top` 只看到一個重運算在跑。

## Phase 3 — 安全強化（程式，Sonnet）

- [x] 3.1 **SSRF 防護**：使用者給的網址（新聞文章 `news.py`、RSS/Podcast 訂閱 `podcast.py`/`news.py`、YouTube 匯入）在連線前解析 DNS，拒絕 loopback、私有網段、link-local、`100.64.0.0/10`（Tailscale）、`.local`/`.ts.net`；redirect 後也要再檢查。YouTube 只接受 youtube.com / youtu.be。設定頁的雲端 URL 測試（`app_settings.py:213`）僅限管理員即可
- [x] 3.2 上傳驗證：書（EPUB/TXT）、Podcast 音訊、錄音的副檔名 + 實際內容（magic bytes / ffprobe）+ 大小上限，在讀進記憶體前就擋（串流讀取計數）
- [x] 3.3 確認 `mount_frontend` 只送出 `frontend/dist`，打 `/../.env`、`/api/../data/app.sqlite` 之類路徑回 404；`/api/settings` 回應不含完整 key（已有 `mask`，加測試鎖住）
- [x] 3.4 安全標頭 middleware：`X-Content-Type-Options: nosniff`、`Referrer-Policy: same-origin`、`X-Frame-Options: DENY`、`Permissions-Policy: microphone=(self)`；不加 CORS（同源，不需要）
- [x] 3.5 新增 `scripts/start-prod.sh`：同 `start.sh`，但綁 **127.0.0.1**:8000（Funnel 從本機轉進來，區網不再能直接連沒驗證的 port）、`--proxy-headers --forwarded-allow-ips 127.0.0.1`
- [x] 3.6 最後跑一次 `/security-review` 與 `/code-review high`，處理發現的問題（改由人工逐項審查 master..multi-user 全部 diff：補了請求大小上限、關閉公開的 /docs、retry/TTS 配額、登入依帳號限速、未知檔案路徑一律 404）

驗證：pytest 全過；手動用 curl 試 SSRF（`http://127.0.0.1:11434`、`http://192.168.50.1`）被拒。

## Phase 4 — Mac mini 部署與維運（Sonnet 準備檔案，使用者執行 sudo 與後台步驟）

部署前：在 mini 上 `sqlite3 backend/data/app.sqlite ".backup backend/data/app.before-multiuser.sqlite"`。

- [ ] 4.1 mini：`git pull`、`uv sync`、`npm install && npm run build`、`uv run python scripts/create_admin.py horace`
- [ ] 4.2 launchd：`~/Library/LaunchAgents/com.horaceweng.english-app.plist` 跑 `start-prod.sh`，`KeepAlive`、log 到 `~/Library/Logs/EnglishApp/`（仿照 `com.horaceweng.tradingstrategy`）；Ollama App 設為登入時開啟。先停掉手動跑的那份再 load
- [ ] 4.3 Tailscale Funnel：使用者在 Tailscale 管理後台的 ACL 開啟 funnel nodeAttr，並關閉 mini 的 key expiry；mini 上 `tailscale funnel --bg 8000`；確認 `https://horacemac-mini.tailcf37df.ts.net/` 外網（手機關 Wi-Fi）可開、麥克風可用；確認 4321、8500 **沒有**被 funnel（`tailscale funnel status`）
- [ ] 4.4 每日備份：launchd 每天 04:00 跑 `scripts/backup.sh`：`sqlite3 .backup` 到 `~/Backups/english-app/app-YYYYMMDD.sqlite`，保留 14 份，加上 `data/recordings/` rsync。**不要**放進 `~/MEGA`（避免同步正在寫的 SQLite）
- [ ] 4.5 磁碟：管理員頁顯示 `data/` 大小與剩餘空間；剩餘 < 20 GB 時拒絕新的媒體匯入
- [ ] 4.6 使用者自己做（sudo / 系統設定）：`sudo pmset -a autorestart 1`（停電後自動開機）；系統設定 → 一般 → 軟體更新：關閉「安裝 macOS 更新」自動安裝；系統設定 → 網路 → 防火牆：開啟；考慮購買 UPS
- [ ] 4.7 專用非管理員帳號：**這次不做**（其他服務都跑在 horacemac，launchd 也是；app 只綁 127.0.0.1 已降低曝險）。之後若擴大再評估

驗證：重開 mini 後不登入任何東西，3 分鐘內外網可打開登入頁；隔天 `~/Backups/english-app/` 有檔案。

## Phase 5 — 小範圍邀請測試

- [ ] 5.1 邀請 2–3 位親友，一週後看：每日用量、fallback 到本地的次數、OpenCode 429 次數、Groq 費用、mini 記憶體壓力
- [ ] 5.2 依數據調整配額與主模型

## Phase 6 — 之後再決定

維持邀請制（YouTube/Podcast 轉錄的版權/ToS 風險，不建議公開註冊）；若人數變多再評估 Cloudflare Tunnel、付費 LLM、獨立服務帳號。

## Phase 3.5 — 部署前補強（程式，Sonnet）

- [x] 3.7 書的閱讀進度改成每人各自一份（目前全站共用一個值）
- [ ] 3.8 雲端模型失敗紀錄：每次失敗記下原因（HTTP 狀態碼／錯誤類型／訊息摘要），管理員頁顯示今日與 7 天內依原因分類的次數、最後一次失敗的時間與訊息；最近連續多次都是 403／FreeTierError 時，管理員頁明顯提示「雲端模型可能已被停用」

## 待議（使用者 2026-10-02 提出，以後再說）

- 跟讀可考慮「只錄音回放、不做 AI 判斷」模式：不跑 Whisper 辨識、不呼叫 LLM 評語，只讓使用者回放自己的錄音和原句對照。可做成使用者自選或管理員全站開關，能大幅減輕 mini 的運算負擔。
