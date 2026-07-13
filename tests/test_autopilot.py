"""autopilot 測試:產物就緒判斷、冪等、launchd plist、claude/* 分支退路(本機 git,不碰網路)。"""

import datetime as dt
import json
import plistlib
import subprocess
from pathlib import Path

from pmb.autopilot import (
    adopt_research_branch,
    already_published,
    build_plist,
    find_research_branch,
    research_ready,
)

_D = dt.date(2026, 7, 10)


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
             "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin", "HOME": str(cwd)},
    )


def _make_relay_fixture(tmp_path: Path) -> Path:
    """origin(bare)+ 本機 clone;雲端把研究推上 origin 的 claude/ 分支(main 沒有)。"""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(["init", "--bare", "-b", "main"], origin)

    seed = tmp_path / "seed"
    _git(["clone", str(origin), str(seed)], tmp_path)
    (seed / "README.md").write_text("base")
    _git(["add", "."], seed)
    _git(["commit", "-m", "base"], seed)
    _git(["push", "origin", "main"], seed)

    # 模擬雲端:研究產物 commit 到 claude/xxx 分支(push main 被拒的退路)
    _git(["checkout", "-b", "claude/happy-test"], seed)
    arts = seed / "artifacts"
    arts.mkdir()
    (arts / f"brief_{_D}.json").write_text("{}")
    (arts / f"script_{_D}.json").write_text("{}")
    _git(["add", "-f", "artifacts"], seed)
    _git(["commit", "-m", f"research: {_D}"], seed)
    _git(["push", "origin", "claude/happy-test"], seed)

    local = tmp_path / "local"
    _git(["clone", str(origin), str(local)], tmp_path)
    return local


def test_find_research_branch_locates_claude_branch_with_artifacts(tmp_path):
    local = _make_relay_fixture(tmp_path)
    ref = find_research_branch(_D, local)
    assert ref == "refs/remotes/origin/claude/happy-test"
    # 沒有該日產物的日期找不到
    assert find_research_branch(dt.date(2020, 1, 1), local) is None


def test_adopt_research_branch_merges_into_main_and_pushes_back(tmp_path):
    local = _make_relay_fixture(tmp_path)
    ref = find_research_branch(_D, local)
    assert adopt_research_branch(ref, local)
    assert (local / "artifacts" / f"brief_{_D}.json").exists()  # 併進 main 的工作樹
    # 已回推 origin/main(接力補完,雲端隔天 rebase 乾淨)
    out = subprocess.run(
        ["git", "log", "origin/main", "--oneline", "-1"],
        cwd=local, capture_output=True, text=True,
    ).stdout
    assert f"research: {_D}" in out


def test_research_ready_requires_brief_and_script(tmp_path):
    assert not research_ready(tmp_path, _D)
    (tmp_path / f"brief_{_D}.json").write_text("{}")
    assert not research_ready(tmp_path, _D)
    (tmp_path / f"script_{_D}.json").write_text("{}")
    assert research_ready(tmp_path, _D)


def test_already_published_only_when_manifest_says_published(tmp_path):
    assert already_published(tmp_path, _D) is None
    manifest = tmp_path / f"publish_{_D}.json"
    manifest.write_text(json.dumps({"published": False, "video_id": None}))
    assert already_published(tmp_path, _D) is None
    manifest.write_text(json.dumps({"published": True, "video_id": "abc123"}))
    assert already_published(tmp_path, _D) == "abc123"


def test_already_published_tolerates_corrupt_manifest(tmp_path):
    (tmp_path / f"publish_{_D}.json").write_text("not-json{")
    assert already_published(tmp_path, _D) is None


def test_build_plist_schedules_weekdays_at_given_time():
    data = plistlib.loads(build_plist(Path("/repo"), 19, 30))
    cal = data["StartCalendarInterval"]
    assert [c["Weekday"] for c in cal] == [1, 2, 3, 4, 5]  # 週一~五
    assert all(c["Hour"] == 19 and c["Minute"] == 30 for c in cal)
    assert data["RunAtLoad"] is False  # 只在排定時間跑
    joined = " ".join(data["ProgramArguments"])
    assert "pmb auto" in joined and "/repo" in joined


def test_build_plist_bakes_absolute_poetry_and_path_env():
    # launchd 不讀 .zshrc:poetry 必須是絕對路徑,且 PATH 要烤進 EnvironmentVariables
    data = plistlib.loads(build_plist(Path("/repo"), 19, 45))
    cmd = data["ProgramArguments"][-1]
    poetry_part = cmd.split("&&")[1].strip().split()[0]
    assert poetry_part.startswith("/")  # 絕對路徑,不靠 shell PATH 找 poetry
    assert data["EnvironmentVariables"]["PATH"]  # 子行程(ffmpeg/git)靠這個
