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
| `pmb today [--date] [--no-upload]` | — | 一鍵完成今日**本機**作業:合成→發佈(前置缺則中止);供控台一鍵 / cron |
| `pmb auto [--wait-minutes N] [--research-local] [--no-pull] [--no-upload]` | — | **每日全自動**:等雲端研究(含 `claude/*` 分支退路)→等不到改本機研究→合成→上傳 private→通知;冪等、休市 skip |
| `pmb research-local [--date] [--no-push]` | — | 本機研究:headless Claude Code(`claude -p`,本機登入免 key)跑研究→驗證→commit+push main |
| `pmb autopilot install\|uninstall\|status [--time HH:MM]` | — | 管理 macOS launchd 排程:平日定時自動跑 `pmb auto` |
| `pmb next-session [--json]` | — | 顯示今天是否交易日 + 下一個交易日(=盤前下次啟動) |
| `pmb research-prompt [--date] [--out]` | — | 輸出今日研究 prompt(模板+快照)貼進 Claude Code 做研究 |
| `pmb auth-youtube --client-secrets X` | — | 一次性:取得 YouTube OAuth refresh token(貼進 `.env`) |

> **研究這步是 Claude Code 做的,不走 API key**:雲端 routine 自動跑,或本機把 `pmb research-prompt` 的輸出貼進 Claude Code。`pmb research`(API 路徑)只供自動化測試/選配。
>
> **dry-run 的意義**:正常營運**唯一的 gate 是「上不上傳」**(`publish` / `run` 加 `--approve` 才上傳,且固定 private)。取數/合成都是免費、直接跑真的;`research`/`assemble` 的 `--dry-run`(範例/靜音)只給自動化測試用。

典型開發跑法(完全不對外、免 LLM/TTS 金鑰):

```bash
poetry run pmb run --dry-run            # 一鍵跑完,產物落 artifacts/,印出 review gate
poetry run pmb publish                  # 只寫 publish manifest,不上傳(需 --approve 才發)
```

## 部署成雲端 routine

日更研究部署成 **Claude Code 雲端 scheduled routine**(盤前排程,電腦關機也跑)。
routine 貼上 [`prompts/cloud_routine.md`](prompts/cloud_routine.md):它會 `pmb fetch` 取數 →
依 [`prompts/daily_research.md`](prompts/daily_research.md) 做研究 → 把 snapshot/brief/script/report
commit 上 main(**雲端不合成、不發布**)。本機由 `pmb auto`(launchd)接手合成與上傳(private),
人工只到 Studio 改公開;報告人工貼上。

## 桌面控台

[`desktop/`](desktop/) 是 Tauri 控台:選交易日看每日製作狀態、按鈕觸發各步驟、檢視講稿/Brief/報告/內嵌影片、即時看執行日誌。跑法:`cd desktop && npm install && npm run tauri dev`。詳見 [`desktop/README.md`](desktop/README.md)。

## 日更營運 SOP

> 頻道:**美股早發車**(類別:教育)。所有產出皆為市場資訊與風險教育、**非投資建議**;上線前先過 GoodFinance 合規。

每步標明誰做:**☁️ Claude Code**(研究)/ **💻 本機**(取數、合成、發布)。控台以「步驟」為主導:本機步驟可點,研究步顯示 prompt 供貼進 Claude Code。

**一次性設定**
1. `.env` 填 `FRED_API_KEY`。**研究不需 API key**(Claude Code 做)。
2. YouTube:Google Cloud 建 OAuth 桌面用戶端 → `pmb auth-youtube --client-secrets X` → 三行貼進 `.env`(憑證**只放信任本機/CI、勿放雲端**)。

**每個交易日 — 全自動模式(預設,人工只剩 1 步)**

一次性 `pmb autopilot install --time 19:45` 後,每個平日傍晚本機自動:

1. **☁️ 雲端 routine**(美東盤前)自動 fetch + 研究,把 snapshot/brief/script/report commit 上 main。
2. **💻 `pmb auto`**(launchd 觸發)`git pull` 輪詢等產物 → 合成(深色圖表 + 卡拉OK字幕 + BGM 母帶)→ 上傳 YouTube(**private**,API 自動帶:合成內容揭露、播放清單、語言、非兒童)→ 桌面通知附 Studio 連結。
3. **🧑 你**:點通知進 YouTube Studio 看片 → 改『**公開**』。完成。

(休市自動 skip;當天已上傳過不會重跑。報告仍為人工貼上。)

**研究來源三層 fallback**(`pmb auto` 內建,全自動):
1. 雲端 routine push main → 直接用。
2. 雲端推不上 main(權限)→ 它退推 `claude/*` 分支 → 本機自動併回 main。
3. 雲端整個沒跑(預設等 30 分)→ **本機 headless Claude Code**(`claude -p`,用本機登入)跑同一份研究 prompt → 過 schema 驗證 → 自動 commit+push main。雲端 routine 從必經之路變成加速器。

**每個交易日 — 手動模式(備援/想逐步看)**
1. **💻 取數**:`pmb fetch`(或控台「取數」);雲端已 commit snapshot 則 `git pull` 即可。
2. **☁️ 研究(Claude Code)**:雲端 routine 盤前自動跑;或本機「複製研究 Prompt」貼進 Claude Code。
3. **🧑 審研究 + 💻 合成**:控台看講稿/Brief/報告(+⚠️圖表缺口);OK 就按「合成」。
4. **🧑 審影片 + 💻 發布**:控台內嵌看片;OK 按「上傳 YouTube(private)」→ 到 Studio 改公開(揭露/播放清單/語言已由 API 設定)。

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
- [x] 影片品質 v2 — 深色圖表主題、逐字卡拉OK字幕(分頁不蓋圖)、Ken Burns、進度條、BGM+ducking、loudnorm -14 LUFS
- [x] 全自動化 — `pmb auto` + `pmb autopilot`(launchd);上傳自動帶合成內容揭露/播放清單/語言,人工只剩改公開
- [x] 桌面控台(Tauri):狀態儀表板 + 觸發 + 內容檢視 + 即時日誌
