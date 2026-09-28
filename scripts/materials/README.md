# 分級教材清單（materials.csv）

160 筆真實存在、可公開存取的影片與 Podcast 集數，依 A2／B1／B2／C1+ 四個等級、影片與 Podcast 各 20 份整理，供 Colab 批次跑語音辨識與翻譯、跑完後匯入 `backend/data/app.sqlite` 用。**這份清單本身跟現有系統的處理流程無關**，只是原始資料來源。

## 來源與分級依據

| 等級 | 影片 | Podcast |
|---|---|---|
| A2 | VOA Learning English「Let's Learn English」YouTube 播放清單（官方為初學者設計的課程） | VOA Learning English「Health & Lifestyle」（VOA 官方說明：以中級偏初級的字彙、放慢 1/3 語速朗讀） |
| B1 | BBC Learning English「Real Easy English」YouTube 播放清單 | VOA Learning English「As It Is」（VOA 官方說明：中級） |
| B2 | BBC Learning English「Learning English from the News」YouTube 播放清單 | BBC Learning English「6 Minute English」 |
| C1+ | TED-Ed YouTube 頻道（原生語速，主題較深） | NPR「Up First」（原生新聞播報，未經簡化，只取 8–20 分鐘的一般集數，過濾掉特別長的專訪） |

分級是依照發布方自己的定位（VOA／BBC 官方文字說明、內容設計對象），不是用本系統的分級演算法算出來的——影片和 Podcast 目前沒有像書籍那樣的自動分級功能。

## 抓取方式

- 影片：`yt-dlp --flat-playlist` 對著上面的真實播放清單／頻道網址抓，每份都有真的可點開的 YouTube 網址。
- Podcast：直接下載真實的 RSS feed（VOA、BBC、NPR 官方位址），取 `<enclosure>` 的音檔網址；NPR 用 `<itunes:duration>` 過濾在 500–1300 秒之間的集數，避免抓到超長的專訪集數。
- 抓取時間：2026-09-28。頻道／節目會持續更新，同一個播放清單過一段時間重跑，抓到的內容可能不同；Podcast 的 RSS 只保留近期集數，VOA 的兩個 feed 目前各自只有 20 筆可用（剛好夠用），BBC／NPR 的則是從最新的往回取 20 筆。

## 欄位

`level, type, source, title, url, duration_sec, published`

- `type`：`video`（YouTube 網址）或 `podcast`（mp3／音檔的直接網址）
- `duration_sec`：秒數（YouTube 的較準；Podcast 取自 RSS 的 `itunes:duration`，VOA 的兩個 feed 沒有提供，欄位是空的）
- `published`：只有 Podcast 有，YouTube 這批沒有回傳發布日期

## 抓取時發現並修正的兩個問題

- **VOA 的 RSS `<enclosure>`其實是縮圖，不是音檔**：一開始直接拿 RSS 裡的 `<enclosure url=...>` 當音檔網址，結果是張 `.jpg` 縮圖。真正的 mp3 要另外打開每篇文章的網頁（`<link>`），從頁面內容找 `voa-audio.voanews.eu/.../*.mp3`。A2、B1 兩個等級的 40 筆全部改用這個方式重新抓過，並且每一筆都用 HTTP HEAD 確認過 `Content-Type: audio/mpeg` 才收進清單；也完整下載播放過其中一筆（4 分 37 秒），確定是真的能聽的音檔。
- **部分 YouTube 影片下載會回報「This video is not available」**：原因不是影片被下架（播放清單還列得出來），而是 yt-dlp 預設用的 web client 遇到 YouTube 目前的反機器人措施（SABR／JS challenge）失敗；改用 `--extractor-args "youtube:player_client=android"` 就正常了，`colab/batch_transcribe_translate.ipynb` 的下載函式已經加了這個參數。這是 yt-dlp 和 YouTube 之間常態性的攻防，之後如果又失效，可以再換成 `player_client=tv` 或 `ios`，或更新 yt-dlp。

## 使用限制

- 這些都是各機構官方公開發布的內容，用於個人英文學習沒有問題；但大量、自動化下載仍建議分批進行，避免對來源網站造成負擔或被暫時限流。
- BBC 的 RSS feed 附有使用條款（商業用途需另外取得授權），個人學習使用不受影響。
