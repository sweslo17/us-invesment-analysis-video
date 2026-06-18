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
| `pmb fetch` | Phase 0 | 組出當日真實數據快照 |
| `pmb research` | Phase 1/3 | 研究 + brief + 講稿/選圖 + 報告(LLM) |
| `pmb render` | Phase 2 | 依 chart_spec 渲染圖表 |
| `pmb assemble` | Phase 4 | 配音 + 合成影片 |
| `pmb publish` | Phase 5 | 發布(預設 dry-run) |
| `pmb run` | — | 全流程 |

## 開發進度

- [x] Phase 0 — 資料層
- [ ] Phase 1 — 研究 prompt + schema
- [ ] Phase 2 — 圖表模組庫
- [ ] Phase 3 — 講稿 + 報告
- [ ] Phase 4 — 配音 + 合成
- [ ] Phase 5 — 發布 + 人工 gate
- [ ] Phase 6 — 雲端 routine + 文件
