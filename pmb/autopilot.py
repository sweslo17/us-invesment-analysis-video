"""每日全自動駕駛:等雲端研究產物 → 合成 → 上傳(private)→ 通知。

目標是把人工壓到只剩「到 YouTube Studio 把影片改公開」一步(鐵則 #6:絕不自動公開)。

- ``pmb auto``:單次執行今天的自動流程(給 launchd / cron / 手動呼叫)。
- ``pmb autopilot install|uninstall|status``:管理 macOS launchd 排程(平日定時跑
  ``pmb auto``;安裝與否由使用者自己執行,程式不會偷裝)。
"""

from __future__ import annotations

import datetime as dt
import json
import plistlib
import subprocess
import sys
import time
from pathlib import Path

from loguru import logger

_LABEL = "com.pmb.autopilot"


def repo_root() -> Path:
    """專案根目錄(pmb/ 的上一層)。"""
    return Path(__file__).resolve().parent.parent


def notify(title: str, message: str) -> None:
    """桌面通知(macOS 用 osascript;其他平台僅留 log,不中斷流程)。"""
    logger.info("通知:{} — {}", title, message)
    if sys.platform != "darwin":
        return
    script = f'display notification "{message}" with title "{title}" sound name "Glass"'
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
    except Exception as exc:  # noqa: BLE001 — 通知失敗不影響主流程
        logger.warning("macOS 通知失敗:{}", exc)


def git_pull(cwd: Path) -> bool:
    """拉雲端 routine 推上 main 的研究產物。失敗不擋(本機可能已有產物)。"""
    proc = subprocess.run(
        ["git", "pull", "--rebase", "--autostash", "origin", "main"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        logger.warning("git pull 失敗(繼續用本機現有產物):{}", proc.stderr.strip()[-300:])
        return False
    out = proc.stdout.strip().splitlines()
    logger.info("git pull:{}", out[-1] if out else "ok")
    return True


def research_ready(artifacts_dir: Path, target: dt.date) -> bool:
    """雲端研究產物(brief + script)是否已就位。"""
    return all(
        (artifacts_dir / f"{kind}_{target}.json").exists() for kind in ("brief", "script")
    )


def already_published(artifacts_dir: Path, target: dt.date) -> str | None:
    """今天已成功上傳過就回傳 video_id(冪等:重跑不重上傳)。"""
    manifest = artifacts_dir / f"publish_{target}.json"
    if not manifest.exists():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data.get("video_id") if data.get("published") else None


def wait_for_research(
    artifacts_dir: Path,
    target: dt.date,
    *,
    pull: bool,
    wait_minutes: float,
    poll_seconds: float = 120.0,
) -> bool:
    """輪詢等雲端研究 commit 落地:每輪先 git pull 再檢查 brief/script。"""
    deadline = time.monotonic() + wait_minutes * 60
    while True:
        if pull:
            git_pull(repo_root())
        if research_ready(artifacts_dir, target):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        logger.info(
            "等待雲端研究產物(brief/script_{})… 再等 {:.0f} 分鐘",
            target,
            remaining / 60,
        )
        time.sleep(min(poll_seconds, max(remaining, 1)))


def studio_url(video_id: str) -> str:
    return f"https://studio.youtube.com/video/{video_id}/edit"


# ---------- launchd 排程(macOS) ----------


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{_LABEL}.plist"


def build_plist(repo: Path, hour: int, minute: int) -> bytes:
    """組 launchd plist:平日(週一~五)本地時間定時跑 ``pmb auto``。

    launchd 不讀 .zshrc、預設 PATH 也沒有 homebrew/pipx——poetry 用安裝當下解析的
    **絕對路徑**,並把安裝 shell 的完整 PATH 烤進 EnvironmentVariables(pmb 的子行程
    ffmpeg/git 才找得到)。log 落在 artifacts/。交易日判斷在 ``pmb auto`` 內做。
    """
    import os
    import shutil

    poetry = shutil.which("poetry")
    if not poetry:
        raise RuntimeError("找不到 poetry(請先確認 `which poetry` 有結果再安裝排程)")
    cmd = f"cd {repo} && {poetry} run pmb auto >> artifacts/autopilot.log 2>&1"
    payload = {
        "Label": _LABEL,
        "ProgramArguments": ["/bin/zsh", "-c", cmd],
        "WorkingDirectory": str(repo),
        "EnvironmentVariables": {"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        "StartCalendarInterval": [
            {"Weekday": wd, "Hour": hour, "Minute": minute} for wd in range(1, 6)
        ],
        "RunAtLoad": False,
        "StandardOutPath": str(repo / "artifacts" / "autopilot.launchd.log"),
        "StandardErrorPath": str(repo / "artifacts" / "autopilot.launchd.log"),
    }
    return plistlib.dumps(payload)


def install_autopilot(hour: int, minute: int) -> int:
    """寫入並載入 launchd 排程(使用者主動執行 ``pmb autopilot install`` 才會裝)。"""
    if sys.platform != "darwin":
        print("autopilot 排程目前只支援 macOS(launchd);Linux 請用 cron 呼叫 pmb auto。")
        return 1
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_plist(repo_root(), hour, minute))
    subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
    proc = subprocess.run(["launchctl", "load", str(path)], capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"launchctl load 失敗:{proc.stderr.strip()}")
        return 1
    print(f"✅ 已排程:平日 {hour:02d}:{minute:02d}(本地時間)自動跑 pmb auto")
    print(f"   plist:{path}")
    print("   流程:git pull 等雲端研究 → 合成 → 上傳 YouTube(private)→ 桌面通知")
    print("   人工只剩:到 YouTube Studio 看片、改『公開』。")
    print("   ⚠️ 美東日光節約切換時,雲端研究落地時間會平移一小時;pmb auto 會輪詢等待,無需調整。")
    return 0


def uninstall_autopilot() -> int:
    path = plist_path()
    subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
    if path.exists():
        path.unlink()
        print(f"已移除排程與 {path}")
    else:
        print("沒有已安裝的 autopilot 排程。")
    return 0


def autopilot_status() -> int:
    path = plist_path()
    if not path.exists():
        print("autopilot:未安裝(pmb autopilot install --time 19:45)")
        return 0
    data = plistlib.loads(path.read_bytes())
    times = data.get("StartCalendarInterval", [])
    when = f"{times[0]['Hour']:02d}:{times[0]['Minute']:02d}" if times else "?"
    proc = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    loaded = _LABEL in proc.stdout
    print(f"autopilot:已安裝,平日 {when};launchd {'已載入 ✓' if loaded else '未載入 ✗'}")
    print(f"  plist:{path}")
    print(f"  log:{repo_root() / 'artifacts' / 'autopilot.log'}")
    return 0
