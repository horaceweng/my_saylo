# 英文學習 Web App 規劃（本機版，全免費）

> 規劃：Opus 5.5（2026-09-25）｜執行：Sonnet 5
> 執行規則：每個階段完成後勾選並跑驗證，**使用者確認後才進入下一階段**。

## Context

使用者想做一個英文學習網頁 app，自己在 Mac 本機使用。首頁有三個入口：**影片**（YouTube）、**書籍**（書 + Podcast，依能力分級）、**新聞**。核心功能：字幕逐字高亮跟讀、每句翻譯、AI 句型說明、單句循環、存片語、shadowing（錄音並由 AI 比較差異），以及點字查詞（字根、字首、字尾、同義字、反義字、同字根單字）。

限制：**不使用任何付費 API**。全部在本機跑：
- 機器：Apple M3 Pro、18 GB RAM、剩 59 GB 硬碟
- 已安裝：Node 22、Python 3.12、ffmpeg、yt-dlp、Ollama（已有 `qwen3.5:9b`、`gemma4:e4b`）

第一個做的是 YouTube 影片模組。

參考專案：`/Users/HoracePro/IT/English/` 底下的 `everyone-can-use-english/enjoy`（shadowing UI：`src/renderer/components/medias/media-shadow-player.tsx`）、`Echo-Loop`（句子級學習流程）、`read-frog`（翻譯呈現）。這些專案都是 GPL/AGPL 授權，**只參考設計，不直接複製程式碼**。

---

## 技術選型（「用什麼 AI？」的答案）

| 用途 | 方案 | 說明 |
|---|---|---|
| 句子說明、翻譯、單字解釋、字根、shadowing 評語 | **Ollama + `qwen3.5:9b`**（已安裝） | 繁中能力好；關閉 thinking 模式降低延遲。透過 OpenAI 相容介面呼叫，後端抽象成 `LLMProvider`，之後想換 Claude API 只要改設定 |
| 語音轉字幕（含逐字時間戳） | **mlx-whisper**，模型 `large-v3-turbo` | Apple Silicon 原生加速，免費；`word_timestamps=True` 提供逐字高亮需要的時間。10 分鐘影片大約 1 分鐘轉完 |
| 字典 | **ECDICT**（MIT 授權，約 77 萬詞，離線） | 有中文釋義、音標、詞性，以及 CET4/6、TOEFL、IELTS、GRE 標籤和 BNC/COCA 詞頻，可以直接用來分新聞單字的難度顏色。用 **OpenCC** 轉成繁體 |
| YouTube 音訊與資訊 | yt-dlp（已安裝） | 下載音訊給 whisper 轉字幕；前端用 YouTube IFrame Player API 播放 |
| 新聞正文擷取 | trafilatura | 貼網址後抽出正文並分段 |
| RSS | feedparser | 新聞 RSS 和 Podcast RSS 共用 |
| EPUB | ebooklib + BeautifulSoup | 拆章節和段落 |
| 公版書 | Gutendex API（Project Gutenberg，免費、不用金鑰） | |

**架構**：
- 後端：Python **FastAPI**（whisper、yt-dlp、trafilatura 都是 Python 生態），套件用 `uv` 管理，資料庫用 SQLite（SQLModel）
- 前端：**Vite + React + TypeScript + Tailwind**，錄音波形用 wavesurfer.js
- 轉字幕、翻譯這類耗時工作走背景工作佇列（FastAPI BackgroundTasks + DB 狀態欄位），前端輪詢顯示進度

**AI 結果全部快取**在 `ai_cache` 表（key 為 `hash(kind + model + input)`），同一句或同一個字第二次查會直接回傳。

---

## 專案結構

```
/Users/HoracePro/IT/English/
  PLAN.md                  ← 本規劃（執行時隨進度更新勾選）
  english-app/
    backend/
      pyproject.toml
      app/
        main.py            FastAPI 入口、路由掛載
        db.py, models.py   SQLModel 資料表
        services/
          llm.py           LLMProvider 介面 + OllamaProvider（之後可加 ClaudeProvider）
          prompts.py       所有 prompt 集中管理（輸出 JSON schema）
          transcribe.py    mlx-whisper → segments + words
          segmenter.py     依標點和停頓把 whisper 的字重切成完整句子
          youtube.py       yt-dlp 下載音訊、取標題和縮圖
          dictionary.py    ECDICT 查詢、詞形還原（lemma）、難度等級
          shadowing.py     錄音轉字 → 逐字 diff → LLM 評語
          books.py, news.py, podcast.py
        routers/           media, dictionary, ai, phrases, shadowing, books, news
      scripts/import_ecdict.py   下載 ECDICT CSV → OpenCC 轉繁體 → dict.sqlite
      data/                app.sqlite, dict.sqlite, audio/, recordings/（加入 .gitignore）
      tests/
    frontend/
      src/
        pages/             Home, VideoList, VideoPlayer, Library(書+Podcast), BookReader,
                           PodcastPlayer, NewsList, NewsReader, Phrases
        components/
          TranscriptView   逐字高亮、句子翻譯、點字（影片和 Podcast 共用）
          SentenceToolbar  AI 說明 / 循環 / 存片語 / Shadowing
          WordPanel        單字解釋側欄 → 字根展開
          ExplainPanel     句型說明
          ShadowingModal   播放 / 暫停 / 錄音 / 回放 / AI 比較
          players/         YouTubePlayer、AudioPlayer，實作同一個 PlayerAdapter 介面
        hooks/usePlaybackClock.ts   requestAnimationFrame 讀 currentTime → 目前句 / 目前字
        api/               型別化的 fetch client
```

**關鍵抽象**：`PlayerAdapter { play, pause, seek(t), getCurrentTime, setRate }`。YouTube IFrame 和 HTML5 `<audio>` 都實作這個介面，`TranscriptView`、`SentenceToolbar`、`ShadowingModal` 只依賴介面，所以影片和 Podcast 共用同一套元件。

---

## 資料表（SQLite）

- `media`（id、kind=video|podcast、source_url、title、thumbnail、audio_path、duration、status=pending|transcribing|translating|ready|error、progress）
- `segment`（media_id、idx、start、end、text、translation）；`word`（segment_id、idx、text、start、end、prob）
- `saved_phrase`（text、context_sentence、translation、note、source_kind、source_id、timestamp、created_at）
- `book`（title、author、source=epub|gutenberg|text、cefr_level、score）；`chapter`；`paragraph`（text、translation）
- `article`（url、title、source、published_at、level）；`article_paragraph`；`feed`（url、kind=news|podcast、title）
- `recording`（segment_id、file_path、transcript、diff_json、feedback、created_at）
- `ai_cache`（key、kind、payload_json、created_at）
- `dict.sqlite`：ECDICT 單獨一個資料庫（word、phonetic、translation、pos、tag、collins、oxford、bnc、frq、exchange）

---

## AI 功能設計

所有 prompt 放在 `prompts.py`，要求模型輸出 JSON，並用 Pydantic 驗證；驗證失敗就重試一次。

1. **句子翻譯**：影片轉完字幕後，背景每批 20 句送 LLM 翻成繁中，並帶前後文，讓翻譯保持一致。
2. **句子 AI 說明**（`POST /ai/explain-sentence`）：回傳句型結構、文法重點、片語或慣用語、同句型的 3 個例句（附翻譯）。
3. **單字**（`GET /dictionary/{word}`）：
   - 先用 ECDICT 取音標、中文釋義、詞性、難度標籤、詞形變化（`exchange` 欄位）
   - 再用 LLM 補英文解釋、例句、字首/字根/字尾拆解、同義字、反義字，結果快取
   - 點擊的字先做詞形還原：用 ECDICT 的 `exchange` 欄位把 `went` 還原成 `go`
4. **字根**（`GET /dictionary/root/{root}`）：LLM 列出同字根單字，**再逐一用 ECDICT 驗證存在**，濾掉模型亂編的字，中文翻譯取自 ECDICT。
5. **Shadowing 比較**：
   1. 前端用 MediaRecorder 錄音，上傳到後端
   2. mlx-whisper 轉出逐字稿，含每個字的信心值
   3. 用確定性的逐字 diff（Python `difflib` 比對正規化後的字串）標出漏字、多字、錯字，信心值低的字標成「發音不清楚」
   4. LLM 依 diff 結果寫出繁中評語，指出漏掉的弱讀、連音、可能的發音問題並給練習建議
   5. 前端並排顯示原音和錄音的波形

   已知限制：免費方案沒有音素級的發音評分；whisper 會自動修正口音，比對會偏寬鬆。這點要在 UI 上註明。

---

## 分階段執行

### Phase 0 — 骨架與基礎服務
- [x] 用 `git init` 建立 `english-app/`，建 backend（uv + FastAPI）和 frontend（Vite React TS + Tailwind）；Vite 設 proxy 到 `/api`
- [x] 寫 `llm.py`（OllamaProvider，打 Ollama 原生 `/api/chat`（不是 OpenAI 相容的 `/v1`，後者會忽略 `think:false`，一句要 47 秒，原生只要 2 秒），模型名稱可在 `.env` 設定）
- [x] 寫 `transcribe.py`（mlx-whisper）和 `segmenter.py`；後者把 whisper 的字重新切成完整句子，依據是句尾標點、超過 0.7 秒的停頓，以及最多 25 個字的上限
- [x] 寫 `scripts/import_ecdict.py` 和 `dictionary.py`
- [x] 首頁放三個大按鈕：影片 / 書籍 / 新聞
- [x] 驗證：`uv run pytest`（segmenter、dictionary、llm 模擬測試）；轉一段短 mp3，檢查輸出有逐字時間戳

**Phase 0 完成紀錄（2026-09-25）**
- 驗證結果：`uv run pytest` 12 個測試全過；whisper 轉 mp3 得到 2 個句子、每字有時間戳；ECDICT 匯入 340 萬詞條（含繁體轉換），`went→go`、`children→child` 詞形還原正確；Ollama 單句翻譯＋句型 JSON 約 2.2 秒；`/api/health` 回報 Ollama 和字典皆正常
- 難度分級調整：詞頻前 3000 名一律算「基礎」，再看 GRE / TOEFL·IELTS / CET6 / CET4 標籤（否則 `the` 會因為帶 zk/gk 標籤被分到 CET4）
- 已知：`negotiate` 這類詞頻剛好在前 3000 的字會被算基礎，Phase 5 若覺得太寬鬆再調門檻
- 資料下載：ECDICT 217 MB、whisper 模型 1.6 GB（網路慢，共花約 1 小時）；下載檔在 `backend/data/raw/`，已加入 .gitignore，可以刪掉
- 前端 `npm run build` 通過，首頁有三個入口（影片／書籍／新聞），目前只有首頁，其他路由在 Phase 1 之後加


### Phase 1 — YouTube 影片（第一優先）
- [x] 影片清單頁：貼上 YouTube 網址 → 建立 `media` → 背景依序執行 yt-dlp 下載音訊、whisper 轉字幕、分句、批次翻譯 → 顯示進度條
- [x] 播放頁：左邊 YouTube IFrame，右邊（手機版在下方）`TranscriptView`
  - 目前句自動捲到畫面中，目前的字加陰影高亮；句子下方顯示翻譯（可切換顯示或隱藏）
  - 點句子跳到該句播放
- [x] 播放控制列（使用者要求）：放在影片下方、速度與翻譯之間，依序是上一句、後退 5 秒、播放/暫停、快進 5 秒、下一句；YouTube 原生控制列與鍵盤已關閉（`controls:0`），點影片畫面也是切換我們的播放/暫停；任何跳轉都會取消單句循環
- [x] `SentenceToolbar`：
  - AI 說明：開啟 `ExplainPanel`
  - 單句循環：播到 segment 結尾就 seek 回開頭
  - 存片語：選取文字或存整句，打 `POST /phrases`
  - Shadowing：Phase 2 才實作，這個階段先放按鈕
  - 播放速度 0.75×、1×、1.25×
- [x] 點任一個字開啟 `WordPanel`，裡面的字根可以點，展開同字根單字清單
- [x] 片語庫頁面 `/phrases`：列表、搜尋、刪除、點來源跳回影片的對應時間點
- [x] 驗證（自動化部分）：4 分鐘 TED-Ed 影片走完整流程；用模擬播放器確認逐字高亮、循環、自動捲動、存片語、片語庫
- [ ] 驗證（需要人工）：在你自己的瀏覽器用真實 YouTube 播放，確認高亮跟得上聲音（誤差小於 0.3 秒）、循環和點句跳轉。自動化用的瀏覽器分頁在背景，YouTube 不會載入影片，這部分無法由 Claude 驗證

**Phase 1 完成紀錄（2026-09-25）**
- 啟動：`cd english-app/backend && uv run fastapi dev app/main.py`，`cd english-app/frontend && npm run dev`，開 http://localhost:5173/videos
- 測試：後端 232 個、前端 68 個全過（前端含時鐘、循環回跳、前後句、NDJSON 讀取）
- 效能：4 分鐘影片，下載約 5 秒、轉字幕約 20 秒、翻譯（10 句一批，用編號回傳）約 1 分鐘；單字首次查詢約 18 秒，之後有快取
- yt-dlp 需要 JS 執行環境，已設成用 Node（`js_runtimes`），否則會缺格式
- 翻譯改用「編號當 key」回傳：原本整批依陣列順序，模型少回一句就整批退回逐句翻譯（7 分鐘）
- 字根功能加了兩道防線（9B 模型會亂列別的字根）：提示詞要求含字根字母，程式再過濾不含字根的字，並用詞頻把 `spic` 修成 `spice`
- 循環時點別句會自動取消循環，不然會被拉回原句
- 開發用：`/videos/1?fake=1` 用模擬播放器（照牆上時鐘走），不需要 YouTube 就能測 UI；只在 dev 模式有效
- AI 說明加速（使用者要求：只做串流，不預先生成，不縮短輸出）：
  - 串流：`POST /api/ai/explain-sentence/stream`（NDJSON），模型寫一段就轉給前端，第一批內容約 1–3 秒出現，完整輸出仍約 18 秒；後端用 `partial_json.py` 把寫到一半的 JSON 補齊解析，`explain_queue.py` 負責生成、快取、同一句共用一次生成
  - 只做使用者要求的工作：關掉說明面板或切到別句，會立刻中止模型生成（不會在背景寫完）；已生成過的句子存在快取，再點會立即出現
  - 曾經做過「預先生成目前句與前後句」，使用者決定不要（增加電腦負擔），已移除，端點 `/prefetch` 不存在
  - 模型比較（qwen3.5:9b vs gemma4:e4b，5 句）：gemma 快約 45% 但文法說明有小錯，所以說明維持 qwen；比較結果在 `backend/data/model_compare.md`
- 修正：單句循環回跳時，若下一句剛好緊接在後，目前句會閃到下一句一格（`resolveFrame` 改為用跳轉後的時間算）
- 修正 whisper 片尾幻聽（使用者要求）：音樂或靜默的片尾，whisper 會硬寫出亂碼或罐頭句（`Thank you.`、`The next time.` 重複 12 次、西里爾字母等），每次跑內容都不一樣
  - 過濾在 `services/hallucination.py`，轉字幕後、分句前套用；只看解碼信心與文字特徵，不改動辨識成功的語音：解碼失敗（avg_logprob < −1.0，whisper 自己的失敗門檻）、重複迴圈（壓縮比 > 2.4）、疑似靜默、逐字信心過低、非拉丁字母占比 > 7%（或靜默 4 秒後出現任何非拉丁字母）、字幕署名（amara.org 等）、靜默 4 秒以上之後出現的罐頭句（`Thank you.` 緊接在講話後面則保留）
  - 安全網：若整段音訊都被判為可疑（口音重、音質差），不刪，原樣保留；被丟掉的片段會寫進後端 log（WARNING）
  - 不採用 whisper 內建的 `hallucination_silence_threshold`：它會連正常語音一起改（刪掉整句 `and some studies show that`、把 `instead, what's really` 換成別的字）；對照實驗證明正常語音兩次辨識結果完全一致，所以差異來自該參數
  - 驗證：對測試影片按「重試」，12 個重複迴圈的片段全部被丟掉，逐字稿結束在真正的最後一句（218.7 秒），46 句全部有翻譯
- 修正：處理中的影片遇到後端重啟就中斷（使用者 60 分鐘影片多次出現「伺服器重啟，處理中斷」）
  - 原因：(1) 我在測試時多次重啟共用的後端，沒有先確認有沒有影片在處理，每次重啟都會中斷工作，啟動時再寫入那句錯誤；(2) 舊行程收到關閉訊號後不會馬上結束，要等背景工作跑完，所以舊、新行程會同時處理同一支影片（互相搶 GPU，也讓當時量到的翻譯時間變成 152 秒，不準）；(3) 按「重試」會整個重來，丟掉已完成的轉字幕和翻譯
  - 修法：中斷的工作在後端啟動時自動續傳（`pipeline.resume_unfinished`），已存的句子不再轉字幕、已翻的句子不再翻；`重試` 也是續傳，`POST /api/media/{id}/retry?restart=true` 才會完全重來；處理工作改由單一 daemon 執行緒佇列負責，停止後端時不會等工作跑完，同一支影片也不會同時被處理兩次
  - 限制：若在「轉字幕」階段被中斷，該階段會從頭再跑（60 分鐘的影片約 7 分鐘）；轉字幕沒有做中途存檔
  - 驗證：翻譯到一半重啟，舊行程 3 秒內結束，新後端自動續傳，只翻剩下的 29/49 句
- 乾淨的處理時間（4 分鐘影片、49 句、沒有其他工作同時跑）：轉字幕 29 秒、翻譯 60 秒、共 88 秒；翻譯約為 whisper 的兩倍。60 分鐘影片（851 句）估計轉字幕約 7 分鐘、翻譯約 17 分鐘。日誌會印出每次處理的各階段耗時
- 翻譯加速評估（使用者要求；同一批 40 句，20 句科普影片 + 20 句 CNBC 訪談，用正式的批次翻譯流程；完整逐句對照在 `backend/data/translation_compare.md`）：
  - qwen3.5:9b 52.9 秒（每句 1.3 秒）；gemma4:e4b 31.1 秒，快約 41%，但有 4 處明顯翻錯（horseradish→西洋山藥、Alphabet→字母順序、$140 billion→一百四十億、1 .5 million→15 到 200 萬），qwen 這 40 句沒有明顯錯誤 → 翻譯維持 qwen
  - 同時送 4 批不會更快：預設 Ollama 52.9→51.4 秒；另開一個 `OLLAMA_NUM_PARALLEL=4` 的實例測試也一樣（52.0→50.1 秒）→ 平行處理這條路排除
  - 兩個模型輸出都是正確的繁體；相同設定重跑，翻譯內容每次略有不同（temperature 0.3）
  - TranslateGemma 4B（專門的翻譯模型，官方建議的提示詞、逐句翻）：28.9 秒，比 qwen 快約 45%，但品質不好：至少 6 處明顯錯誤（`horseradish` 沒翻、把 wasabi 翻成「魚藤」；`about half the units` 翻成「兩倍」，意思相反；2 million 翻成「2 萬」；$140 billion 翻成「140 億」；heat receptors 翻成「味蕾」；`adrenaline-rich` 被漏掉），還混用「您／你」→ 不採用
  - 結論：翻譯維持 qwen3.5:9b；能在速度上追上它的模型（4B 級）品質不夠，品質可能夠的（TranslateGemma 12B、HY-MT1.5 7B）大小與速度跟 qwen 差不多，換了也不會明顯變快，所以不再下載更多模型
  - 更有效的方向（未做）：不縮短計算，而是縮短「等待」——轉完字幕加前幾批翻譯就開放閱讀，其餘在背景補翻；或有 YouTube 自動字幕時省下 whisper（只省約三分之一）
  - 其他專門模型資料（未測）：TranslateGemma 4B/12B（Ollama 官方，3.3/8.1 GB，支援 zh-TW；4B 已開始下載，約 1.1 MB/s）、Hunyuan HY-MT1.5 1.8B/7B（騰訊，WMT25 多項第一，官方有 GGUF）、Opus-MT（最快但輸出簡體）；NLLB、MADLAD、Tower 不考慮
- 縮短等待時間（使用者要求；2026-09-26）：60 分鐘的影片原本要等約 24 分鐘（whisper 約 7 分鐘 + 翻譯約 17 分鐘）才能開始看，現在 **65 秒**就能開始看
  - 分段轉字幕（`services/chunked.py`）：每 5 分鐘一段，音檔只解碼一次再切片；每段多轉 20 秒，段尾未完成的那一句留給下一段從句首重新開始，所以句子不會被切半、遺漏或重複；每段轉完立刻存進資料庫，第一段約 20–35 秒
  - 先翻譯再繼續轉：每轉完一段，就翻「使用者目前位置往後 40 句」（`LOOKAHEAD`），前 20 句翻完（`PLAYABLE_AFTER`）媒體就標成 `playable`，可以開啟；字幕全部轉完後，其餘句子從使用者位置開始往外補翻
  - 翻譯順序跟著播放位置：前端在句子改變時回報位置（`POST /api/media/{id}/focus`），跳到後面的句子，那附近的翻譯會被優先處理（實測跳到第 230 句，15 秒內就有翻譯，此時字幕還沒轉完）
  - 網頁：影片清單顯示「可以開始看 · 語音轉文字 27%」；播放頁上方有進度橫幅（字幕處理到 mm:ss / 總長、翻譯 已翻/總句數），尚未翻譯的句子顯示「翻譯中…」；輪詢改用輕量的 `GET /api/media/{id}/updates`（只送新句子與新翻譯，不重送整份逐字稿）
  - 中斷續傳：資料表新增 `media.transcribed`（舊資料庫啟動時自動 ALTER TABLE 補欄位，舊的完成影片標為已轉完）；轉字幕到一半被中斷時，從最後存下的句子後面接著轉
  - 修正：處理中按「刪除」，原本處理執行緒會因為寫入已刪除的資料而出錯甚至崩潰，現在會安靜停止、不留殘餘資料
  - 限制：整個檔案都被判為可疑（音質很差）時的最後手段，各段是直接接起來的，句子可能在段邊界被切開，橫跨段邊界的字可能掉 1 個；正常轉字幕不會有這問題
  - 驗證：60 分鐘音檔真實跑；後端 123 個、前端 38 個測試
- 已知：YouTube 首次可能出現廣告；shadowing 按鈕先放著（Phase 2）

### Phase 2 — Shadowing（共用元件）
- [x] `ShadowingModal`：播放原句（只播這一句）、暫停、錄音（MediaRecorder 輸出 webm，後端用 ffmpeg 轉成 16k wav）、回放自己的錄音
- [x] 「AI 比較」按鈕：逐字 diff 用顏色標示，下方顯示 LLM 評語，並排顯示雙波形
- [x] 每次錄音都存進 `recording`，可以看同一句的歷史紀錄
- [x] 驗證（自動化部分）：用 macOS `say` 合成的語音走真實流程（ffmpeg → whisper → 比對 → qwen 評語）：正確念 100%、把 eyes 念成 ears 標出「聽成 ears」86%、漏念 your 時 whisper 聽成 `make ice water`，顯示 your→ice 且 eyes 漏掉 71%；前端用假的錄音器走完開啟、錄音、停止（麥克風確實釋放）、比較、串流評語、歷史查看與刪除
- [ ] 驗證（需要人工）：在你自己的瀏覽器用真麥克風錄音，並確認波形有畫出來、原音與錄音可以播放。自動化用的瀏覽器分頁在背景，媒體元素不會載入，波形（wavesurfer.js）與播放無法由 Claude 驗證；麥克風權限也只能由你按允許

**Phase 2 完成紀錄（2026-09-25）**
- 使用：播放頁的句子工具列按「🎙 Shadowing」（會先暫停影片）。流程：聽原音 → 開始錄音／停止 → 「AI 比較」→ 逐字標示（念錯、漏掉、多念、不清楚）、完整度百分比、AI 評語（串流）→ 每一句的練習紀錄可回看、刪除
- 後端：`POST /api/segments/{id}/recordings`（上傳 → ffmpeg 轉 16 kHz wav → whisper → 逐字比對）、`GET /api/segments/{id}/audio`（從影片音訊切出這一句，有快取）、`POST /api/recordings/{id}/feedback/stream`（NDJSON 串流）；比對邏輯在 `services/shadowing.py`，錄音存在 `data/recordings/`，資料表 `recording`
- 比對規則：用 difflib 對齊句子與辨識結果；辨識信心低於 0.5 的字標「不清楚」；完整度＝念到的字 ÷ 句子的字（念錯的不算）。沒錄到聲音（RMS 太低）回 422，語音辨識忙碌時回 503
- 錄音不用「原句當提示詞」：那樣會讓 whisper 偏向照原句聽，變得太寬鬆
- 錄音的辨識不套用片尾幻聽過濾：信心低的字正是要找的訊號
- whisper 加了共用鎖：影片轉字幕和錄音辨識不能同時跑（mlx 不保證多執行緒安全），影片轉字幕中按比較最多等 90 秒
- AI 評語的限制與防線：9B 模型只看得到文字比對，卻愛寫音標、舌位（還會寫錯，例如 ears 的音標）；提示詞要求不要寫，模型仍不聽，所以後端在送出、儲存、讀取時都會把含音標符號或舌位、口型描述的建議與句子拿掉，沒有建議時補「重聽原音，放慢速度再念一次」
- 使用者調整（2026-09-25）：
  - 字幕預設隱藏（英文句子和中文翻譯都藏），按「顯示字幕／隱藏字幕」切換；比較結果那一塊才會顯示逐字標色的句子
  - 兩種練習方式用按鈕切換（選擇會記在瀏覽器）：「先聽再念」＝先聽原音再錄；「邊聽邊念」＝真正的同步 shadowing：按開始 → 倒數 3、2、1 → 開啟麥克風並開始錄音 → 播放原音 → 原音結束 1.5 秒後自動停止（也可手動停止或在倒數時取消）
  - 同步模式的注意事項：喇叭放出的原音會被麥克風錄進去，辨識會把原音當成使用者念的，分數會失真，所以要戴耳機；同步模式開啟瀏覽器的回音消除與降噪，畫面上有耳機提醒。目前沒有偵測「錄到原音」的功能
  - 流程邏輯在 `frontend/src/lib/syncShadowing.ts`（不含 React 與真計時器，有 7 個單元測試：順序、麥克風失敗、取消、原音沒回報結束時的保護計時器）
  - 未驗證：同步模式下原音實際播放的同時錄音、回音消除的效果、以及「原音播完的事件」觸發自動停止（自動化瀏覽器的媒體元素不會載入，測試時是靠保護計時器收尾）
- 已知限制：語音辨識會自動修正口音，結果可能偏寬鬆；漏念一個字時，辨識器可能把前後字合併聽成別的字（例如 make eyes water → make ice water），所以會顯示成念錯加漏掉；不是音素等級的發音評分（免費方案做不到），介面上已註明

### Phase 3 — Podcast（放在「書籍」入口的 Podcast 分頁）
- [x] 載入方式：貼 Podcast RSS（列出集數後選一集）、貼 mp3 網址、上傳音檔 → 共用 Phase 1 的轉字幕流程
- [x] `AudioPlayer` 實作 `PlayerAdapter`，重用 `TranscriptView`、`SentenceToolbar`、`ShadowingModal`
- [x] 控制列：播放/暫停、後退 5 秒、快進 5 秒（秒數可以在設定裡改）、上一句、下一句
- [x] 驗證（自動化部分）：BBC 6 Minute English 真實 RSS（342 集）→ 載入最新一集 → 下載 6 秒、60 秒後可以開始看、共 166 秒完成；學習頁的逐字高亮、存片語（記成 Podcast）、Shadowing 從下載的 mp3 切出原句都通過
- [ ] 驗證（需要人工）：在你自己的瀏覽器實際播放 Podcast 音檔，確認逐字高亮跟得上聲音、拖拉進度條、上一句／下一句／±5 秒、循環與 Shadowing 播放。自動化用的瀏覽器分頁在背景，`<audio>` 不會載入，這部分 Claude 無法驗證

**Phase 3 完成紀錄（2026-09-26）**
- 使用：首頁「書籍」→ Podcast 分頁。三種載入方式：貼 RSS 網址（列出集數，選一集載入，已載入的顯示「已載入」）、貼 mp3 網址（一鍵載入）、上傳自己的音檔（mp3、m4a、wav、ogg、flac）。載入後和影片走同一套流程（下載 → 分段轉字幕 → 先翻前幾句 → 可以開始看），學習頁是同一個 `MediaPage`（影片與 Podcast 共用逐字稿、句子工具列、單字面板、Shadowing、片語庫），只有上方的播放器不同
- 後端：`services/podcast.py`（RSS 解析：只列有音檔的集數、支援 iTunes 三種時長格式；網址類型判斷；串流下載，有進度、大小上限 600 MB、失敗不留殘檔、同一連結不重複下載）、`routers/podcasts.py`（`GET /api/podcasts/feed?url=`、`POST /api/podcasts`、`POST /api/podcasts/upload`）、`GET /api/media/{id}/audio`（支援 Range，可拖拉進度）、`GET /api/media?kind=` 過濾、刪除時一併清掉音檔（別的項目還在用同一個檔案就保留）
- 前端：`AudioPlayer`（實作 `PlayerAdapter`：封面、拖拉進度條、時間；播放/暫停/上一句/下一句/±5 秒沿用同一組控制列）、`Library` 頁、共用的 `MediaCard`、`useMediaList`、`lib/mediaStatus.ts`；片語庫的「回到這集」會去 `/podcasts/{id}`
- 重要修正：Podcast 訂閱裡寫的時長常常不準（實測某集訂閱寫 6:22、實際音檔 8:39），處理流程會用實際音檔長度覆蓋
- 已知：下載連結若是轉址（BBC 就是），會跟隨轉址並依回應的 Content-Type 決定副檔名；`?tab=book` 的「書」分頁目前只有佔位說明（Phase 4）；每集控制列的快進/後退秒數固定 5 秒，設定頁（Phase 6）再做成可調
- 測試：後端 147 個、前端 46 個

### Phase 4 — 書籍
- [x] 書庫頁分「書 / Podcast」兩個分頁，並提供能力分級篩選（A2 / B1 / B2 / C1+）
- [x] 匯入方式：上傳 EPUB、上傳 txt，或搜尋 Project Gutenberg 後一鍵下載（搜尋改用官方 OPDS，不用 Gutendex，原因見下）
- [x] 分級的算法：用 ECDICT 標籤算出超過 CET4 程度的字占多少比例，再加上平均句長，換算成 CEFR 等級（Phase 5 重新校準，見 Phase 5 紀錄）
- [x] 閱讀器：左邊章節目錄，右邊逐段呈現；每段有「翻譯」和「AI 說明」按鈕，點字開 `WordPanel`；記錄閱讀進度
- [x] 驗證：真實匯入 12 本 Gutenberg 書（EPUB）、1 本純文字，章節拆分與分級都檢查過；瀏覽器實測搜尋、匯入、閱讀、翻譯、AI 說明、閱讀位置還原、片語連結

**Phase 4 完成紀錄（2026-09-26）**
- 使用：首頁「書籍」→「書」分頁。搜尋公版書一鍵載入（約 2 秒）、上傳 EPUB 或 txt；依等級（A2／B1／B2／C1+）篩選，篩選鈕旁顯示各等級數量。閱讀器（`/books/{id}`）：桌機左側章節目錄、手機用「目錄」抽屜；每段可點字查詞（單字面板，句子當語境）、「翻譯」（串流，存起來只翻一次，可隱藏／再顯示）、「💡 AI 說明」（有選取文字就只說明選取的，否則整段）；閱讀位置捲動時自動儲存，重新開啟回到原位；片語庫的「📖 回到書中」連到那一段
- 後端：`services/books.py`（EPUB 用 ebooklib + BeautifulSoup，純文字自己拆）、`services/grading.py`、`services/gutenberg.py`、`routers/books.py`；資料表 `book`、`chapter`、`paragraph`；同一本書（Gutenberg 編號或檔案內容雜湊）不會重複加入；過長的段落（> 1200 字）在句子結尾切開
- 搜尋改用官方 OPDS（`gutenberg.org/ebooks/search.opds`，限定英文、依下載數排序）：計畫寫的 Gutendex 實測連續回 503，且要等 20–30 秒；OPDS 約 1 秒
- 分級公式（`grading.py`）：`分數 = 100 × 超過 CET6 的字比例 + 0.5 × 平均句長`；A2 < 15 ≤ B1 < 17.5 ≤ B2 < 21 ≤ C1+。專有名詞（句中大寫字）與字典查不到的字不計入。用 12 本真實的書校準：《綠野仙蹤》14.6（A2）、《愛麗絲》15.3、《福爾摩斯》15.6、《小飛俠》15.8、《德古拉》16.5、《叢林奇譚》17.0（以上 B1）、《湯姆歷險記》17.7、《傲慢與偏見》18.5、《黑神駒》19.3（B2）、《伊索寓言》21.6、《科學怪人》23.4、《白鯨記》26.6（C1+）。這只是估計：文學作品的難度不只看字彙和句長（例如《傲慢與偏見》的難在句法，估得偏低；《伊索寓言》的古文譯本字彙偏難，估得偏高），介面上已註明「難度是估計值」
- 真實 EPUB 才會遇到的問題（都已修並有測試）：每頁重複的書名被當成章節（《傲慢與偏見》原本多 15 個假章節）、Gutenberg 的 `Title :` 元數據行混進正文、首字下沉造成 `T o Sherlock`、一章被拆在好幾個檔案（接續的檔案要併回前一章）、插圖說明搶走章節標題、目錄裡指向檔案內部的條目（`#插圖`）改掉章名、`CONTENTS`／`INDEX`／授權條款被當成章節、`Part of the problem…` 這種一般句子被誤判成標題（標題關鍵字後必須接序號）、`Mr.` `Dr.` 後面不能斷句
- 已知限制：純文字沒有章節標題的書會每 40 段切成一「部分」；EPUB 裡的圖片與腳註不處理；一本書一次最大 60 MB；翻譯與 AI 說明用本機 9B 模型，段落翻譯約 4–7 秒；目前沒有「整章一次翻譯」；單字面板第一次查某個字要等 AI 補充內容（約 18 秒，之前就有的行為，之後有快取）
- 測試：後端 205 個、前端 56 個（Phase 4 完成當時）

### Phase 5 — 新聞
- [x] 載入方式：貼網址（trafilatura 抽正文後分段）；RSS 訂閱，預設 VOA Learning English 和 BBC，可自己加；列表顯示最新文章
- [x] 閱讀器：逐段呈現，每段有翻譯和 AI 說明
- [x] **單字底線顏色 = 難度**（這個功能原本還沒想清楚，建議這樣用）：
  - 用 ECDICT 標籤和詞頻分成 5 級：基礎（不畫底線）、中級 CET4、中高 CET6、進階 TOEFL/IELTS、高階 GRE 或罕用字
  - 已存進片語庫或查過的字另外用一種顏色標記
  - 設定裡可以選「我的程度」，只標出高於這個程度的字；畫面上附顏色圖例
  - 文章列表同時顯示整篇的難度等級
- [x] 驗證：從 VOA Learning English、BBC、卫报（另試 NPR）真實抓文章，正文擷取乾淨；底線分級用 12 本書與約 55 篇新聞校準，瀏覽器實測標色、程度切換、查過標記、片語連結

**Phase 5 完成紀錄（2026-09-26）**
- 使用：首頁「新聞」。上方貼任何英文文章網址就能讀；「最新文章」有 5 個預設訂閱（由易到難：VOA Learning English 的 Health & Lifestyle、As It Is、Science & Technology，BBC News，The Guardian · World），可以「＋ 新增訂閱」貼自己的 RSS、也可移除（預設訂閱只在第一次啟動時加入，刪掉不會再出現）；已讀過的文章顯示等級與「繼續閱讀」；「我讀過的文章」可依等級篩選。文章存成只有一章的「書」（`source='news'`），所以閱讀器、段落翻譯（串流）、AI 說明、單字面板、閱讀位置、片語庫（`📰 回到文章`）全部共用；閱讀器對新聞不顯示目錄，顯示來源、日期、等級與「原文 ↗」
- **單字底線顏色（這個功能的定案）**：底線顏色 = 難度。依字典等級：CET4 藍、CET6 綠、TOEFL/IELTS 琥珀、GRE／罕用 紅；「我的程度」（基礎／CET4／CET6／TOEFL·IELTS，預設 CET4）以下的字不畫底線，所以預設只標 CET6 以上；查過或存進片語庫的字用紫色底色（可和底線並存）；閱讀器上方有開關、程度選單與只顯示相關顏色的圖例；設定記在瀏覽器（`my-level`、`word-marks-enabled`、`seen-words`）。句中的大寫字（人名地名縮寫）不標。書籍閱讀器也同樣有標色。實測一篇 568 字的 BBC 文章只有 23 個字（4%）有底線，都是真正的難字
- 後端：`services/news.py`（trafilatura 抽正文與中繼資料；濾掉 `- Published`、圖片來源、分隔線、BBC 的隱藏 `external` 標籤；少於 80 字、非英文、被擋（401/402/403）都回明確的中文原因）、`routers/news.py`（`/api/news/feeds`、`/feeds/{id}/items`、`/articles`）、`POST /api/dictionary/levels`（一次查多個字的等級；連字詞如 `four-year` 取各部分最難的）、`Book` 新增 `url/published/site`、新資料表 `feed`、`setting`；`db._LATER_COLUMNS` 是通用的「舊資料庫補欄位」機制
- 實測來源：BBC、NPR、卫报、VOA 各節目；**VOA Learning English 的「總訂閱」現在幾乎全是播客與影片頁（沒有文字）**，所以預設改用它的三個有文字的節目訂閱；VOA 節目訂閱裡仍有少數影片頁，載入時會說「只有 N 個字，不像一篇文章」
- **順著標色發現並修掉的字典 bug**（都有測試）：(1) ECDICT 的詞形還原欄位有錯（`also→conjurer`、`of→have`、`some→an`、`they→it`），`lookup` 現在只相信「原形自己列出這個詞形」或「這個詞自己宣告是過去式／進行式等」的連結，代名詞與冠詞不當原形；(2) 難度改成「取最容易的那個考試級別」（`strict` 同時在 CET4 與 TOEFL 表，原本被分成 TOEFL 級）；(3) `frq` 為 0 的字（`an`、`BBC`）改用 BNC 詞頻，`were`、`is` 這類形態變化正確歸到 `be`
- **分級重新校準**（字典改了，原門槛失效）：難字 = 超過 CET4 的字（`level ≥ 2`）；`分數 = 100 × 難字比例 + 0.5 × 平均句長`；A2 < 12 ≤ B1 < 15 ≤ B2 < 18.5 ≤ C1+。書：《綠野仙蹤》11.8（A2）、《福爾摩斯》12.5、《愛麗絲》12.6、《小飛俠》13.4、《德古拉》13.5、《湯姆歷險記》13.7、《叢林奇譚》13.9（B1）、《傲慢與偏見》15.3、《黑神駒》16.3、《伊索寓言》17.2（B2）、《科學怪人》18.8、《白鯨記》22.6（C1+）。新聞：VOA 各節目 7–14（`American Stories` 最易）、BBC 中位數 16.4、NPR 16.0、卫报 19.9。`GRADING_VERSION`：分級方法一改，已存的書與文章在下次啟動時自動重新分級（你的《愛麗絲》因此由 A2 變 B1）
- 已知限制：需要登入、付費牆、靠 JavaScript 才顯示內容的網站抓不到；VOA 文章末尾的「Words in This Story」字詞表會變成幾個段落；分級仍是估計（句法難度看不出來，例如《福爾摩斯》可能被低估）；沒有「整篇一次翻譯」
- 測試：後端 232 個、前端 68 個

### Phase 6 — 打磨
- [x] 設定頁：LLM 模型、whisper 模型、快進秒數、我的程度、翻譯預設顯示或隱藏
- [x] 各頁面的載入中、錯誤、空資料狀態；Ollama 沒開時顯示提示
- [x] （可選）片語庫加上間隔複習
- [x] 額外：單字即時查詢、一個指令啟動（後端直接提供前端）、README

**Phase 6 完成紀錄（2026-09-26）**
- 啟動：`./scripts/start.sh`（必要時自動建置前端）→ http://localhost:8000，前端與 API 同一個 port；`/api/` 底下不存在的路徑回 404，其他路徑回前端（重新整理 `/settings` 也能開）。詳見 `english-app/README.md`
- 設定頁 `/settings`：語言模型（只列 Ollama 已安裝的，選未安裝的會回報 `ollama pull …` 指令）、Whisper 模型（標示是否已下載，未下載會提醒第一次使用要下載）、前進／後退秒數（3／5／10／15／30，套用到播放控制列）、翻譯預設顯示或隱藏（影片與 Podcast；書和文章的翻譯本來就是按需產生）、我的程度與難度標色開關、系統狀態。模型設定存在資料庫並在啟動時載入，不需重啟；秒數、翻譯、程度存在瀏覽器（`skip-seconds`、`show-translation`、`my-level`）
- 系統提示：畫面左下角的浮動提示（不影響版面），每 15 秒檢查 `/api/health`；Ollama 沒開、模型沒安裝、字典或 ffmpeg 找不到、後端連不上時各有對應說明，可關閉
- 單字查詢改為即時：字典部分（音標、意義、字形變化）立刻顯示，AI 補充（英文解釋、例句、字首字根字尾、同義反義）串流填入，快取後就是即時；切到別的字會中止上一個字的生成
- 片語複習 `/phrases/review`：簡化版 SM-2（忘了 10 分鐘後再問／有點難／記得／很簡單），一次最多 20 張，片語庫頁顯示到期數；`savedphrase` 新增欄位由啟動時自動補上，舊片語立刻算到期
- 各頁面：載入中、錯誤、空狀態補齊；新增 404 頁與 ErrorBoundary（頁面出錯時顯示訊息和回首頁，而不是空白）；頁面標題 English Lab
- 驗證（真實環境，重啟後）：一個 port 提供前端與 API；設定儲存與還原；未安裝模型回報錯誤；單字即時查詢 0.02 秒、AI 串流約 14 秒、快取後即時；複習頁顯示、翻面；模擬 Ollama 關閉時提示出現；影片頁點字後單字面板顯示 AI 內容
- 測試：後端 257 個、前端 78 個、`tsc -b` 皆過

**追加：Podcast 頻道（2026-09-26）**
- 貼上 Podcast RSS 後，「＋ 追蹤這個節目」把它固定成頻道；書籍 → Podcast 分頁最上方是「我追蹤的節目」（頭像＋名稱），點一個就即時讀取它的最新集數（已載入的顯示「已載入」），記住上次選的頻道；「不再追蹤」不會刪掉已載入的集數
- 後端：`feed` 資料表新增 `kind`（news／podcast）與 `image`，舊資料庫啟動時自動補上（舊訂閱都是 news）；`/api/podcasts/channels`（GET／POST）、`/channels/{id}`（DELETE）、`/channels/{id}/episodes`；單一音檔連結不能追蹤；新聞與 Podcast 的訂閱互不影響
- 測試：後端 261 個、前端 78 個；瀏覽器實測 BBC 6 Minute English：追蹤、頻道與集數顯示、不再追蹤、由貼上網址再追蹤（目前這個頻道已留在你的清單裡）

**追加：Colab 批次語音辨識＋翻譯（獨立功能，2026-09-28）**
- 動機：大量教材（不同等級 × 影片／Podcast）要做語音辨識和翻譯，用 Colab 的免費 GPU 跑，離線完成後匯入主系統，不佔用自己電腦資源，跟主系統平常的處理流程完全獨立
- 教材清單 `scripts/materials/materials.csv`：A2/B1/B2/C1+ 四個等級 × 影片／Podcast 各 20 份，共 160 筆，全部是真實查證過的來源（不是編造的連結）——影片：VOA「Let's Learn English」(A2)、BBC「Real Easy English」(B1)、BBC「Learning English from the News」(B2)、TED-Ed (C1+)，皆用 `yt-dlp --flat-playlist` 驗證過播放清單真的存在；Podcast：VOA「Health & Lifestyle」(A2)、VOA「As It Is」(B1)、BBC「6 Minute English」(B2)、NPR「Up First」(C1+)，皆下載過真實 RSS 並驗證音檔網址回應 `audio/mpeg`
- 抓取過程修正了兩個真實踩到的問題（見 `scripts/materials/README.md`）：VOA 的 RSS `<enclosure>` 其實是縮圖不是音檔，要另外抓文章頁面裡的 `voa-audio.voanews.eu` 網址；部分 YouTube 影片因為 yt-dlp 預設 client 遇到 SABR／JS challenge 回報「not available」，改用 `--extractor-args youtube:player_client=android` 解決
- Colab 筆記本 `colab/batch_transcribe_translate.ipynb`：`git clone` repo 後直接重用 `services/segmenter.py`、`hallucination.py`、`chunked.py`、`prompts.py`（純 Python，不依賴資料庫／FastAPI／mlx，跟本機處理同一套規則），GPU 用 faster-whisper（預設 `large-v3-turbo`，跟主系統本機同一個模型）轉逐字稿；每處理完一項就存進 Google Drive，重新執行會跳過已完成的項目，斷線不會重來
- 匯入端：`backend/app/services/batch_import.py`（`parse_item`／`import_item`，資料格式錯誤會擋下並說明原因；同一個影片或集數的連結已存在就跳過，不會重複）＋ `backend/scripts/import_batch.py`（CLI：`uv run python scripts/import_batch.py <資料夾>`，遞迴找 `*.json` 逐一匯入並印出成功／略過／失敗統計）
- 測試：後端新增 11 個（`test_batch_import.py`），全部通過（後端共 323 個）；額外用假資料驗證了分句＋幻聽過濾＋長音檔分段的重用邏輯、批次翻譯＋缺漏句子單獨重試的邏輯；`import_batch.py` 對著真實暫存資料庫跑過（匯入、重複略過、壞檔案回報錯誤、跨兩次執行結果一致）；用真實網路請求驗證了所有 160 筆素材的音訊／影片連結可以下載
- 未驗證：Colab 上的語音辨識與翻譯本身完全沒有實際跑過（沒有 GPU），辨識準確度、qwen3:8b 翻譯品質、整個流程跑起來順不順仍需要使用者自己在 Colab 上執行第一批才能確認；YouTube 的反機器人措施可能隨時再變化

**修正：翻譯改在 Colab 本機跑 Ollama + qwen3:8b，不叫雲端 API（2026-09-28）**
- 使用者要求：「既然是用 colab 的雲端，當然也要利用它來跑 ollama」——筆記本不再需要雲端 API 金鑰，改成安裝 Ollama、下載 qwen3:8b，直接重用主系統的 `app.services.llm.OllamaProvider` 與 `chat_json`，確保是原生 `/api/chat`、`think: false`（跟主系統最早踩過的坑一樣：OpenAI 相容介面會忽略 `think: false`，同一句從 2 秒變 47 秒，所以直接重用同一份程式碼而不是重寫）
- Whisper 模型改成預設 `large-v3-turbo`（原本筆記本預設 `large-v3`）：跟主系統本機同一個模型，準確又比 `large-v3` 快、VRAM 用量小很多，讓免費 T4（16 GB）能同時載入 qwen3:8b（約 5 GB）+ `large-v3-turbo`（約 1.5 GB）
- 測試：用假的 Ollama HTTP 回應驗證了 `OllamaProvider` + `chat_json` 的批次翻譯與缺漏句子單獨重試邏輯，並確認送出的請求是 `think: false`、走 `/api/chat`
- 未驗證：Ollama 在 Colab 上的安裝、GPU 偵測、qwen3:8b 實際跑起來的翻譯品質和速度，完全沒有實測過；實際跑的時候發現 Colab 影像缺少 `zstd`，Ollama 官方安裝腳本解壓縮會失敗（`ollama` 執行檔沒裝成功，導致 `ollama serve` 報 `FileNotFoundError`），已在安裝那一格加上 `zstd`，並加一行安裝後檢查。第一次小批試跑（16 份）三個問題都真的發生了：(1) `process_row` 寫結果檔那段少 import `json`，兩筆已經完整跑完辨識＋翻譯（194s、210s）卻在最後一步炸掉，已修好；(2) VOA 的音檔 CDN 對 `httpx` 預設的 User-Agent（`python-httpx/…`）回 403，不是 IP 被擋（在本機用同一個預設 UA 一樣 403，換成瀏覽器 UA 就 200），已加上瀏覽器 UA header；(3) 全部 YouTube 下載都失敗，但 `--quiet` 加上沒有擷取 stderr，只看到「exit status 1」看不出真正原因，已改成擷取 yt-dlp 的錯誤輸出直接顯示；真正原因還要等使用者重跑一次、看到實際訊息才能判斷（很可能是 Colab 所在的 Google Cloud IP 段被 YouTube 的反機器人機制擋下——重跑後證實了：真正的錯誤是「Sign in to confirm you're not a bot」，跟本機測試時完全正常形成對比。已加上可選的 cookies 支援（`COOKIES_FILE = /content/cookies.txt`，存在就自動帶入 `--cookies`，不存在就跟原本一樣），使用者要自己從瀏覽器匯出登入狀態上傳。同一批試跑（16 份）也證實了 Podcast 那條路完全正確：4 部（VOA A2/B1、BBC B2、NPR C1+）語音辨識＋翻譯＋存檔全部成功。加上 cookies 後 YouTube 仍然同樣失敗——原因是 `player_client=android` 跟 cookies 互相打架：android／tv 用戶端走 app 內建認證，根本不看 cookies，等於白帶；改成 yt-dlp 官方文件建議、跟 cookies 搭配用的 `web_safari`（沒有 cookies 時仍用 android，避開先前另一個問題），**這個組合還沒有實測**）

**追加：書與新聞朗讀（2026-09-26）**
- 書和新聞閱讀器可以朗讀：章節頂端「🔊 朗讀這一章／這篇文章」（從畫面上第一段開始）、每段的「🔊 從這裡朗讀」。朗讀時正在念的句子淡黃底、正在念的字深黃底，自動捲動跟著走；下方控制列有上一段／暫停／繼續／下一段／停止與速度（0.7–1.3×）；讀完一章會接著讀下一章；離開頁面或換章就停止
- 用瀏覽器內建的語音（Web Speech API）：免費、離線、不經過後端，沒有新的相依套件。設定頁新增「朗讀」：選聲音、速度、試聽；預設自動挑最好的英文聲音（優先 Premium／Enhanced、美式、本機）。想要更自然的聲音：macOS 系統設定 → 輔助使用 → 朗讀內容 → 系統語音 → 管理語音，下載進階／Premium 英文語音
- 實作：`lib/speech.ts`（`Reader` 逐句朗讀、`chunkText` 把段落切成每塊 ≤ 240 字的完整句子，避免長句被語音引擎截斷）、`hooks/useReadAloud.ts`、`components/ReadAloudBar.tsx`
- 測試：前端 93 個（新增 15 個：切句、選聲音、逐段朗讀、跳段、取消後的舊事件、暫停繼續、錯誤）；瀏覽器實測（Chrome，Alice 第一章）：逐字高亮、下一段、暫停／繼續、停止、離開頁面停止
- 未實測：整章讀完自動接下一章（只有單元測試）；其他瀏覽器（Safari 的字詞回報可能不同，沒有回報時只會標出句子）

**追加：自然語音朗讀（2026-09-26）**
- 瀏覽器內建語音太機械，改用本機的 **Kokoro-82M**（mlx-audio，Apache 授權，免費、不用 API）：後端一句一句合成 mp3，前端邊播邊預先取下一句；朗讀控制列、逐字高亮、跳段、暫停、換章沿用。合成速度約即時的 2–6 倍，第一句約 1 秒內開始（後端剛啟動的第一次要載入模型，約 8 秒）
- 後端：`services/tts.py`（模型只在專用的單一執行緒載入與使用，MLX 需要；語音存 `data/tts/*.mp3`，播放時更新時間，30 天沒播放的清掉）、`routers/tts.py`（`GET /api/tts/status`、`POST /api/tts/speak`）；速度在前端用 `playbackRate`（保持音高）調，所以快取不分速度
- 前端：`Reader` 改成依賴 `Speaker` 介面，兩個實作：`BrowserSpeaker`（內建語音，備援）與 `NeuralSpeaker`（後端語音）；設定頁「朗讀」可選聲音來源、11 個英文聲音（美式／英式、男／女）、速度、試聽；後端不能用時（缺 espeak-ng 等）設定頁與朗讀都會說明原因並改用內建語音
- 逐字高亮：Kokoro 不提供字的時間，所以依字長與逗號、句號的停頓**估算**每個字的位置（精準度不如內建語音的回報，但句子層級是準的）。若之後要精準，可以把合成好的音檔用 whisper 對齊一次
- 新的依賴：`mlx-audio`、`misaki[en]`、spaCy 的 `en_core_web_sm`（寫進 `pyproject.toml`，不再執行時下載）；後端環境約多 1 GB（PyTorch）；系統需要 `brew install espeak-ng`（套件內附的 espeak 在這台機器找不到自己的資料檔，所以用 Homebrew 版）
- 測試：後端 270 個、前端 108 個。實測：API 合成、快取、第二次即時；瀏覽器整合（背景分頁無法載入媒體，所以用假的播放時鐘搭配真的 mp3 解碼跑完整流程）：逐字標示、第一段結束接第二段、預先取下一句。**沒有實際聽到聲音的自動化驗證**，聲音好壞與逐字高亮跟得上聲音的程度需要你自己聽
- 未實測：真的把 Ollama 關掉（改用模擬 health 回應）、複習頁按下評分後的排程（後端測試涵蓋）

**追加：雲端 API 選項（2026-09-26）**
- 動機：16 GB 的機器同時載入語言模型（約 7–8 GB）與 Whisper（2–3 GB）很緊。設定頁「AI 服務」可把**語言模型**與**語音辨識**各自切到雲端（OpenAI 相容的 API），互不影響；預設仍是全本機、免費
- 建議方案（價格為 2026-09 查到的，會變）：語言模型 **Gemini 3.1 Flash-Lite**（輸入 $0.25／輸出 $1.50 每百萬 token，有免費額度但內容可能被用來改進產品）；備選 OpenAI gpt-5-mini（$0.25／$2）、gpt-5-nano（$0.05／$0.40）。語音辨識 **Groq whisper-large-v3-turbo**（每小時音訊 $0.04，約 15 秒轉完一小時，支援逐字時間）；備選 OpenAI whisper-1（$0.36／小時）。估算一小時影片翻譯＋轉字幕約 USD 0.1。Claude Haiku 4.5 是 $1／$5，翻譯用不到這個等級。朗讀（Kokoro）維持本機；雲端朗讀（如 gpt-4o-mini-tts 約 $0.015／分鐘）沒有做
- 後端：`services/llm.py` 新增 `OpenAICompatProvider`（`/chat/completions`，含串流 SSE；服務不接受 `response_format` 時自動改成不帶再問一次；錯誤轉成中文說明且不含金鑰）與 `make_provider()`（所有呼叫點改用它）；`services/cloud_stt.py`（每 5 分鐘一段轉成約 1.2 MB 的 mp3 上傳，`verbose_json` 取逐字與句子時間，429／5xx 依 Retry-After 重試最多 4 次，把「字」放回各自的句子，沿用原本的幻聽過濾）；`config.py` 新增 `llm_backend`／`cloud_*`／`stt_*`，`active_llm_model` 進快取鍵，換模型不會用到舊答案；`PUT /api/settings` 驗證（缺 Base URL、模型、金鑰就拒絕，本機位址不需金鑰）、金鑰只回傳最後四碼、`POST /api/settings/test/{llm|stt}` 測試連線；`/api/health` 在雲端模式不再要求 Ollama
- 前端：設定頁「AI 服務：本機或雲端」（服務預設、Base URL、模型、金鑰、測試連線、清除金鑰）；左下角提示會說雲端還沒設定好
- 金鑰存在 `app.sqlite` 的 `setting` 表（明文，只在這台電腦；備份資料夾時要注意）。跟讀（shadowing）比較仍用本機 Whisper，因為需要每個字的信心值
- 測試：後端 300 個、前端 111 個。實測：對一個假的 OpenAI 相容伺服器走真的 HTTP（聊天、串流、multipart 音訊上傳、錯誤金鑰、測試連線）；瀏覽器設定頁（切換、預設帶入、缺金鑰被擋下且沒有存下）。**沒有用真的雲端金鑰測過**（Gemini／Groq／OpenAI 的實際回應格式、Gemini 的 `response_format` 支援、思考 token 造成的實際費用都未驗證）——第一次用請先按「測試連線」，再拿一支短影片試

**修正：完整句子被切成兩半（2026-09-26）**
- 原因：分句器對每個句子設了 25 個字的硬上限，超過就在第 25 個字切開，不管句子有沒有結束（例：`…who takes money from the poor to fund | his lavish lifestyle, can't stand him.` 共 31 個字，被切成兩個沒意義的半句，後半句的翻譯還變成「此句已包含於第 1 句之語意中…」）
- 新規則（`services/segmenter.py`）：句子在標點結束處結束；只有超過 40 個字才在**下一個逗號**切開，超過 70 個字仍找不到逗號才在最長的停頓處切；停頓 0.7 秒以上且前面是逗號才算句尾，沒有標點要停 1.2 秒以上。順便修：結尾帶引號的句子（`…book?"`）現在算句尾，但引號後接小寫字（`… ?" thought Alice`，對話標記）不算；`Mr.`、`Dr.`、`J.` 這類縮寫不算句尾
- 已處理過的影片：`services/resegment.py` 用資料庫裡已存的字與時間重新分句（不需要重新轉字幕）。沒變的句子保留原本的翻譯，合併或新切出的句子清空翻譯並在背景重新翻譯；跟讀錄音改掛到現在包含它開頭的句子；啟動時做一次（`segmentation_version`），之後不重做。你的 7 部影片共 133 句需要重翻（重啟前已備份 `app.sqlite` 到 `/tmp/app_backup_before_resegment.sqlite`）
- 測試：後端 312 個（新增分句 9 個、重新分句 5 個）；用資料庫副本試跑：7 部影片句數 49→46、851→761、93→91、91→72、177→158、51→46、44→39，沒有孤兒錄音



---

## 驗證總覽
- 後端：在 `english-app/backend` 跑 `uv run pytest`
- 啟動：終端機一執行 `ollama serve`；終端機二在 backend 執行 `uv run fastapi dev app/main.py`；終端機三在 frontend 執行 `npm run dev`，然後開 http://localhost:5173
- 每個階段都用真實素材走完整流程，並用 Chrome 自動化截圖確認 UI

## 風險與注意
- YouTube 下載依賴 yt-dlp，YouTube 改版時要 `yt-dlp -U` 更新
- 9B 本機模型的說明品質不如 Claude；因為有 `LLMProvider` 抽象，之後想升級只要改設定
- whisper 和 Ollama 同時跑大約吃 10 GB 記憶體。18 GB 夠用，但轉字幕時要避免同時開其他大型程式
