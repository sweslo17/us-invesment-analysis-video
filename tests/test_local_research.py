"""本機研究 runner 測試:驗證/重試迴圈與產物檢查(注入假 invoke,不跑 claude CLI)。"""

import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace

from pmb.research.local_runner import run_local_research, validate_research_artifacts
from pmb.research.sample import sample_brief_json
from pmb.schemas.brief import Brief
from pmb.schemas.snapshot import Snapshot

_D = dt.date(2026, 7, 10)


def _settings(tmp_path: Path) -> SimpleNamespace:
    arts = tmp_path / "artifacts"
    state = tmp_path / "state"
    arts.mkdir()
    state.mkdir()
    snap = Snapshot(session_date=_D, generated_at=dt.datetime.now(tz=dt.UTC))
    (arts / f"snapshot_{_D}.json").write_text(snap.model_dump_json(), encoding="utf-8")
    prompt = tmp_path / "prompt.md"
    prompt.write_text("研究任務模板", encoding="utf-8")
    return SimpleNamespace(artifacts_dir=arts, state_dir=state, prompt_path=prompt)


def _write_valid_artifacts(arts: Path) -> None:
    brief = Brief.model_validate_json(sample_brief_json(_D))
    (arts / f"brief_{_D}.json").write_text(brief.model_dump_json(), encoding="utf-8")
    script = {
        "segments": [
            {"vo": "測試句。", "chart_id": "c0", "t_start": 0.0, "duration": 5.0},
        ],
        "charts": [{"id": "c0", "module": "index_overnight_grid", "params": {}}],
    }
    (arts / f"script_{_D}.json").write_text(json.dumps(script), encoding="utf-8")
    (arts / f"report_{_D}.md").write_text("# 報告\n" + "內容 " * 200, encoding="utf-8")


def test_validate_rejects_over_budget_vo_before_tts(tmp_path):
    """字數超標必須在配音前被擋下(否則成片超 180s、失去 Shorts 資格)。

    2026-07-27 實例:研究寫了 1203 字 → 成片 197s。字數預算只寫在 prompt 裡、
    LLM 偶爾會超,必須由驗證強制執行(失敗訊息帶實際字數,重試才修得動)。
    """
    _write_valid_artifacts(tmp_path)
    script = json.loads((tmp_path / f"script_{_D}.json").read_text())
    # 塞一段超長 vo(約 1200 字),模擬 7/27 的情況
    script["segments"][0]["vo"] = "這是一句很長的旁白內容需要控制字數。" * 67
    (tmp_path / f"script_{_D}.json").write_text(json.dumps(script), encoding="utf-8")

    errors = validate_research_artifacts(tmp_path, _D)
    assert any("字數" in e for e in errors), f"應擋下超標字數,實際錯誤:{errors}"
    # 錯誤訊息要含實際字數與上限,agent 重試時才知道要砍多少
    msg = next(e for e in errors if "字數" in e)
    assert "1206" in msg or "120" in msg
    assert "上限" in msg


def test_validate_passes_within_budget(tmp_path):
    _write_valid_artifacts(tmp_path)  # 正常長度的講稿
    assert validate_research_artifacts(tmp_path, _D) == []


def test_validate_reports_missing_and_invalid_artifacts(tmp_path):
    errors = validate_research_artifacts(tmp_path, _D)
    assert len(errors) == 3  # brief/script/report 全缺
    (tmp_path / f"brief_{_D}.json").write_text("{not json")
    errors = validate_research_artifacts(tmp_path, _D)
    assert any("schema" in e for e in errors)


def test_invoke_headless_passes_model_flag_and_token_env():
    # model → --model;oauth_token → 子行程 CLAUDE_CODE_OAUTH_TOKEN
    # (launchd 淨環境沒互動登入,長效 token 才不會像 7/22 那樣 session 過期斷線)
    import subprocess

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env") or {}
        return subprocess.CompletedProcess(cmd, 0, stdout="done", stderr="")

    import pmb.research.local_runner as lr

    orig = lr.subprocess.run
    lr.subprocess.run = fake_run
    try:
        lr.invoke_headless_claude(
            "prompt", Path("/repo"), model="claude-sonnet-5", oauth_token="tok-abc"
        )
    finally:
        lr.subprocess.run = orig
    assert "--model" in captured["cmd"] and "claude-sonnet-5" in captured["cmd"]
    assert captured["env"].get("CLAUDE_CODE_OAUTH_TOKEN") == "tok-abc"


def test_run_local_research_succeeds_when_agent_writes_valid_files(tmp_path):
    settings = _settings(tmp_path)
    calls: list[str] = []

    def fake_invoke(prompt: str) -> None:
        calls.append(prompt)
        _write_valid_artifacts(settings.artifacts_dir)

    assert run_local_research(_D, settings, invoke=fake_invoke) is True
    assert len(calls) == 1
    assert "快照" in calls[0] and "artifacts/brief_" in calls[0]  # files 模式 prompt


def test_over_budget_retries_then_ships_anyway_rather_than_losing_the_day(tmp_path):
    """字數超標要重試砍字;但重試用盡仍超標時,寧可出「非 Shorts 的長片」也不要整天沒影片。

    schema 壞掉是硬錯(不能出片);字數超標是軟錯(片還是可用,只是失去 Shorts 紅利)。
    """
    settings = _settings(tmp_path)
    calls: list[str] = []

    def always_too_long(prompt: str) -> None:
        calls.append(prompt)
        _write_valid_artifacts(settings.artifacts_dir)
        script = json.loads((settings.artifacts_dir / f"script_{_D}.json").read_text())
        script["segments"][0]["vo"] = "很長的旁白內容需要控制字數哦。" * 90  # ~1350 字
        (settings.artifacts_dir / f"script_{_D}.json").write_text(
            json.dumps(script), encoding="utf-8"
        )

    ok = run_local_research(_D, settings, invoke=always_too_long, max_attempts=2)
    assert ok is True  # 仍出片(降級),不是整天失敗
    assert len(calls) == 2  # 但確實重試過、試圖砍字
    assert "字數超標" in calls[1]  # 重試 prompt 帶了砍字指示


def test_hard_errors_still_fail_after_retries(tmp_path):
    settings = _settings(tmp_path)

    def broken_schema(prompt: str) -> None:
        (settings.artifacts_dir / f"brief_{_D}.json").write_text("{broken")

    assert run_local_research(_D, settings, invoke=broken_schema, max_attempts=2) is False


def test_run_local_research_retries_with_error_feedback_then_succeeds(tmp_path):
    settings = _settings(tmp_path)
    calls: list[str] = []

    def flaky_invoke(prompt: str) -> None:
        calls.append(prompt)
        if len(calls) == 1:
            (settings.artifacts_dir / f"brief_{_D}.json").write_text("{broken")
        else:
            _write_valid_artifacts(settings.artifacts_dir)

    assert run_local_research(_D, settings, invoke=flaky_invoke) is True
    assert len(calls) == 2
    assert "未通過驗證" in calls[1]  # 第二次帶錯誤回饋

    # 用盡重試 → False(不拋例外)
    always_bad = lambda p: (settings.artifacts_dir / f"script_{_D}.json").write_text("x")  # noqa: E731
    for f in settings.artifacts_dir.glob(f"*_{_D}.json"):
        if "snapshot" not in f.name:
            f.unlink()
    assert run_local_research(_D, settings, invoke=always_bad, max_attempts=2) is False


# --- 額度上限(session limit)處理 ---------------------------------------------
# 2026-08-26 事故:19:46 撞到 session limit(20:00 重置),兩次重試相隔 6 秒、
# 全撞同一道牆,整天沒產出。且 log 只印 stderr,而額度訊息在 stdout,查因得翻
# transcript。以下測試把「錯誤要看得見」與「等重置再試」都釘住。


def test_invoke_headless_error_message_includes_stdout(tmp_path):
    """rc!=0 時錯誤訊息必須含 stdout——額度/API 錯誤訊息印在 stdout,不是 stderr。"""
    import subprocess

    import pmb.research.local_runner as lr

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 1, stdout="You've hit your session limit · resets 8pm (Asia/Taipei)", stderr=""
        )

    orig = lr.subprocess.run
    lr.subprocess.run = fake_run
    try:
        try:
            lr.invoke_headless_claude("prompt", tmp_path)
        except RuntimeError as exc:
            assert "session limit" in str(exc), f"錯誤訊息漏了 stdout:{exc}"
        else:
            raise AssertionError("rc=1 應該要拋錯")
    finally:
        lr.subprocess.run = orig


def test_invoke_headless_raises_rate_limited_with_reset_time(tmp_path):
    """額度上限要拋可辨識的 RateLimitedError,並帶上解析出的重置時間。"""
    import subprocess

    import pmb.research.local_runner as lr

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 1, stdout="You've hit your session limit · resets 8pm (Asia/Taipei)", stderr=""
        )

    orig = lr.subprocess.run
    lr.subprocess.run = fake_run
    try:
        try:
            lr.invoke_headless_claude("prompt", tmp_path)
        except lr.RateLimitedError as exc:
            assert exc.reset_at is not None
            assert exc.reset_at.hour == 20 and exc.reset_at.minute == 0
        else:
            raise AssertionError("應拋 RateLimitedError")
    finally:
        lr.subprocess.run = orig


def test_parse_reset_at_handles_common_shapes():
    import pmb.research.local_runner as lr

    now = dt.datetime(2026, 8, 26, 19, 46, tzinfo=dt.UTC).astimezone(
        __import__("zoneinfo").ZoneInfo("Asia/Taipei")
    )
    got = lr.parse_reset_at("You've hit your session limit · resets 8pm (Asia/Taipei)", now=now)
    assert got is not None and (got.hour, got.minute) == (20, 0)
    got = lr.parse_reset_at("usage limit reached · resets at 8:30pm (Asia/Taipei)", now=now)
    assert got is not None and (got.hour, got.minute) == (20, 30)
    assert lr.parse_reset_at("some unrelated failure", now=now) is None


def test_rate_limit_waits_until_reset_then_succeeds(tmp_path):
    """撞額度時要睡到重置後再試,而不是 6 秒後重撞、然後放棄整天。"""
    import pmb.research.local_runner as lr

    settings = _settings(tmp_path)
    now = dt.datetime.now(tz=dt.UTC)
    slept: list[float] = []
    calls: list[str] = []

    def invoke(prompt: str) -> None:
        calls.append(prompt)
        if len(calls) == 1:
            raise lr.RateLimitedError("session limit", reset_at=now + dt.timedelta(minutes=10))
        _write_valid_artifacts(settings.artifacts_dir)

    ok = run_local_research(
        _D, settings, invoke=invoke, max_attempts=2, sleep=slept.append, now=lambda: now
    )
    assert ok is True, "等重置後應該要成功"
    assert len(slept) == 1 and 600 <= slept[0] <= 900, f"應睡到重置後(含緩衝),實際 {slept}"
    assert len(calls) == 2


def test_rate_limit_reset_beyond_deadline_gives_up_without_sleeping(tmp_path):
    """重置時間晚到來不及趕上開盤,就不要傻等(睡到開盤後才出片沒意義)。"""
    import pmb.research.local_runner as lr

    settings = _settings(tmp_path)
    now = dt.datetime.now(tz=dt.UTC)
    slept: list[float] = []

    def invoke(prompt: str) -> None:
        raise lr.RateLimitedError("session limit", reset_at=now + dt.timedelta(hours=6))

    ok = run_local_research(
        _D, settings, invoke=invoke, max_attempts=2, sleep=slept.append, now=lambda: now
    )
    assert ok is False
    assert slept == [], f"超過等待上限不該睡,實際 {slept}"


def test_rate_limit_does_not_consume_content_retry_budget(tmp_path):
    """額度上限不是「產物寫壞」,不該吃掉修正產物的重試次數。"""
    import pmb.research.local_runner as lr

    settings = _settings(tmp_path)
    now = dt.datetime.now(tz=dt.UTC)
    calls: list[str] = []

    def invoke(prompt: str) -> None:
        calls.append(prompt)
        if len(calls) == 1:
            raise lr.RateLimitedError("session limit", reset_at=now + dt.timedelta(minutes=5))
        if len(calls) == 2:
            (settings.artifacts_dir / f"brief_{_D}.json").write_text("{broken")
            return
        _write_valid_artifacts(settings.artifacts_dir)

    ok = run_local_research(
        _D, settings, invoke=invoke, max_attempts=2, sleep=lambda s: None, now=lambda: now
    )
    assert ok is True, "額度重試後仍應保有 2 次產物重試"
    assert len(calls) == 3
