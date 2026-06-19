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
| `pmb publish [--date] [--approve]` | Phase 5 | 發布(**預設 dry-run**;`--approve` 才上傳 YouTube) |
| `pmb run [--date] [--dry-run]` | — | 全流程 fetch→research→assemble→人工 gate(不自動發布) |

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

## 開發進度

- [x] Phase 0 — 資料層(FRED + yfinance + 衍生指標 + 快照)
- [x] Phase 1 — 研究 prompt + schema(確定性骨架完成;品質 burn-in 進行中)
- [x] Phase 2 — 圖表模組庫(§6.1 全 8 模組)
- [x] Phase 3 — 講稿 + 報告(一次產出 brief/script/report,chart_id 交叉驗證)
- [x] Phase 4 — 配音 + 合成(edge-tts + ffmpeg,30s mp4 + 燒字幕)
- [x] Phase 5 — 發布 + 人工 gate(YouTube 預設 dry-run + orchestrator)
- [x] Phase 6 — 雲端 routine + 文件
