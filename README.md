# English Lab

在自己的 Mac 上跑的英文學習網站，全部免費、不需要任何 API 金鑰：影片（YouTube）、書籍與 Podcast、新聞。
逐字高亮字幕、每句翻譯、AI 句型說明、單句循環、shadowing 跟讀比較、點字查詞、片語庫與間隔複習。

## 需要先安裝

- Python 3.12 + [uv](https://docs.astral.sh/uv/)、Node 22、ffmpeg、yt-dlp、espeak-ng（`brew install espeak-ng`，自然語音朗讀用）
- [Ollama](https://ollama.com)，並下載一個模型：`ollama pull qwen3:8b`
- 第一次使用前建立字典：`cd backend && uv sync && uv run python scripts/import_ecdict.py`

## 執行

```bash
ollama serve            # 另開一個終端機（已經在背景執行就不用）
./scripts/start.sh      # 建置前端並啟動，然後開 http://localhost:8000
```

之後只要 `./scripts/start.sh`；前端程式有改動時會自動重新建置。

## 帳號

所有 API 都要登入。第一次使用先建立管理員（舊的片語與錄音會歸給他）：

```bash
cd backend && uv run python scripts/create_admin.py <帳號>
```

之後管理員在「👥 使用者」頁產生邀請連結給別人註冊；只有管理員能看設定頁、刪除影片／書／訂閱。登入 cookie 預設只在 https 傳送；`start.sh` 在本機 http 使用時自動設 `COOKIE_SECURE=false`，用 `fastapi dev` 時請自己加上同一個環境變數。

## 開發

```bash
cd backend  && COOKIE_SECURE=false uv run fastapi dev app/main.py     # API，port 8000
cd frontend && npm run dev                        # 畫面，http://localhost:5173（/api 會轉到 8000）
cd backend  && uv run pytest                      # 後端測試
cd frontend && npx vitest run && npx tsc -b       # 前端測試與型別檢查
```

## 雲端 AI（選用）：記憶體不夠或想更快時

預設全部在本機跑（免費）。「設定 → AI 服務」可以把**語言模型**與**語音辨識**各自改成雲端服務（OpenAI 相容的 API，按用量付費，金鑰只存在你的電腦）。改成雲端後這台電腦不用再載入約 9–10 GB 的模型，適合 16 GB 的機器。

| 用途 | 建議 | 價格（2026 年 9 月，請以官網為準） |
|---|---|---|
| 翻譯、AI 說明、單字補充 | Google Gemini `gemini-3.1-flash-lite` | 每百萬 token 輸入 $0.25／輸出 $1.50；有免費額度（但免費額度的內容可能被用來改進產品） |
| 同上，另一選擇 | OpenAI `gpt-5-mini`／`gpt-5-nano` | $0.25／$2.00；nano $0.05／$0.40 |
| 語音辨識（轉字幕，要有逐字時間） | Groq `whisper-large-v3-turbo` | 每小時音訊 $0.04，一小時約 15 秒轉完 |
| 同上，另一選擇 | OpenAI `whisper-1` | 每小時 $0.36 |

一小時的影片，翻譯加轉字幕大約 USD 0.1（估算）。朗讀（Kokoro）與跟讀比較仍在本機。雲端模式會把字幕文字、音訊送給該服務商。

## 追蹤節目與新聞來源

新聞：在「新聞」頁按「＋ 新增訂閱」貼上 RSS。Podcast：在「書籍 → Podcast」貼上節目的 RSS 網址並查詢，按「＋ 追蹤這個節目」，之後點頻道名稱就會看到最新集數。

## 朗讀

書和新聞可以朗讀（章節頂端的「🔊 朗讀」，或每段的「🔊 從這裡朗讀」）。預設是**自然語音**：在這台 Mac 上執行的 Kokoro 神經網路語音（免費、不用 API），抑揚頓挫接近真人；第一次使用會下載約 330 MB 的模型。合成好的語音存在 `backend/data/tts/`，同一段再聽是即時的，一個月沒聽的會自動清掉。
聲音、速度在「設定」頁；也可以改用瀏覽器內建語音（較機械，但不需要後端）。

## 設定

在畫面右上角的「⚙️ 設定」：語言模型（Ollama 裡已安裝的）、語音辨識模型、前進／後退秒數、翻譯預設顯示、「我的程度」。
畫面左下角出現黃色提示時，代表 Ollama 沒開、模型沒安裝、找不到字典或 ffmpeg，照提示處理即可。
環境變數（`backend/.env`）可以改預設值，例如 `LLM_MODEL`、`WHISPER_MODEL`。

## 資料放在哪裡

`backend/data/`：`app.sqlite`（影片、書、片語、設定）、`dict.sqlite`（字典）、`audio/`、`recordings/`、`tts/`（朗讀語音的快取，可以刪）。備份這個資料夾即可。

## 限制

- 本機 9B 模型的翻譯與說明品質不如大型雲端模型，偶爾會有錯，重要的內容請自行判斷。
- shadowing 比較是逐字比對加上 AI 評語，沒有音素級的發音評分；Whisper 會自動修正口音，比對會偏寬鬆。
- YouTube 下載靠 yt-dlp，YouTube 改版後若失敗，執行 `yt-dlp -U` 更新。
