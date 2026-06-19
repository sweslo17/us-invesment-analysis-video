# PMB 日更雲端 routine(貼進 Claude Code 雲端 scheduled routine)

> 這份是要貼進 **Claude Code 雲端排程 routine**(claude.ai/code/scheduled)的指令。
> 排程:**美股交易日盤前(ET 07:00–08:00 ≈ 台灣傍晚/晚上)**。電腦關機也照跑。
> 研究是唯一的 AI 步驟;取數/畫圖/配音/合成/發布都是 `pmb` 確定性指令(shell 執行,不靠 LLM 推理)。

---

## 雲端環境前置需求(部署前必做,否則跑不完)

雲端 routine 跑在 Anthropic 的 Ubuntu 24.04 沙箱,**預設網路是 Trusted(擋未列名網域)、無 ffmpeg、無 CJK 字型**。建立 routine 的 environment 時要設定:

1. **網路出口改 Custom,allowlist 這些網域**(否則 fetch / 配音失敗):
   - `query1.finance.yahoo.com`、`query2.finance.yahoo.com`、`fc.yahoo.com`、`*.finance.yahoo.com`(yfinance)
   - `api.stlouisfed.org`(FRED)
   - `speech.platform.bing.com`、`*.bing.com`(edge-tts 配音)
   - 勾「包含常見套件管理器預設清單」(pip/apt)
2. **setup script(只跑一次、會快取)裝 ffmpeg + CJK 字型**:
   ```bash
   apt-get update && apt-get install -y ffmpeg fonts-noto-cjk
   ```
   裝了 `fonts-noto-cjk` 後,圖表(matplotlib)與字幕(libass)的中文才不會變豆腐方塊;`video_font` 預設就是 `Noto Sans CJK TC`。
3. **環境變數**:`FRED_API_KEY=...`(雲端環境變數是明文,只放這種可輪替的低敏感 key)。研究用 web search,**不需要 ANTHROPIC_API_KEY**。**YouTube OAuth 不要放雲端**(見下方發布)。
4. **跨日狀態**:routine 每次從 repo 預設分支重新 clone、`artifacts/` 不保留。要讓 thesis 與去重跨日生效,routine 結束要把 `state/thesis.json`(+ 當日 brief)**commit/push**,經人工 gate 合併回主分支,隔天才讀得到。

> **建議的分工(風險最低)**:雲端 routine 只做 **fetch + 研究 + commit 產物**(只需 yahoo/fred/web search,完全不碰 ffmpeg/edge-tts/字型/OAuth);**影片合成 + 發布在你信任的機器/CI** 上 `pmb assemble` + `pmb publish --approve`(影片可由 committed 的 script+snapshot 確定性重建,不必經 git 傳 mp4)。

---

## 每次執行,依序做這些

1. **取數(確定性)**:在 repo 根目錄執行 `poetry run pmb fetch`。
   - 若輸出「今天非 NYSE 交易日,skip」→ 今天休市,**直接結束**。
   - 否則它會把當日真實數據快照寫到 `artifacts/snapshot_<date>.json`。

2. **讀** `artifacts/snapshot_<date>.json`(真實數字)與 `state/thesis.json`(中長期基準情境)。

3. **研究(AI)**:依「研究任務」(下方,即 `prompts/daily_research.md` 全文)做研判:
   web search 近 12–24 小時、標 horizon/vs_thesis/materiality/confidence、寫「對一般人代表什麼」。
   **所有數字只能引用快照,不可編造。**

4. **寫出產物**(schema 見 `pmb/schemas/`):
   - `artifacts/brief_<date>.json` — 過 `Brief` schema(§5.7)。
   - `artifacts/report_<date>.md` — 面向一般讀者的長文(§7.1)。
   - 講稿:可直接寫 `artifacts/script_<date>.json`(過 `Script` schema:每段 `chart_id` 對得上
     `charts[].id`;模組只能用 8 個固定模組);或交給下一步的 `pmb research` 由 brief 確定性產生。
   - thesis 若有**重大且夠確認**的變化 → 保守更新 `state/thesis.json`;否則不動。
   > 也可以直接 `poetry run pmb research`(本機開發模式會用 Anthropic API 跑同一份 prompt,
   > 或在 routine 內由你這個 agent 直接產出)一次寫出 brief + script + report。

5. **合成(確定性)**:`poetry run pmb assemble --date <date>`(edge-tts 配音 + ffmpeg 合成)。
   先驗可用 `--dry-run`(靜音、不打 edge-tts)。

6. **停在人工 gate。不要自動發布。** 執行 `poetry run pmb run --dry-run` 會跑完整流程並產出
   `artifacts/review_<date>.json`,列出所有產物等人工審。

7. **放行(operator 手動)**:影片 → `poetry run pmb publish --approve`(需 YouTube OAuth 憑證);
   報告 → 人工貼上 Medium,或改發 Hashnode/Ghost。

---

## 鐵則(不可違反)

- 數字走 API、LLM 只引用,不編造。
- 槓桿走「全市場/各指數最適槓桿教育」(波動目標 + 波動耗損),講的是**一般性的「開幾倍槓桿」概念**(融資/期貨/選擇權/槓桿型 ETF 都適用),**不特指任何商品、不點名代號、零買賣建議**。
- 反 AI 腔(禁「不是…而是」「值得注意的是」),與任何 portfolio 脫鉤,語氣教育而非建議。
- **不自動對外發布**;只用 web search,不掛工作的 Drive/Slack connector。
- 任何步驟失敗 → 通知 operator,不要硬發。
- 每個產出帶「非投資建議」免責。

---

## 研究任務(= prompts/daily_research.md)

> routine 可直接讀 `prompts/daily_research.md`;內容即該檔全文。
