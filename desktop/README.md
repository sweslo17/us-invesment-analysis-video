# PMB 控台(Tauri 桌面 App)

把 `pmb` CLI 包成桌面控制面板:一眼看每日製作狀態、按鈕觸發各步驟、檢視講稿/Brief/報告/影片、即時看執行日誌。

## 它做什麼

**以「步驟」為主導**。左欄是 4 個步驟,每步標明誰做、是否完成;點步驟,右側顯示該步的動作與產出,下方是即時日誌。

- **① 取數 💻 本機**:點「執行取數」→ 今日真實快照。
- **② 研究 ☁️ Claude Code**:**不是本機按鈕**。雲端 routine 盤前自動跑;或在本機按「複製研究 Prompt」→ 貼進 Claude Code → 它研究並寫出 brief/講稿/報告。右側可看講稿/Brief/報告與「研究 Prompt」。
- **③ 合成 💻 本機**:點「執行合成」→ 直式短片(右側內嵌播放 + 封面)。
- **④ 發布 💻 本機**:「預演(不上傳)」看發布資訊,或「上傳 YouTube(private)」實際上傳;右側顯示標題/tags/上傳到的頻道。
- **即時日誌**:本機步驟的 `poetry run pmb …` 輸出逐行串到右下。
- 頂列顯示「今天開市/休市 · 下次啟動日」。

> **沒有 dry-run 開關**:取數/合成都直接跑真的(免費);唯一的 gate 是發布要不要上傳。研究不走 API key,是 Claude Code 做的。
>
> 後端是 Rust(Tauri v2),用 login shell 跑 `poetry run pmb`(取得 poetry PATH),讀專案根的 `artifacts/`。確定性、無外部呼叫。

## 前置需求

- Rust ≥ 1.77(`rustup update stable`)、Node 18+、本專案已能跑 `poetry run pmb`(含 `.env`)。
- macOS 已裝 Xcode Command Line Tools。

## 開發模式(平常用這個)

```bash
cd desktop
npm install          # 第一次
npm run tauri dev    # 開視窗;改前端會熱更新
```

第一次會編譯 Tauri 的 Rust 依賴,需幾分鐘;之後很快。

## 打包成 .app

```bash
cd desktop
npm run tauri build  # 產出 src-tauri/target/release/bundle/
```

⚠️ 注意:雙擊啟動的 `.app` 在 macOS 下 PATH 較精簡;本後端已用 `/bin/zsh -lc` 載入你的 profile 來找 `poetry`,一般可用。若仍找不到 poetry,改用 `npm run tauri dev`,或設定環境變數 `PMB_ROOT` 指向專案根。

## 設定

- 專案根:預設用編譯時位置往上推(`desktop/` 的上一層)。可用環境變數 **`PMB_ROOT`** 覆蓋。
- 真正上傳 YouTube 仍需 `.env` 內的 OAuth 憑證;沒有時 `approve` 會安全退回 dry-run。

## 安全

- 只會觸發白名單內的 `pmb` 子指令(fetch/research/render/assemble/publish/run)。
- 不自動公開:上傳固定 `private`,公開要你自己到 YouTube Studio 改。
- 偵測到 `dry-run` 範例內容會在日誌警告(提醒別把範例當真內容發布)。
