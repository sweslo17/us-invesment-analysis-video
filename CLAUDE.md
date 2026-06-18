# CLAUDE.md — PMB(Pre-Market Macro Brief)專案指令

> 這是給 Claude Code 的專案指令檔。每個 session 開始請先讀本檔與 `premarket-macro-brief-system-plan.md`(本 repo 內,**正式規格,細節以它為準**)。本檔給的是操作方式與鎖定的決策。

---

## 任務

每個交易日盤前,自動研判美股市場(各大指數、總經、市場 regime,槓桿作風險教育素材),產出**一支公開的 30 秒說明影片**(YouTube)與**一份當日研究報告**(發布平台)。受眾是一般大眾,內容以「對最多人最有價值」為準,與任何個人 portfolio 脫鉤。

**開發/執行分工(重要):**
- **本次用 Claude Code 互動式開發**這個 repo(寫 code、測試、跑 dry-run)。
- **日更研究**最終部署成 **Claude Code 雲端 routine**(claude.ai/code/scheduled),電腦關機也跑。
- **確定性 pipeline**(圖表渲染、TTS、合成、上傳)是普通腳本,在 routine 產出 artifacts 後執行,**不放進 agentic session**。

---

## 鐵則(不可違反)

1. **數字走 API,絕不讓 LLM 生成。** 指數點位、漲跌幅、殖利率、VIX、CPI 等一律來自資料層(FRED/yfinance)。研究 prompt 拿到的是資料層產出的真實數據快照,只能引用、不能編造。
2. **研究與機械分離。** 只有「研判 + 文字生成」用 agentic LLM;取數/畫圖/配音/合成/上傳是確定性流程。
3. **兩個 LLM 步合一。** 研究 + brief + 講稿/選圖 + 報告 + thesis 更新,設計成同一個 routine 的一次 run。
4. **為最多人最大價值,與個人 portfolio 脫鉤。** 槓桿走資訊/風險教育,**非可跟單策略**;語氣教育而非建議。
5. **反 AI 腔。** 講稿與報告:自然口語/書面、有個性,**不用「不是…而是」「值得注意的是」等套話**,少清單腔、避免空洞對比。
6. **開發期一律不對外發布。** 影片、報告產出後落到本機 review 資料夾;YouTube 上傳與發文功能要實作,但預設 **dry-run / 需人工放行**,不可自動公開。
7. **不提交任何密鑰。** FRED key、YouTube OAuth、TTS 等用 `.env` + `pydantic-settings`;`.gitignore` 排除。研究 routine 只用 web search,**不掛工作的 Drive/Slack connector**。
8. **每個產出帶「非投資建議」免責**。

---

## 鎖定的技術決策(不要重新討論)

- 語言/套件管理:Python 3.12 + **Poetry**。依賴用 `poetry add`、dev 依賴 `poetry add --group dev`;`pmb` CLI 走 Poetry script entry point(`[tool.poetry.scripts]`,`pmb = "pmb.cli:main"`),以 `poetry run pmb …` 執行;`poetry.lock` 要提交。
- 形態:**批次 pipeline + CLI**(不是常駐服務)。提供 `pmb` CLI:`fetch` / `research` / `render` / `assemble` / `publish` / `run`(全流程)/ 各步皆支援 `--dry-run`。
- Schema:**pydantic v2** 定義 `brief` / `script+chart_spec`;LLM 輸出一律過 schema 驗證,失敗自動重試。
- 資料:`fredapi`(或直接 REST)、`yfinance`、`pandas_market_calendars`。
- 圖表:`matplotlib` + `mplfinance`(模組庫,見規格 §6)。**不用任何 AI 影片/圖像生成。**
- TTS:`edge-tts`(免費、zh-TW、逐字時間戳→字幕);包 retry,留 fallback 介面(OpenAI TTS / ElevenLabs)。
- 影片合成:`ffmpeg`(subprocess)為主,或 `moviepy`;燒字幕用 edge-tts 的 word boundary 對齊。
- 上傳:`google-api-python-client`(YouTube Data API v3,OAuth + refresh token)。
- 研究 LLM:Claude Code 雲端 routine 本身(同一 agent 做研究+寫作);本機開發/測試時用 Anthropic API 跑同一份 prompt。
- 測試:`pytest`;資料層與 schema 要有測試;全流程要有 `--dry-run` 煙霧測試(用 fixture 數據,不打外部)。
- Lint/format:`ruff`。

---

## 專案結構(建立成這樣)

```
pmb/
  cli.py                 # pmb CLI 入口
  config.py              # pydantic-settings,讀 .env
  data/
    fred.py  yfinance.py  calendar.py  derived.py   # 衍生指標:股債相關、已實現波動、廣度
    snapshot.py          # 組出當日真實數據快照(餵研究 + 圖表)
  schemas/
    brief.py  script.py  # pydantic models(見下)
  research/
    runner.py            # 本機跑研究 prompt(開發/測試用);驗證輸出
    dedup.py             # horizon-aware 去重(讀昨日 brief)
    thesis.py            # thesis.json 讀寫
  charts/
    library.py           # 模組庫:每個模組一支 render fn
    select.py            # 驗證 LLM 選的模組+參數,呼叫對應 render
  tts/  edge.py
  video/ assemble.py     # segment→chart 對齊 + 燒字幕 + 配音
  publish/ youtube.py  report.py   # report.py 產 markdown;youtube.py 上傳(預設 dry-run)
  orchestrator.py        # 確定性 pipeline:吃 artifacts → render → assemble → (gate) → publish
prompts/
  daily_research.md      # ★ runtime 研究 prompt(部署到雲端 routine 的內容,草案見下)
artifacts/               # 每日產出:brief.json / script.json / report.md / *.png / *.mp4(gitignore)
state/
  thesis.json
tests/
.env.example
README.md
```

---

## 工作方法(請這樣執行)

- **先確認再動工**:讀完規格後,先用一段話跟我複述你的理解 + Phase 0 的具體計畫,等我說 go 再寫 code。
- **嚴格分階段**:照下面 Phase 0→6,**完成一階段、跑通驗收、給我看,再進下一階段**。不要一次全做。
- **小步提交**:每個有意義的單元一個 commit,訊息清楚。
- **動到不可逆或會對外的動作前要問我**(刪檔、對外發布、寫入帳號設定)。
- 每階段附簡短測試或 dry-run 證明可跑;遇到外部 endpoint(yfinance/edge-tts)要包 retry + 明確錯誤。
- 過程不要自己決定改規格;要改先跟我講。

---

## 分階段建置與驗收

**Phase 0 — 資料層**
- 接 FRED + yfinance(指數期貨、VIX、^TNX、美元、TLT、槓桿載具 UPRO/TQQQ/TMF/SOXL 等)+ 衍生指標(股債相關、已實現波動、廣度)+ NYSE 行事曆。
- 產出 `snapshot.py`:組出當日真實數據快照(dict/JSON)。
- 驗收:`pmb fetch` 印出當日快照;休市日正確 skip;有測試。

**Phase 1 — 研究 prompt + schema(最關鍵)**
- 實作 `schemas/brief.py`、`research/thesis.py`、`research/dedup.py`、`research/runner.py`(本機用 Anthropic API 跑 `prompts/daily_research.md`,輸出過 schema 驗證 + 重試)。
- 把下方「runtime 研究 prompt 草案」寫進 `prompts/daily_research.md`。
- 驗收:`pmb research --dry-run` 用快照產出合法 `brief.json`,含 horizon/confidence/thesis_delta/lead_horizon;去重對昨日 brief 生效。**這階段先純人工審輸出品質,不接後面。**

**Phase 2 — 圖表模組庫**
- 實作 `charts/library.py` 模組(規格 §6.1:index_overnight_grid、yield_curve、vix_regime、rates_trend、stock_bond_corr、breadth、econ_print、leverage_decay)+ `charts/select.py`(驗證 LLM 選的模組/參數,用真實數據渲染)。
- 驗收:給定 chart_spec → 產出對應 PNG;非法模組/參數被擋。

**Phase 3 — 講稿 + 報告(同一次 LLM 輸出)**
- 擴充研究 prompt 與 `schemas/script.py`,讓同一次輸出含:講稿 segments(綁 chart_id)+ charts(選自模組庫)+ report.md。
- 驗收:`pmb research` 一次產出 brief + script(segments/charts)+ report.md;圖文 chart_id 對得上;反 AI 腔與編輯約束有落實(人工看)。

**Phase 4 — 配音 + 合成**
- `tts/edge.py`(配音 + word timing)+ `video/assemble.py`(依 segment.t_start/duration 顯示對應 chart、燒字幕、配音軌)。
- 驗收:`pmb assemble --dry-run` 用 fixture 產出一支 30s mp4,字幕與圖隨旁白切換對齊。

**Phase 5 — 發布 + 人工 gate**
- `publish/report.py`(產 Medium-ready markdown)+ `publish/youtube.py`(上傳,**預設 dry-run**)+ `orchestrator.py`(全流程,產物落 `artifacts/`,送 review channel,等放行)。
- 驗收:`pmb run --dry-run` 跑完整流程不對外;放行機制可運作。

**Phase 6 — 部署成雲端 routine + 文件**
- 把 `prompts/daily_research.md` 整理成可貼進 Claude Code 雲端 routine 的版本;寫 README 說明如何註冊 routine(盤前排程)、如何接 orchestrator、如何放行發布。
- 驗收:文件齊全;我能照著把日更 routine 排起來。

---

## ★ 要產出的 runtime 研究 prompt 草案(寫進 `prompts/daily_research.md`)

> 這是日更雲端 routine 每天執行的內容。輸出語言為繁體中文。

```
你是一個盤前市場研究助理,服務「公開影片 + 研究報告」的一般大眾觀眾。
你的判斷要以「對最廣大、最多投資人最有價值」為準,而不是服務任何特定人的部位。

【鐵則】
- 你會拿到今天的真實數據快照(指數、期貨、VIX、利率、美元、槓桿載具、衍生指標)。所有數字只能引用快照,不可自行編造或估算。
- 槓桿/反向 ETF 一律以「資訊與風險教育」呈現(這種 regime 下它如何表現、為何高風險),不得做成可跟單的策略或建議。
- 與任何個人 portfolio 脫鉤;語氣是教育而非投資建議;不暗示讀者該買賣什麼。
- 文字自然口語/書面、有個性。禁止「不是…而是」「值得注意的是」這類套話,少用清單腔,避免空洞對比。

【流程】
1. 讀 state/thesis.json(當前市場中長期基準情境)。
2. 研究近 12–24 小時(隔夜/盤前)的美股市場:各大指數動向與原因、總經與 Fed/利率/通膨 backdrop、市場 regime(波動、股債相關、廣度)、今日排程催化劑。搜尋要鎖定「相對昨天有什麼變化」,不是泛泛總結現況。
3. 對每一條判斷標記:horizon(ST/MT/LT)、vs_thesis(confirms/challenges/new)、materiality(1–5)、confidence(confirmed/developing/single-print),並寫一句「這對一般投資人代表什麼」。
4. 即使是日更短內容,只要當天出現可能改變中長期趨勢的變化,務必提及。重大但未確認的標 developing,語氣對應 confidence(例:「若延續,可能…」),不要當成既成事實。
5. 與昨天的 brief 去重:短期項目去重;中長期項目當作持續追蹤的 open thread,只在有新進展時再講。不要因為昨天提過就略過長期訊號。
6. 評估今天是否動到中長期 thesis。若有重大且夠確認的變化,更新 thesis(保守,要確認才改基準);否則不動。

【產出】(嚴格照 schema)
- brief.json:見規格 §5.7。
- script:30 秒講稿,切成 segments,每段綁一個 chart_id;依 lead_horizon 浮動配時(平常日短期為主、中長期各一句;regime 日把該中長期項目升級、甚至當 hook)。同時輸出 charts 陣列,模組只能從固定清單挑(index_overnight_grid / yield_curve / vix_regime / rates_trend / stock_bond_corr / breadth / econ_print / leverage_decay),附參數。選圖以「幫最多人理解今天市場」為準。
- report.md:同一份研究的完整版長文,面向一般讀者,結構見規格 §7.1。
- thesis 更新(若有)。

數字一律來自快照。任何不確定就降低 confidence 並在文字中誠實標示。
```

---

## Schema 摘要(`schemas/`)

`brief.py` 與 `script.py` 依規格 §5.7 與 §6.3 實作 pydantic models;`charts[].module` 用 `Literal[...]` 限定為固定模組庫,`segments[].chart_id` 必須對得上 `charts[].id`。LLM 輸出一律 `model_validate`,失敗重試。

---

## 第一個動作

讀完本檔與 `premarket-macro-brief-system-plan.md` 後,用一段話跟我複述理解 + Phase 0 計畫,等我說 go。先不要寫任何 code。
