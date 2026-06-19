# PMB 日更雲端 routine(貼進 Claude Code 雲端 scheduled routine)

> 這份是要貼進 **Claude Code 雲端排程 routine**(claude.ai/code/scheduled)的指令。
> 排程:**美股交易日盤前(ET 07:00–08:00 ≈ 台灣傍晚/晚上)**。電腦關機也照跑。
> 研究是唯一的 AI 步驟;取數/畫圖/配音/合成/發布都是 `pmb` 確定性指令(shell 執行,不靠 LLM 推理)。

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
- 槓桿走「全市場/各指數最適槓桿教育」(波動目標 + 波動耗損),**與任何 ETF 商品脫鉤、不點名代號、零買賣建議**。
- 反 AI 腔(禁「不是…而是」「值得注意的是」),與任何 portfolio 脫鉤,語氣教育而非建議。
- **不自動對外發布**;只用 web search,不掛工作的 Drive/Slack connector。
- 任何步驟失敗 → 通知 operator,不要硬發。
- 每個產出帶「非投資建議」免責。

---

## 研究任務(= prompts/daily_research.md)

> routine 可直接讀 `prompts/daily_research.md`;內容即該檔全文。
