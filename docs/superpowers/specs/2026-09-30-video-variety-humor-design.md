# 影片 v4:多變化段型 + 頻道人設梗 — 設計規格

- 日期:2026-09-30
- 分支:`feat/video-variety`(worktree `.worktrees/video-variety`)
- 狀態:待使用者審閱
- 相關:`premarket-macro-brief-system-plan.md`(正式規格)、v3 視覺定案(Shorts 安全區版面)

---

## 1. 背景與目標

### 1.1 使用者回饋
影片「像套版」、「不夠有梗」。希望內容更豐富多變,並有固定的幽默人設。

### 1.2 診斷(2026-09-21 ~ 09-30 共 8 支)
- 8/8 骨架相同:開場字卡 → `overnight_vs_close` → 2–3 張圖 → 名詞小教室 → 名人金句卡。
- 8/8 開場 kicker 都是「今日盤前」;8/8 第一張圖都是 `overnight_vs_close`。
- 梗只有一種(片尾「○○○ 不知道有沒有說過」),固定位置、固定格式。
- 畫面只有兩種:同版面的圖表段、紅色字卡。
- 根因在 prompt:`prompts/daily_research.md` 明文寫死「6–7 段:hook → 3–4 圖 → 名詞小教室
  → 對句卡」,梗只寫「適度加」,模型每天走最安全的同一條路。

### 1.3 觀看數(YouTube Data API,2026-09-30 查)
| 期間 | 版本 | 每支觀看中位數 |
|---|---|---|
| 6/23–8/3 | ~2.5 分鐘 | ~577 |
| 8/4–9/4 | ~2.5 分鐘 | ~146 |
| 9/8–9/28 | 75 秒短版 + v3 視覺 | ~290 |

按讚多為個位數,留言幾乎全 0。

### 1.4 使用者已定案的決策
- 梗的風格:**鄉民網路梗 + 冷面反差**(混成固定人設)。
- 深度:**講稿 + 新畫面種類**(含雙聲對話配音);逐字高亮/圖表生長動畫不在本期。
- 保留的品牌記憶點:**片尾名人金句、固定開場口號、固定收尾口號**。名詞小教室改為「有合適術語才出」。
- 多變機制:**積木自由組合 + 反重複檢查**(方案 B)。

### 1.5 成功標準
1. 任連續 5 個交易日,段型序列(只看種類)兩兩不同;每支至少 1 段新段型;hook 後第一段與前一天不同。
2. 每支 `gags` ≥ 2(不含金句)。
3. **不因任何新規則少出一天的片**:所有風格類規則都是軟規則(見 §5.4)。
4. 成片長度維持 65–80 秒(vo 預算 330–410 字、硬上限 520;系統插入的開場口號與收尾口號約佔 6 秒,2026-10-01 彩排後下修)。
5. 觀察指標(非驗收):上線後兩週的每支觀看中位數與按讚/留言,對比 9/8–9/28 基準 ~290。

---

## 2. 範圍

**本期要做:**
- 4 種新段型:`dialogue`(對話框)、`split`(好壞消息)、`bignum`(全屏大數字)、`recap`(對帳)。
- Script schema 改為以 `kind` 區分的 discriminated union(舊檔自動推斷)。
- 合成端拆出段型註冊(`pmb/video/segments/`)。
- 雙聲配音(A/B 角 + 旁白)、「……」停頓機制。
- 系統自動插入:開場口號轉場(含程序化音效)、收尾口號。
- 反重複驗證器 + prompt 注入「最近 5 天」回顧塊。
- prompt 改寫:拿掉寫死的骨架,新增「頻道人設」章節與梗的護欄。
- `pmb validate-research` 自我檢查指令(給研究 agent 在同一次執行內自修)。
- 封面 `cover_spec` 支援從新段型取大數字。

**本期不做(第二期或另案):**
- 念到某字時圖表高亮、折線/長條生長動畫、圖表段 stat 的數字跳動、每段轉場音效。
- 新增圖表模組、付費 TTS、YouTube Analytics 串接、report.md 格式變動。

---

## 3. 段型設計

### 3.1 共通
- 每段有 `kind`。基底欄位:`vo: str = ""`、`t_start: float = 0`、`duration: float = 0`
  (`t_start/duration` 為舊欄位,時間軸一向以實測配音長度為準,改為選填)。
- 每種段型提供 `spoken_text`(實際念出的字):`dialogue` = 各句 `text` 串接 + `vo`;其餘 = `vo`。
  字數預算 `check_vo_budget` 改用 `spoken_text` 加總。
- 版面一律遵守 v3 安全區:底部 400px、右側 170px 不放文字;可見區底緣 y=1520。
- 新段型畫面 = **純畫布色底圖 + ASS 疊層**(與現行字卡同做法),各元素才能按時間出現。
  色塊(泡泡、面板)用 ASS 繪圖指令(`\p1`)畫圓角框;✓/✗/〰 也用繪圖畫,不依賴字型字符。
- 角標(頻道 · M/D)每段照疊。
- 以下座標為設計值,實作以抽幀驗證微調。

### 3.2 既有段型(行為不變)
| kind | 欄位 | 說明 |
|---|---|---|
| `chart` | `chart_id`、`title?`、`stat?`、`stat_label?`、`vo` | 現行圖表段 |
| `card` | `headline`、`tag?`、`vo` | hook、名詞小教室(`tag="名詞小教室"`)、金句(`tag` 以「不知道有沒有說過」結尾)共用 |

### 3.3 `dialogue` 對話框
- 欄位:`title?`(≤10 字,頂部)、`lines: list[DialogueLine]`(2–4 句)、`vo?`(泡泡講完後的旁白解說,選填)。
- `DialogueLine`:`speaker`(≤6 字)、`voice: Literal["a", "b"]`、`text`(≤16 字)。
- schema 硬規則:至少 2 個不同 `speaker`;同一 `speaker` 全段只能用同一個 `voice`。
- 角色只能是**機構或市場擬人**(Fed、債市、油價、VIX、散戶、華爾街…),不得是真實人物(prompt 規定)。
- 版面:4 個固定槽位,槽頂 y ≈ 300 / 530 / 760 / 990,每槽約 230px(角色名 40px + 泡泡)。
  A 角靠左(x 起點 70)、B 角靠右(泡泡右緣 ≤ 870);泡泡字 60px、最寬 720px(每行約 12 字、最多 2 行)。
  配色:A 藍 `#185FA5`、B 琥珀 `#854F0B`,角色名用同色系淺色。
- 時間:第 k 句的泡泡在該句配音開始時彈出(沿用 `_POP_IN`),之後留到段尾。
- 字幕:泡泡句不跑底部字幕(泡泡就是字);`vo` 旁白部分照常跑卡拉OK字幕。

### 3.4 `split` 好壞消息
- 欄位:`title?`、`top: Panel`、`bottom: Panel`、`vo`。
- `Panel`:`label`(≤6 字,如「好消息」「Fed 說」「美股」)、`text`(≤10 字)、`stat?`(≤7 字元)、
  `tone: Literal["good", "bad", "neutral"]`(綠 / 紅 / 藍底)。
- 版面:上格 y ≈ 290–760、下格 y ≈ 800–1270,x 60–890;label 48px、text 96px(最多 2 行)、stat 110px 金色。
- 時間:上格段首出現;下格在 `vo` **第 2 句**開始時出現。`vo` 只有 1 句時(軟規則會擋)退回段長 50% 處出現。
- 字幕照常跑。

### 3.5 `bignum` 全屏大數字
- 欄位:`value`(≤8 字元,如 `5.26%`、`+16.2萬`)、`label`(≤12 字)、`context?`(≤16 字)、`vo`。
- 版面:label y ≈ 560(52px)、value 置中 y ≈ 820、context y ≈ 1060(60px)。
  value 字級 260px,寬度超過 760px 時自動縮小到剛好放得下。
- 動態:value 從 0 跳到目標值,0.2s 起跑、歷時 0.6s,每幀一個 ASS 事件,保留原格式(正負號、小數位、單位)。
  解析不了數字時直接 pop-in 顯示並記 WARNING。
- 字幕照常跑。

### 3.6 `recap` 對帳
- 欄位:`title?`(預設「昨天說要看的」)、`rows: list[RecapRow]`(1–3 列)、`vo`。
- `RecapRow`:`ask`(≤14 字,昨天說要看的事)、`result`(≤12 字)、`mark: Literal["yes", "no", "mixed"]`
  (✓ 發生/符合預期、✗ 沒發生/不如預期、〰 好壞參半/未定)。
- 資料來源:prompt 已附昨日 brief(含 `catalysts`);prompt 指示只在昨天有明確「今天要看」的事時才用。
- 版面:列頂 y ≈ 330 起,每列約 250px;ask 44px 灰、result 72px 白,mark 圖示 72px 在 result 左側。
- 時間:第 k 列在 `vo` 第 k 句開始時出現;句數少於列數時,剩餘列平均分布在段內。
- 字幕照常跑。

### 3.7 系統自動插入(不在 Script 裡,模型不用寫)
**開場口號轉場(sting)**
- 位置:第 0 段(hook)之後。長度 = max(0.15s 前導 + 口號配音長 + 0.35s 段尾, 1.2s)。
- 畫面:畫布色底 + 頻道字樣(金色 120px)+ 口號 pop-in;不跑字幕。
- 聲音:音效在 t=0,口號旁白在 t≈0.15s。音效由新的 `pmb/audio/sfx.py` 程序化生成
  (兩聲短喇叭「叭叭」+ 短促 whoosh,約 0.5s);`assets/sfx/` 下有 `sting.*` 音檔就改用它。
- 設定:沿用現有(目前未被使用的)`slogan_intro`,預設改為「美股早發車,發車!」;新增 `sting_enable: bool = True`。
- 進度條與全片時間軸都算入 sting。

**收尾口號**
- 沿用現有 `slogan_outro`,預設改為「以上非投資建議,明天盤前見。」。
- 由合成端接在最後一段的最後一句之後(旁白聲)。若最後一段 `vo` 已以同義句結尾
  (去標點後含「非投資建議」且含「盤前見」),不重複接。
- 片尾 CTA 疊層規則不變。

### 3.8 「……」停頓
- 斷句時「……」(或「…」)視為句末。該句配音後的間隔改為 0.5s(一般句間 0.18s)。
- 送進 TTS 的文字去掉「……」;字幕保留。
- 用途:冷面反差梗的 punchline 前停一拍。

---

## 4. 配音

- `SynthFn` 簽名改為 `(text, out_path, planned_duration, voice_key)`,`voice_key: Literal["narrator", "a", "b"]`。
- 設定:`tts_voice`(旁白,預設不變 HsiaoChen)、新增 `tts_voice_a`(預設 `zh-TW-YunJheNeural`)、
  `tts_voice_b`(預設 `zh-TW-HsiaoYuNeural`);`tts_rate`/`tts_pitch` 三個聲線共用。
- dry-run 的 `silent_synth` 忽略 `voice_key`。
- 每種段型的 renderer 回傳「要念的句子計畫」`list[Utterance]`(`text`、`voice_key`、`gap_after`),
  由 `assemble` 統一合成與量測;時間軸與 ASS 以實測長度計算。

---

## 5. 反重複與驗證

### 5.1 最近 5 天回顧塊(注入 prompt)
`build_research_prompt` 新增一塊「=== 最近 5 個交易日的影片(別重複骨架與梗)===」,
由程式從 `artifacts/script_<date>.json` 整理,每天一列:
- 段型序列(含圖表模組),例:`card → chart:overnight_vs_close → dialogue → chart:rates_trend → card`
- hook 句與 kicker、金句名人與句子、`gags`、名詞小教室術語(有的話)

另附「近 20 個交易日用過的名詞小教室術語」清單。讀不到或解析失敗的舊檔跳過並記 WARNING。

### 5.2 `gags` 欄位
`Script.gags: list[str] = []`:模型自報當天用了哪些梗(每個一句話描述)。供回顧塊避免重複、做 callback。

### 5.3 規則(新模組 `pmb/research/variety.py`)
| # | 規則 | 類別 |
|---|---|---|
| S1 | 第 0 段是 `card`(hook);最後一段是 `card` 且 `tag` 以「不知道有沒有說過」結尾;`chart` ≥ 2 段 | 軟 |
| S2 | 段型序列(只看 kind)≠ 前 3 個交易日任一天 | 軟 |
| S3 | 第 1 段(hook 後第一段)的 (kind, 模組) ≠ 昨天的 | 軟 |
| S4 | 至少 1 段新段型,且新段型集合 ≠ 昨天的集合 | 軟 |
| S5 | 金句名人 ≠ 昨天;名詞小教室術語不在近 20 個交易日內 | 軟 |
| S6 | hook 的 kicker(`tag`)≠ 昨天 | 軟 |
| S7 | `len(gags) ≥ 2` | 軟 |
| L1 | 各欄位字數上限(§3) | 軟 |
| N1 | 畫面上的數字(`chart.stat`、`bignum.value`、`split` 的 `stat`、`recap.result` 內數字)的數字核心必須出現在該段 `spoken_text` 裡(數字核心 = 去掉正負號、千分位逗號與單位後的數字字串,如 `5.26%`→`5.26`、`+16.2萬`→`16.2`) | 軟 |
| H* | kind 合法、必填欄位齊、數量範圍(對話 2–4 句、對帳 1–3 列)、對話角色/聲線一致、chart_id 綁定 | 硬(schema) |

「前 N 天」以 artifacts 裡日期早於今天、存在的 script 檔為準(= 交易日)。沒有歷史時相關規則自動通過。
每條違規都產生可據以修改的中文錯誤訊息(指出哪一段、改成什麼方向)。

### 5.4 硬規則與軟規則
- **硬(schema)**:不過就不能出片 → 重試。只放結構性檢查。
- **軟**:字數預算(現有)+ S1–S7 + L1 + N1。重試時帶給模型修;**最後一次仍不過,照樣出片**
  (沿用現行 `include_budget=False` 的邏輯,擴充為「只看硬錯」),並把軟錯記 WARNING 到 autopilot.log。
- renderer 一律防禦:文字過長時換行/縮字級,不得因內容讓合成崩潰。

### 5.5 自我檢查指令
- 新增 `pmb validate-research [--date YYYY-MM-DD]`:跑 `validate_research_artifacts` 全部(硬 + 軟),
  逐條印出,有錯 exit 1。
- prompt 指示研究 agent 寫完檔後**先跑這個指令、有錯就在同一次執行內修好**
  (headless 已允許 `Bash(poetry run:*)`)。每次重試是一次完整 headless 研究(約 17 分鐘),
  盡量在第一次就過。取代 prompt 裡現有的「python 一行數字數」指示。

---

## 6. prompt 改寫(`prompts/daily_research.md`)

**刪除:** 寫死的「6–7 段:開場 hook 卡 → 3–4 個圖表段 → 1 張名詞小教室卡 → 片尾對句卡」;
「每天一格名詞小教室」;要模型自己寫「以上非投資建議,明天盤前見」。

**新增 / 改寫:**
1. **段型清單**:6 種 kind 的用途、欄位與字數上限、何時適合用(例:對立局面 → dialogue / split;
   單一驚人數字 → bignum;昨天有明確待觀察事件 → recap)。
2. **結構底線**(對應 S1):hook 開場、金句收尾、至少 2 張圖;其餘自由排列,並說明回顧塊的用途與 S2–S6。
3. **格式靈感(不強制)**:對決日(整支圍繞兩方對立)、一個數字(整支圍繞一個數字)、
   今晚大考(催化劑日)、對帳日(對帳開場)、平常日。
4. **頻道人設章節**:
   - 一句話:嘴有點壞但很懂市場的老朋友,用鄉民語感講總經,擅長一本正經講幹話。
   - 鄉民梗寫法:對話體、長青流行語、推文體;優先長青梗(模型對最新流行語不熟,追新容易用錯)。
   - 冷面反差寫法:好消息/壞消息、一本正經的冷知識對照、先鋪陳再短句打臉;punchline 前一句用「……」。
   - 配額:全片至少 2 個梗、1 個在前 15 秒(hook 可以就是梗);`gags` 如實列出。
   - `title_hook` 也可帶人設口吻,但仍須具體名詞/數字、不 clickbait。
5. **梗的護欄**:
   1. 不拿傷亡、災難、戰爭受害者開玩笑;戰爭類新聞只吐槽市場反應與數字。
   2. 不人身攻擊、不選邊站政治;吐槽市場、指標、機構的「行為」。
   3. 不用暗示進出場的梗:梭哈、歐印、抄底、上車(頻道名「早發車」易順口帶到,特別注意);
      「住套房」「韭菜」只能自嘲,不嘲笑觀眾。
   4. 梗要扣著當天數字或機制,拿掉梗資訊量不能變少。
   5. 對話角色不得是真實人物;對機構立場的轉述要忠實。
   6. 反 AI 腔鐵則照舊。
6. 金句卡旁白只寫金句本身(收尾口號由系統接)。
7. 完成前執行 `poetry run pmb validate-research --date <date>`(§5.5)。

所有既有鐵則(盤前時序、數字只引用快照、web search 必做、槓桿教育、非投資建議)一字不動保留。

---

## 7. 程式結構變動

```
pmb/schemas/script.py          # Segment → kind union;ChartSegment/CardSegment/DialogueSegment/
                               # SplitSegment/BignumSegment/RecapSegment;spoken_text;gags;舊檔推斷
pmb/video/segments/
  __init__.py
  base.py                      # SegmentRenderer 介面:utterances(seg) / background(...) / ass_events(...)
  registry.py                  # kind → renderer
  chart.py  card.py            # 自 assemble.py 搬出,行為不變
  dialogue.py  split.py  bignum.py  recap.py
  sting.py                     # 開場口號轉場
pmb/video/assemble.py          # 只留時間軸、ffmpeg clip、串接、母帶、共用 ASS 樣式;逐句 gap
pmb/audio/sfx.py               # 程序化 sting 音效 + assets/sfx 覆寫
pmb/research/variety.py        # 近期 script 載入、回顧塊摘要、S1–S7/L1/N1 檢查
pmb/research/runner.py         # build_research_prompt 加回顧塊
pmb/research/local_runner.py   # validate_research_artifacts 納入軟規則;最終只看硬錯
pmb/research/script_builder.py # 確定性後備改用明確的 ChartSegment/CardSegment,行為不變
pmb/tts/edge.py, pmb/cli.py    # voice_key、validate-research 指令、cover_spec 泛化
pmb/config.py                  # tts_voice_a/b、sting_enable、slogan_intro/outro 新預設
prompts/daily_research.md      # §6
README.md, .env.example        # 新段型、新設定
```

資料流不變:快照 → 研究 agent 寫 brief/script/report → 驗證(硬 + 軟)→ 合成
(renderer 產句子計畫 → 逐句 TTS 量測 → 時間軸 → 各段 ASS + clip → sting 插入 → 串接 → 母帶)→ 上傳。

---

## 8. 錯誤處理

| 情況 | 行為 |
|---|---|
| 未知 kind / 缺必填欄位 | schema 硬錯 → 重試;最後仍錯則當天不出片(與現行相同) |
| 軟規則違反 | 重試時帶錯誤;最後仍違反照樣出片,WARNING 記 log |
| 文字超長 | renderer 換行/縮字級,WARNING |
| bignum 數字解析失敗 | 靜態 pop-in,WARNING |
| sting 音效生成失敗 | 略過音效,口號照播,WARNING |
| sting 口號 TTS 失敗 | 整段 sting 略過,WARNING,影片照出 |
| 某段無可發音內容 | 沿用現行:跳過該段 |
| 歷史 script 讀不到/解析失敗 | 回顧塊與反重複規則略過該日,WARNING |

---

## 9. 測試

- **schema**:6 種 kind 的合法/不合法案例;舊檔推斷;`artifacts/` 內現有全部 script 皆可載入
  (以複製進 `tests/fixtures/` 的代表性舊檔測,artifacts 本身不入庫);`spoken_text` 與預算。
- **variety**:以 fixture 建「最近 N 天」,S1–S7、L1、N1 各有通過/擋下案例;無歷史時全過;
  回顧塊摘要內容。
- **prompt**:`build_research_prompt` 含回顧塊與近 20 天術語。
- **local_runner**:軟錯在最後一次不擋出片、硬錯仍擋。
- **renderer(純函式,不跑 ffmpeg)**:對話泡泡時間 = 各句起點、泡泡句無字幕、旁白有字幕;
  split 下格在第 2 句;recap 逐列與不足句數的平均分布;bignum 解析(`5.26%`、`+16.2萬`、`-0.27%`、
  無法解析)與 count-up 事件數;「……」斷句與 0.5s gap;收尾口號不重複接;sting 長度。
- **配音**:voice_key → 聲線對應。
- **cover_spec**:bignum / split 取數字。
- **煙霧**:一支含 6 種 kind 的 fixture 跑 `pmb assemble --dry-run` 產出 mp4;抽幀人工確認版面。
- 全部既有測試維持綠燈;`ruff check` 乾淨(`assemble.py`/`cards.py` 不套 ruff format)。

---

## 10. 上線

1. 全程在 worktree `.worktrees/video-variety`(分支 `feat/video-variety`)開發;主 checkout 維持 main,
   19:45 的 `pmb auto` 不受影響。
2. 合併前彩排:worktree 內放 `.env`(自主 checkout 複製,不入庫),實跑
   `pmb research-local --no-push` + `pmb assemble`(真實 TTS、不上傳),產出一支真片給使用者看;
   避開 19:00–21:30 以免與日更搶 Claude 用量。
3. 使用者點頭後合併進 main(避開 19:00–21:30),push。
4. 上線後第一週每天看成片與 autopilot.log 的軟錯 WARNING;兩週後比對 §1.5 觀察指標。

---

## 11. 第二期候選(本規格不做)
念到某字時圖表對應元素高亮/放大、折線與長條生長動畫、圖表段 stat 數字跳動、段間轉場音效、
更自然的 TTS(需保有逐字時間戳)、YouTube Analytics 留存曲線(需使用者到 GCP 啟用 API)。
