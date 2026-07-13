"""autopilot 純邏輯測試:產物就緒判斷、冪等、launchd plist(不碰 launchctl/網路)。"""

import datetime as dt
import json
import plistlib
from pathlib import Path

from pmb.autopilot import already_published, build_plist, research_ready

_D = dt.date(2026, 7, 10)


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
