# PMB — Pre-Market Macro Brief

美股盤前總經自動研究系統。每個交易日盤前研判美股市場(各大指數、總經、market regime,槓桿作風險教育),產出一支 30 秒公開說明影片(YouTube)與一份當日研究報告。受眾是一般大眾,內容與任何個人 portfolio 脫鉤。

> 正式規格見 [`premarket-macro-brief-system-plan.md`](premarket-macro-brief-system-plan.md);專案指令見 [`CLAUDE.md`](CLAUDE.md)。

## 核心原則

- **數字走 API,絕不讓 LLM 生成**:指數點位、漲跌幅、殖利率、VIX、CPI 等一律來自資料層(FRED / yfinance)。
- **研究與機械分離**:只有「研判 + 文字生成」用 agentic LLM;取數、畫圖、配音、合成、上傳是確定性流程。
- **開發期一律不對外發布**:發布功能預設 dry-run / 需人工放行。

## 開發環境

- Python 3.12+
- [Poetry](https://python-poetry.org/) 套件管理

```bash
poetry install              # 安裝依賴
cp .env.example .env        # 填入 FRED_API_KEY
poetry run pmb fetch        # 取得當日真實數據快照
poetry run pytest           # 跑測試
poetry run ruff check .     # lint
```

## CLI

`pmb` 是批次 pipeline 的 CLI 入口,各步皆支援 `--dry-run`:

| 指令 | 階段 | 說明 |
|---|---|---|
| `pmb fetch [--date]` | Phase 0 | 組出當日真實數據快照(`--json` 輸出 JSON) |
| `pmb research [--date] [--dry-run]` | Phase 1/3 | 研究 → 一次產出 brief + script + report(`--dry-run` 用範例、免金鑰) |
| `pmb render [--date] [--module M]` | Phase 2 | 從快照渲染圖表 PNG(8 個固定模組) |
| `pmb assemble [--date] [--dry-run]` | Phase 4 | 配音 + 合成 30s mp4(`--dry-run` 用靜音) |
| `pmb publish [--date] [--approve]` | Phase 5 | 發布(**預設 dry-run**;`--approve` 才上傳 YouTube,固定 private) |
| `pmb run [--date] [--dry-run] [--approve]` | — | 全流程 fetch→research→assemble→gate(`--approve` 才以 private 上傳) |
| `pmb next-session [--json]` | — | 顯示今天是否交易日 + 下一個交易日(=盤前下次啟動) |
| `pmb auth-youtube --client-secrets X` | — | 一次性:取得 YouTube OAuth refresh token(貼進 `.env`) |

典型開發跑法(完全不對外、免 LLM/TTS 金鑰):

```bash
poetry run pmb run --dry-run            # 一鍵跑完,產物落 artifacts/,印出 review gate
poetry run pmb publish                  # 只寫 publish manifest,不上傳(需 --approve 才發)
```

## 部署成雲端 routine

日更研究部署成 **Claude Code 雲端 scheduled routine**(盤前排程,電腦關機也跑)。
routine 貼上 [`prompts/cloud_routine.md`](prompts/cloud_routine.md):它會 `pmb fetch` 取數 →
依 [`prompts/daily_research.md`](prompts/daily_research.md) 做研究產出 brief/script/report/thesis →
`pmb assemble` 合成 → 停在人工 gate。影片放行才 `pmb publish --approve`,報告人工貼上。

## 桌面控台

[`desktop/`](desktop/) 是 Tauri 控台:選交易日看每日製作狀態、按鈕觸發各步驟、檢視講稿/Brief/報告/內嵌影片、即時看執行日誌。跑法:`cd desktop && npm install && npm run tauri dev`。詳見 [`desktop/README.md`](desktop/README.md)。

## 日更營運 SOP

> 頻道:**美股早發車**(類別:教育)。所有產出皆為市場資訊與風險教育、**非投資建議**;上線前先過 GoodFinance 合規。

**一次性設定**
1. `.env` 填 `FRED_API_KEY`(研究若在本機測試另填 `ANTHROPIC_API_KEY`;雲端 routine 用 agent 本身、免金鑰)。
2. YouTube:Google Cloud 建 OAuth 桌面用戶端 → `pmb auth-youtube --client-secrets X` → 三行貼進 `.env`(憑證**只放信任本機/CI、勿放雲端**)。

**每個交易日**
1. **☁️ 研究(雲端 routine)**:盤前自動 `fetch` + 研究 → 產 brief/script/report、更新 thesis(commit / 落 artifacts)。
2. **🧑 gate①(人工審研究)**:用控台或直接看 `artifacts/`,檢查 insight、講稿、thesis、⚠️圖表缺口;要改就編 `prompts/daily_research.md` 或當日 `script_<date>.json`。
3. **💻 合成**:`pmb assemble`(或控台「3 合成」)→ 直式 mp4。
4. **🧑 gate②(人工審影片)**:控台內嵌播放確認。
5. **💻 發布**:`pmb publish --approve`(或控台勾 approve)→ 以 **private** 上傳 → 印出「上傳到頻道」確認是美股早發車 → 自己到 YouTube Studio 補「合成內容揭露(用了 TTS)」、加播放清單、改公開。

**手動介入點**:選題/語氣 → `prompts/daily_research.md`;當日內容 → `artifacts/script_<date>.json` 後重 `assemble`;中長期 → `state/thesis.json`;風格/頻道名/語速/類別 → `pmb/config.py`(或 `.env`)。

**休市**:不帶 `--date` 會自動 skip;`pmb next-session` 看下次啟動日。

## 開發進度

- [x] Phase 0 — 資料層(FRED + yfinance + 衍生指標 + 快照)
- [x] Phase 1 — 研究 prompt + schema(確定性骨架完成;品質 burn-in 進行中)
- [x] Phase 2 — 圖表模組庫(§6.1 全 8 模組)
- [x] Phase 3 — 講稿 + 報告(一次產出 brief/script/report,chart_id 交叉驗證)
- [x] Phase 4 — 配音 + 合成(edge-tts + ffmpeg,30s mp4 + 燒字幕)
- [x] Phase 5 — 發布 + 人工 gate(YouTube 預設 dry-run + orchestrator)
- [x] Phase 6 — 雲端 routine + 文件
- [x] 頻道品牌「美股早發車」+ YouTube metadata(標題/描述/tags/封面/語言)
- [x] 桌面控台(Tauri):狀態儀表板 + 觸發 + 內容檢視 + 即時日誌
