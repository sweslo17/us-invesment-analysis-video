# PMB 控台(Tauri 桌面 App)

把 `pmb` CLI 包成桌面控制面板:一眼看每日製作狀態、按鈕觸發各步驟、檢視講稿/Brief/報告/影片、即時看執行日誌。

## 它做什麼

- **狀態儀表板**:選交易日 → 顯示 快照 / Brief / 講稿 / 報告 / 影片 / 發布 是否已產出。
- **執行按鈕**:`1 取數` `2 研究` `3 合成` `4 發布` 與 `▶ 全流程 run`,可切換 `dry-run`(範例/靜音)與 `approve`(真上傳)。
- **內容檢視**:講稿(逐段 vo/字卡/圖)、Brief(研判/regime/催化劑/thesis)、報告(markdown)、影片(系統播放器開啟 + 發布狀態)。
- **即時日誌**:把 `poetry run pmb …` 的 stdout/stderr 逐行串到右側。

> 後端是 Rust(Tauri v2),用 login shell 跑 `poetry run pmb`(取得 poetry PATH),並讀專案根的 `artifacts/`。確定性、無任何外部呼叫。

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
