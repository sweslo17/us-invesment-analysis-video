// PMB 控台後端:把既有的 `poetry run pmb …` CLI 包成桌面操作,
// 並讀取 artifacts/ 呈現每日製作狀態與內容。確定性、無外部呼叫。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Command, Stdio};

use serde::Serialize;
use tauri::{AppHandle, Emitter};

/// PMB 專案根目錄:優先用 PMB_ROOT,否則用編譯時的 manifest 位置往上兩層
/// (desktop/src-tauri → 專案根)。本機開發用,穩定。
fn project_root() -> PathBuf {
    if let Ok(p) = std::env::var("PMB_ROOT") {
        return PathBuf::from(p);
    }
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(|p| p.parent())
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| PathBuf::from("."))
}

fn artifacts_dir() -> PathBuf {
    project_root().join("artifacts")
}

/// 允許觸發的 pmb 子指令(白名單,避免任意指令注入)。
const ALLOWED_STEPS: [&str; 7] =
    ["fetch", "research", "render", "assemble", "publish", "run", "today"];

fn is_valid_date(d: &str) -> bool {
    d.len() == 10
        && d.as_bytes()
            .iter()
            .enumerate()
            .all(|(i, &b)| if i == 4 || i == 7 { b == b'-' } else { b.is_ascii_digit() })
}

#[derive(Serialize)]
struct Status {
    date: String,
    snapshot: bool,
    brief: bool,
    script: bool,
    report: bool,
    video: bool,
    publish: bool,
    cover: bool,
    published: Option<bool>,
    video_id: Option<String>,
}

fn artifact_path(date: &str, kind: &str) -> PathBuf {
    let dir = artifacts_dir();
    match kind {
        "snapshot" => dir.join(format!("snapshot_{date}.json")),
        "brief" => dir.join(format!("brief_{date}.json")),
        "script" => dir.join(format!("script_{date}.json")),
        "report" => dir.join(format!("report_{date}.md")),
        "video" => dir.join(format!("video_{date}.mp4")),
        "publish" => dir.join(format!("publish_{date}.json")),
        "cover" => dir.join(format!("cover_{date}.png")),
        _ => dir.join(format!("{kind}_{date}")),
    }
}

/// 從檔名抓出 YYYY-MM-DD(掃 10 字元視窗)。
fn extract_date(name: &str) -> Option<String> {
    let bytes = name.as_bytes();
    if bytes.len() < 10 {
        return None;
    }
    for i in 0..=bytes.len() - 10 {
        let slice = &name[i..i + 10];
        if is_valid_date(slice) {
            return Some(slice.to_string());
        }
    }
    None
}

#[tauri::command]
fn list_dates() -> Vec<String> {
    let mut dates: Vec<String> = Vec::new();
    if let Ok(entries) = std::fs::read_dir(artifacts_dir()) {
        for entry in entries.flatten() {
            if let Some(name) = entry.file_name().to_str() {
                if let Some(d) = extract_date(name) {
                    if !dates.contains(&d) {
                        dates.push(d);
                    }
                }
            }
        }
    }
    dates.sort();
    dates.reverse(); // 最新在前
    dates
}

#[tauri::command]
fn get_status(date: String) -> Status {
    let exists = |kind: &str| artifact_path(&date, kind).exists();
    let (mut published, mut video_id) = (None, None);
    let publish_file = artifact_path(&date, "publish");
    if publish_file.exists() {
        if let Ok(text) = std::fs::read_to_string(&publish_file) {
            if let Ok(json) = serde_json::from_str::<serde_json::Value>(&text) {
                published = json.get("published").and_then(|v| v.as_bool());
                video_id = json
                    .get("video_id")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());
            }
        }
    }
    Status {
        snapshot: exists("snapshot"),
        brief: exists("brief"),
        script: exists("script"),
        report: exists("report"),
        video: exists("video"),
        publish: exists("publish"),
        cover: exists("cover"),
        published,
        video_id,
        date,
    }
}

/// 讀某日某類 artifact 的原始內容(json / md)。不存在回 Err。
#[tauri::command]
fn read_artifact(date: String, kind: String) -> Result<String, String> {
    let path = artifact_path(&date, &kind);
    std::fs::read_to_string(&path).map_err(|_| format!("尚未產生:{}", path.display()))
}

#[tauri::command]
fn video_path(date: String) -> Option<String> {
    let p = artifact_path(&date, "video");
    if p.exists() {
        Some(p.to_string_lossy().to_string())
    } else {
        None
    }
}

/// 用系統預設程式開啟路徑(影片 / 資料夾)。
#[tauri::command]
fn open_path(path: String) -> Result<(), String> {
    Command::new("open")
        .arg(&path)
        .spawn()
        .map(|_| ())
        .map_err(|e| format!("開啟失敗:{e}"))
}

/// 開啟專案內的指定檔(白名單:研究 prompt / thesis / artifacts 資料夾)。
#[tauri::command]
fn open_rel(rel: String) -> Result<(), String> {
    const ALLOWED: [&str; 3] = ["prompts/daily_research.md", "state/thesis.json", "artifacts"];
    if !ALLOWED.contains(&rel.as_str()) {
        return Err(format!("不允許開啟:{rel}"));
    }
    let path = project_root().join(&rel);
    Command::new("open")
        .arg(&path)
        .spawn()
        .map(|_| ())
        .map_err(|e| format!("開啟失敗:{e}"))
}

#[tauri::command]
fn cover_path(date: String) -> Option<String> {
    let p = artifact_path(&date, "cover");
    if p.exists() {
        Some(p.to_string_lossy().to_string())
    } else {
        None
    }
}

/// 取得今日「研究 prompt」(模板 + 快照 + thesis),供貼進 Claude Code 做研究。
#[tauri::command]
fn research_prompt(date: String) -> Result<String, String> {
    if !is_valid_date(&date) {
        return Err(format!("日期格式錯誤:{date}"));
    }
    let root = project_root();
    let out = Command::new("/bin/zsh")
        .arg("-lc")
        .arg(format!(
            "cd '{}' && poetry run pmb research-prompt --date {}",
            root.display(),
            date
        ))
        .current_dir(&root)
        .output()
        .map_err(|e| format!("執行失敗:{e}"))?;
    if !out.status.success() {
        return Err(String::from_utf8_lossy(&out.stderr).trim().to_string());
    }
    Ok(String::from_utf8_lossy(&out.stdout).to_string())
}

/// 查今天是否交易日 + 下一個交易日(呼叫 `pmb next-session --json`)。
#[tauri::command]
fn next_session() -> Result<serde_json::Value, String> {
    let root = project_root();
    let out = Command::new("/bin/zsh")
        .arg("-lc")
        .arg(format!(
            "cd '{}' && poetry run pmb next-session --json",
            root.display()
        ))
        .current_dir(&root)
        .output()
        .map_err(|e| format!("執行失敗:{e}"))?;
    let stdout = String::from_utf8_lossy(&out.stdout);
    // login shell 可能印雜訊;取最後一行 JSON
    let line = stdout
        .lines()
        .rev()
        .find(|l| l.trim_start().starts_with('{'))
        .ok_or_else(|| "next-session 無 JSON 輸出".to_string())?;
    serde_json::from_str(line).map_err(|e| format!("解析失敗:{e}"))
}

/// 觸發一個 pmb 步驟;以 login shell 跑(取得 poetry PATH),
/// 即時把 stdout/stderr 逐行 emit 給前端,結束時 emit 結束碼。
#[tauri::command]
fn run_step(
    app: AppHandle,
    step: String,
    date: Option<String>,
    dryrun: bool,
    approve: bool,
) -> Result<(), String> {
    if !ALLOWED_STEPS.contains(&step.as_str()) {
        return Err(format!("不允許的步驟:{step}"));
    }
    let mut parts = vec![step];
    if let Some(d) = date {
        if !d.is_empty() {
            if !is_valid_date(&d) {
                return Err(format!("日期格式錯誤:{d}"));
            }
            parts.push("--date".into());
            parts.push(d);
        }
    }
    if dryrun {
        parts.push("--dry-run".into());
    }
    if approve {
        parts.push("--approve".into());
    }

    let root = project_root();
    let inner = format!(
        "cd '{}' && poetry run pmb {}",
        root.display(),
        parts.join(" ")
    );

    std::thread::spawn(move || {
        let _ = app.emit("pmb-log", format!("$ poetry run pmb {}", parts.join(" ")));
        let child = Command::new("/bin/zsh")
            .arg("-lc")
            .arg(&inner)
            .current_dir(&root)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn();
        let mut child = match child {
            Ok(c) => c,
            Err(e) => {
                let _ = app.emit("pmb-log", format!("✗ 無法啟動:{e}"));
                let _ = app.emit("pmb-done", -1);
                return;
            }
        };
        // stderr(loguru 走這裡)另開執行緒讀
        let stderr = child.stderr.take();
        let app_err = app.clone();
        let err_handle = std::thread::spawn(move || {
            if let Some(err) = stderr {
                for line in BufReader::new(err).lines().map_while(Result::ok) {
                    let _ = app_err.emit("pmb-log", line);
                }
            }
        });
        if let Some(out) = child.stdout.take() {
            for line in BufReader::new(out).lines().map_while(Result::ok) {
                let _ = app.emit("pmb-log", line);
            }
        }
        let _ = err_handle.join();
        let code = child.wait().ok().and_then(|s| s.code()).unwrap_or(-1);
        let _ = app.emit("pmb-done", code);
    });
    Ok(())
}

fn git(args: &[&str]) -> Result<String, String> {
    let root = project_root();
    let out = Command::new("git")
        .args(args)
        .current_dir(&root)
        .output()
        .map_err(|e| format!("git 執行失敗:{e}"))?;
    let mut s = String::from_utf8_lossy(&out.stdout).to_string();
    s.push_str(&String::from_utf8_lossy(&out.stderr));
    let s = s.trim().to_string();
    if out.status.success() {
        Ok(s)
    } else {
        Err(s)
    }
}

#[tauri::command]
fn git_status() -> Result<String, String> {
    let _ = git(&["fetch", "--quiet"]); // best-effort:先抓遠端,才知道雲端是否已推研究(離線則略過)
    git(&["status", "-sb"])
}

/// 取雲端推到 main 的研究產物(fast-forward;本機若有未推送提交會擋下,提示先推送)。
#[tauri::command]
fn git_pull() -> Result<String, String> {
    git(&["pull", "--ff-only"])
}

/// 本機審查後回推修正:強制加當日 text 產物(artifacts/ 被 gitignore)+ 已追蹤檔修改 → commit → push。
#[tauri::command]
fn git_commit_push(message: String, date: Option<String>) -> Result<String, String> {
    if message.trim().is_empty() {
        return Err("請填修正說明".to_string());
    }
    if let Some(d) = date.as_deref() {
        if is_valid_date(d) {
            for (kind, ext) in [("brief", "json"), ("script", "json"), ("report", "md")] {
                let rel = format!("artifacts/{kind}_{d}.{ext}");
                if project_root().join(&rel).exists() {
                    let _ = git(&["add", "-f", &rel]);
                }
            }
        }
    }
    git(&["add", "-u"])?; // 已追蹤檔(state/、prompts/、pmb/…)的修改
    let staged = git(&["diff", "--cached", "--name-only"])?;
    if staged.is_empty() {
        return Err("沒有可提交的變更".to_string());
    }
    git(&["commit", "-m", &message])?;
    let pushed = git(&["push"])?;
    Ok(format!("已提交並推送:\n{staged}\n{pushed}"))
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_clipboard_manager::init())
        .invoke_handler(tauri::generate_handler![
            list_dates,
            get_status,
            read_artifact,
            video_path,
            cover_path,
            open_path,
            open_rel,
            next_session,
            research_prompt,
            git_status,
            git_pull,
            git_commit_push,
            run_step
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
