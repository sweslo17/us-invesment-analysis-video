# PMB 日更雲端 routine(貼進 claude.ai/code scheduled routine)

> 排程:**美股交易日盤前**——建議**台北 19:30 平日**(= ET 夏令 07:30 / 冬令 06:30,皆在盤前)。
> 電腦關機也照跑。本機 `pmb autopilot` 設 **19:45** 接手(先生產、後消費;本機端輪詢 90 分,
> 雲端偶爾跑慢也接得住)。
> **拓樸 A**:雲端只做 **取數 + 研究 + commit**(只碰 yahoo/FRED/web search);
> 影片**合成 + 發佈在你本機**跑(`pmb today`)——雲端不需 ffmpeg / 字型 / edge-tts / YouTube OAuth。

---

## 一次性環境設定(在 claude.ai/code 的 environment;部署前必做)

1. **連接 GitHub repo** `sweslo17/us-invesment-analysis-video`,授權 claude.ai 讀寫(才能 clone 與開 PR/push 分支)。
2. **Setup script**(只跑一次、會快取;拓樸 A 不需 ffmpeg/字型):
   ```bash
   command -v poetry >/dev/null || python3 -m pip install poetry
   ```
   ⚠️ 兩個坑,都踩過了:
   - **不要** `pip install --upgrade pip`:雲端 Ubuntu 的 pip 是 debian 套件(無 RECORD 檔),
     pip 無法解除安裝自己,升級必炸(`Cannot uninstall pip 24.0, RECORD file not found`)。
   - **不要在這裡 `poetry install`**:環境建置階段 repo 尚未 checkout(cwd 是空的 home),
     找不到 pyproject.toml。依賴安裝放在「每次執行」第 1 步。
3. **Routine 的 Prompt 欄**建議只貼這一行(每次執行讀 repo 內最新版,改 prompt 免重貼):
   > 你是 repo `sweslo17/us-invesment-analysis-video` 的雲端排程 session。讀取 repo 內的
   > `prompts/cloud_routine.md`,嚴格依其「每次執行,依序做這些」章節執行;其餘章節是給
   > 人類的一次性設定說明,略過。
4. **環境變數**:`FRED_API_KEY=<你的 key>`(明文、低敏感、可輪替)。
   **不要放** YouTube OAuth、也不需 `ANTHROPIC_API_KEY`(研究用 routine 自帶的 web search,免 key)。
5. **網路出口改 Custom,allowlist**(否則 `pmb fetch` 失敗):
   - `query1.finance.yahoo.com`、`query2.finance.yahoo.com`、`*.finance.yahoo.com`、`fc.yahoo.com`
   - `api.stlouisfed.org`
   - 勾「包含常見套件管理器預設清單」(pip/apt);web search 內建,無需額外網域。
   - (**不需** `*.bing.com`——本 routine 不配音。)

---

## 每次執行,依序做這些

1. **裝依賴 + 取數**(session 是新容器,repo 這時才在):
   ```bash
   poetry install --quiet    # 每次都要;setup 階段沒有 repo 裝不了
   poetry run pmb fetch
   ```
   - 若輸出「今天非 NYSE 交易日,skip」→ 休市,**直接結束、不要 commit**。
   - 否則它會寫 `artifacts/snapshot_<date>.json`。
2. **讀** `artifacts/snapshot_<date>.json`(真實數字)與 `state/thesis.json`(中長期基準)。
3. **研究(AI,web search)**:嚴格依下方「研究任務」(= `prompts/daily_research.md` 全文)。
   ⚠️ 搜尋窗 = **自上一交易日收盤到今天盤前的整段**(假期/週末後第一個交易日要涵蓋整段休市期間,
   不只前一日;重大事件影響常跨多日,仍在發酵的也要納入)——見快照 `previous_session_date`。
   盤前框架(上一交易日收盤回顧 + 今日盤前期貨 + 今日催化劑)、反 AI 腔、槓桿走一般倍數風險教育、
   與 portfolio 脫鉤、非投資建議。**所有數字只能引用快照,不可編造。**
4. **寫產物並過 schema**(`pmb/schemas/`):
   - `artifacts/brief_<date>.json`(Brief §5.7)
   - `artifacts/script_<date>.json`(Script:每段 `chart_id` 對得上 `charts[].id`;模組限 `charts/select.py` 的固定清單)
   - `artifacts/report_<date>.md`(§7.1)
   - 重大且**夠確認**才保守更新 `state/thesis.json`;否則不動。
   - 驗證:`poetry run python -c "from pmb.schemas.brief import Brief; from pathlib import Path; Brief.model_validate_json(Path('artifacts/brief_<date>.json').read_text())"`(script 同理);不過就修正重寫。
5. **commit 並直接 push 到 `main`**(審查在本機做,不開 PR;`artifacts/` 被 gitignore,text 產物用 `-f`):
   ```bash
   D=<date>
   git add -f artifacts/snapshot_$D.json artifacts/brief_$D.json artifacts/script_$D.json artifacts/report_$D.md
   git add state/thesis.json
   git commit -m "research: $D 盤前研究產出"
   git pull --rebase origin main    # 先同步本機可能的修正
   git push origin main
   ```
   ⚠️ **snapshot 一定要一起 commit**:本機合成直接沿用這份快照,圖表數字才與講稿一致(本機重抓會有時間差)。
   若 `push origin main` 被拒(帳號未開 unrestricted branch pushes),**改推 fallback 分支**:
   `git push origin HEAD:claude/research-$D` ——本機 `pmb auto` 會自動掃描 `claude/*` 分支、
   把研究併回 main 並回推;接力不會斷,不需人工。
6. **絕不執行 `pmb assemble` / `pmb publish`**(那在你本機跑)。任一步失敗 → 清楚說明,不要硬產半成品。

---

## 本機後續(不在雲端)

**全自動(預設)**:本機 launchd 排程(`pmb autopilot install --time 19:45`)每個平日傍晚
自動跑 `pmb auto`:git pull 輪詢等本 routine 的 commit → 合成 → 上傳 YouTube(private,
API 已自動帶合成內容揭露/播放清單/語言)→ 桌面通知。**人工只剩:到 YouTube Studio 看片、
改『公開』**(鐵則:絕不自動公開)。

**手動(備援)**:`git pull` → 控台檢視講稿/Brief/報告(要改就本機改、「⬆ 提交+推送」回推
main)→ 控台「🚀 一鍵完成今日作業」或 `poetry run pmb today` → Studio 改公開。

---

## 鐵則(不可違反)

- 數字走 API、LLM 只引用,不編造。
- 槓桿走一般性「開幾倍槓桿」概念(融資/期貨/選擇權/槓桿型 ETF 都適用),不特指商品、不點名代號、零買賣建議。
- 反 AI 腔(禁「不是…而是」「值得注意的是」),與任何 portfolio 脫鉤,語氣教育而非建議。
- **雲端不自動發布、不做合成**;只用 web search,不掛工作的 Drive/Slack connector。
- 任何步驟失敗 → 在結果通知,不要硬產。每個產出帶「非投資建議」免責。

---

## 研究任務(= prompts/daily_research.md)

> routine 直接讀 `prompts/daily_research.md`;內容即該檔全文。
