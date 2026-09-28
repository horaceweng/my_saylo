# Colab 批次語音辨識 + 翻譯

用 Colab 的免費 GPU，把大量 YouTube 影片或 Podcast 集數批次轉逐字稿、分句、翻譯，跑完後匯入主系統。
**跟主系統平常怎麼處理一支影片完全無關**——這是另外一條路，處理很多素材、又不想佔用自己電腦的資源時用。

## 需要什麼

- Google 帳號（跑 Colab、掛 Google Drive 存結果）
- `english-app/scripts/materials/materials.csv`：已經整理好、真實存在的教材清單（A2/B1/B2/C1+ 各 20 支影片、20 集 Podcast）
- **不需要任何雲端 API 金鑰**：翻譯直接在 Colab 這台機器上用 Ollama + qwen3:8b 跑，筆記本會自動安裝

## 步驟

1. 打開 `batch_transcribe_translate.ipynb`（上傳到 [colab.research.google.com](https://colab.research.google.com)，或直接用「在 Colab 開啟」開 GitHub 上的版本）。
2. 執行階段改成 GPU（選單「執行階段 → 變更執行階段類型」，選 T4）。
3. 從上到下依序執行每一格。安裝 Ollama、下載 qwen3:8b、下載 Whisper 模型都在跑的過程中自動完成，第一次會花幾分鐘。
4. 第 4 格可以先把 `MAX_ITEMS_PER_LEVEL_TYPE` 設小一點（例如 2）試跑，順利了再調大或設 `None`（全部跑）。
5. 跑完的結果在你的 Google Drive `english_lab_batch/` 資料夾裡（每個項目一個 JSON），最後一格會打包成 zip 方便下載。
6. 下載回本機後，在 `english-app/backend` 執行：
   ```
   uv run python scripts/import_batch.py /path/to/english_lab_batch
   ```
   會把每一份寫進 `data/app.sqlite`，開啟主系統就能直接看到，跟平常處理出來的影片沒有差別。已經匯入過的（同一個網址）會自動跳過，可以放心重複執行。

## 為什麼可以不碰主系統的程式碼

分句規則（連續超過 25 字被硬切開的問題）、幻聽過濾、長音檔分段、翻譯提示詞、`OllamaProvider`（跟 Ollama
溝通的方式）這幾個模組是純 Python，跟資料庫、FastAPI、mlx 都無關，筆記本會直接 `git clone` 你的 repo 來
重用同一份程式碼，確保跟本機處理影片時的規則一致——特別是翻譯用的是 Ollama 原生的 `/api/chat` 加
`think: false`，不是 OpenAI 相容介面（那個介面會忽略 `think: false`，同一句翻譯會從 2 秒變 47 秒，
主系統一開始就踩過這個坑）。匯入的部分也只是新增資料（`app/services/batch_import.py`），不會修改任何
現有的處理流程（`services/pipeline.py`）。

## GPU 資源怎麼分配

免費 T4 有 16 GB VRAM。Whisper 預設用 `large-v3-turbo`（跟主系統本機同一個模型，約 1.5 GB），Ollama 的
qwen3:8b 約 5 GB，兩個同時載入在 T4 上完全沒問題。如果想換更準的 `large-v3`（約 3 GB，第 4 格的
`WHISPER_MODEL_SIZE`），也還在容量內，只是轉字幕會慢不少。

## 已知限制、還沒驗證的部分

- **Colab 免費 GPU 會斷線、有時數上限**：每處理完一項就立刻存進 Google Drive，重新執行筆記本會自動跳過
  已完成的項目，斷線後接著跑不會重來，但要手動重新執行一次筆記本；Ollama 跟已下載的模型也會跟著消失，
  重新執行時會重新安裝、重新下載。
- **YouTube 反機器人措施**：下載時遇過「This video is not available」，其實是 yt-dlp 的預設用戶端被擋，改用
  `player_client=android` 解決了；筆記本已經套用這個修正，但這是 yt-dlp 和 YouTube 之間常態性的攻防，
  之後可能又需要調整（見 `scripts/materials/README.md`）。
- **實測踩過的三個坑，都已修好**：
  1. 存結果的那一格少 `import json`，語音辨識和翻譯明明成功了，最後一步存檔卻失敗——已修好。
  2. VOA 的音檔連結對 Python `httpx` 預設的 User-Agent 回 403（不是被擋 IP，本機測試同一個預設 UA 也一樣 403，換成瀏覽器 UA 就正常）——已加上瀏覽器 UA。
  3. 這台 Colab 映像檔預設沒裝 `zstd`，Ollama 官方安裝腳本需要它來解壓縮，沒裝會讓 `ollama` 執行檔沒裝成功——已在安裝格加上 `zstd`。
- **YouTube 下載遇到「Sign in to confirm you're not a bot」**：確認是 Colab 的 IP 被 YouTube 的反機器人機制擋下，比家用網路常見很多。解法（見第 6 節上面的說明）：從瀏覽器匯出登入狀態的 cookies，上傳到 `/content/cookies.txt`，下載函式偵測到這個檔案就會自動帶入 `--cookies`；沒有這個檔案還是照樣跑（不保證每支都成功）。**這份 cookies 等於你帳號當時的登入狀態，不是密碼，但能在有效期內冒充該帳號**：建議用備用帳號匯出、不要存進 Google Drive。
  第一次加 cookies 後測試仍然失敗：原因是原本用的 `player_client=android` 跟 cookies 互相打架（android／tv 用戶端走 app 內建認證，不看 cookies），
  已改成有 cookies 時用 yt-dlp 官方建議搭配 cookies 的 `web_safari`——**這個組合還沒有實測**，需要使用者驗證。
- **Podcast 那條路已經實測成功**：VOA（A2/B1）、BBC 6 Minute English（B2）、NPR Up First（C1+）各抓了一份，語音辨識、Ollama 翻譯、存檔全部正常，證明整條 pipeline（除了 YouTube 下載本身）是通的。：我沒有 GPU，無法在 Colab 上實測。純邏輯的部分
  （分句、幻聽過濾、批次翻譯重試、跟 Ollama 溝通的請求格式、音訊下載指令）都用假資料或真實的下載測試過，
  可以放心；但辨識準不準、qwen3:8b 翻譯品質好不好、整個流程順不順，要你自己跑過第一批才知道，建議先設
  `MAX_ITEMS_PER_LEVEL_TYPE = 2` 試跑。
- **教材清單會過期**：`materials.csv` 是 2026-09-28 抓的，YouTube 頻道會持續更新，同一份清單過一陣子可能有影片下架。
