"""本機研究 runner 測試:驗證/重試迴圈與產物檢查(注入假 invoke,不跑 claude CLI)。"""

import datetime as dt
import json
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from loguru import logger

from pmb.research import local_runner
from pmb.research.local_runner import (
    RateLimitedError,
    normalize_research_outputs,
    run_local_research,
    validate_research_artifacts,
)
from pmb.research.sample import sample_brief_json
from pmb.schemas.brief import Brief
from pmb.schemas.snapshot import Snapshot
from pmb.textnorm import zh_punct, zh_punct_obj

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
            {"kind": "card", "vo": "測試開場。", "headline": "測試開場", "tag": "測試日"},
            {"kind": "chart", "vo": "測試句一。", "chart_id": "c0"},
            {"kind": "bignum", "vo": "數字是5.26%。", "value": "5.26%", "label": "殖利率"},
            {"kind": "chart", "vo": "測試句二。", "chart_id": "c1"},
            {"kind": "card", "vo": "金句。", "headline": "金句\n對句",
             "tag": "巴菲特 不知道有沒有說過"},
        ],
        "charts": [{"id": "c0", "module": "index_overnight_grid", "params": {}},
                   {"id": "c1", "module": "rates_trend", "params": {}}],
        "gags": ["測試梗一", "測試梗二"],
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
    total = sum(len(seg["vo"]) for seg in script["segments"])
    assert str(total) in msg
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


def test_validate_rejects_vo_over_short_form_budget(tmp_path):
    """成片目標 65–80 秒(330–410 字),硬上限 520 字。

    2.5 分鐘的 Shorts 留不住人:8 月起觀看數掉約 4 倍。600 字必須被擋下,錯誤訊息要帶新的
    目標區間,agent 重寫時才知道要砍到哪。v4 起系統自動加開場/收尾口號約 6 秒,不在字數裡,
    預估秒數要把這 6 秒算進去(fixture 共 634 字:634 × 0.18 + 6 ≈ 120s,不含則是 114s)。
    """
    _write_valid_artifacts(tmp_path)
    script = json.loads((tmp_path / f"script_{_D}.json").read_text())
    script["segments"][0]["vo"] = "這是一句很長的旁白內容需要控制字數。" * 34  # 612 字
    (tmp_path / f"script_{_D}.json").write_text(json.dumps(script), encoding="utf-8")

    errors = validate_research_artifacts(tmp_path, _D)
    msg = next((e for e in errors if "字數" in e), None)
    assert msg is not None, f"612 字應被擋下,實際錯誤:{errors}"
    assert "330–410" in msg and "380–450" not in msg
    assert "預估成片 120 秒" in msg  # 634 × 0.18 + 6(系統口號);少算 6 秒會是 114


def test_validate_accepts_vo_at_short_form_target(tmp_path):
    _write_valid_artifacts(tmp_path)
    script = json.loads((tmp_path / f"script_{_D}.json").read_text())
    script["segments"][0]["vo"] = "這是一句很長的旁白內容需要控制字數。" * 25  # 450 字
    (tmp_path / f"script_{_D}.json").write_text(json.dumps(script), encoding="utf-8")
    assert validate_research_artifacts(tmp_path, _D) == []


def test_validate_includes_soft_variety_errors_and_can_skip_them(tmp_path):
    _write_valid_artifacts(tmp_path)
    script = json.loads((tmp_path / f"script_{_D}.json").read_text())
    script["gags"] = []  # 違反 S7
    (tmp_path / f"script_{_D}.json").write_text(json.dumps(script), encoding="utf-8")
    assert any("gags" in e for e in validate_research_artifacts(tmp_path, _D))
    assert validate_research_artifacts(tmp_path, _D, include_soft=False) == []


def test_validate_compares_against_yesterday_script(tmp_path):
    _write_valid_artifacts(tmp_path)
    yesterday = _D - dt.timedelta(days=1)
    (tmp_path / f"script_{yesterday}.json").write_text(
        (tmp_path / f"script_{_D}.json").read_text(), encoding="utf-8"
    )
    errors = validate_research_artifacts(tmp_path, _D)
    assert any("段型序列" in e for e in errors)


def test_soft_errors_retry_then_ship_anyway(tmp_path):
    settings = _settings(tmp_path)
    calls: list[str] = []

    def no_gags(prompt: str) -> None:
        calls.append(prompt)
        _write_valid_artifacts(settings.artifacts_dir)
        path = settings.artifacts_dir / f"script_{_D}.json"
        script = json.loads(path.read_text())
        script["gags"] = []
        path.write_text(json.dumps(script), encoding="utf-8")

    assert run_local_research(_D, settings, invoke=no_gags, max_attempts=2) is True
    assert len(calls) == 2 and "gags" in calls[1]


def test_prompt_includes_recent_history_block(tmp_path):
    settings = _settings(tmp_path)
    _write_valid_artifacts(settings.artifacts_dir)
    yesterday = _D - dt.timedelta(days=1)
    (settings.artifacts_dir / f"script_{yesterday}.json").write_text(
        (settings.artifacts_dir / f"script_{_D}.json").read_text(), encoding="utf-8"
    )
    (settings.artifacts_dir / f"script_{_D}.json").unlink()
    calls: list[str] = []

    def fake_invoke(prompt: str) -> None:
        calls.append(prompt)
        _write_valid_artifacts(settings.artifacts_dir)

    run_local_research(_D, settings, invoke=fake_invoke)
    assert "最近 1 個交易日的影片" in calls[0]
    assert str(yesterday) in calls[0]
    assert "pmb validate-research" in calls[0]


@contextmanager
def _warnings():
    """收集 loguru 的 WARNING 以上訊息。"""
    messages: list[str] = []
    handler = logger.add(lambda m: messages.append(m.record["message"]), level="WARNING")
    try:
        yield messages
    finally:
        logger.remove(handler)


def _outputs(settings) -> list[Path]:
    arts = settings.artifacts_dir
    return [arts / f"brief_{_D}.json", arts / f"script_{_D}.json", arts / f"report_{_D}.md",
            settings.state_dir / "thesis.json"]


def _write_soft_only_artifacts(settings) -> None:
    """合法但有軟錯(沒有 gags)的產物 + thesis 更新。"""
    _write_valid_artifacts(settings.artifacts_dir)
    path = settings.artifacts_dir / f"script_{_D}.json"
    script = json.loads(path.read_text())
    script["gags"] = []
    path.write_text(json.dumps(script), encoding="utf-8")
    (settings.state_dir / "thesis.json").write_text('{"attempt": 1}', encoding="utf-8")


def test_broken_crashing_retry_restores_last_shippable_attempt(tmp_path):
    """第 1 次只有軟錯(可出片);第 2 次改寫到一半就逾時、把 script 寫壞 → 還原第 1 次的產物出片。"""
    settings = _settings(tmp_path)
    calls: list[str] = []
    first: dict[Path, bytes] = {}

    def invoke(prompt: str) -> None:
        calls.append(prompt)
        if len(calls) == 1:
            _write_soft_only_artifacts(settings)
            first.update({p: p.read_bytes() for p in _outputs(settings)})
            return
        (settings.artifacts_dir / f"script_{_D}.json").write_text('{"segments": [', "utf-8")
        (settings.state_dir / "thesis.json").write_text('{"attempt": 2, ', encoding="utf-8")
        raise subprocess.TimeoutExpired("claude", 2100)

    with _warnings() as warned:
        assert run_local_research(_D, settings, invoke=invoke, max_attempts=2)
    assert len(calls) == 2
    restored = {p: p.read_bytes() for p in _outputs(settings)}
    thesis = settings.state_dir / "thesis.json"
    assert restored[thesis] == first[thesis]  # thesis 不在標點正規化範圍，位元組一模一樣
    for path in _outputs(settings)[:3]:  # brief/script/report：還原後的內容 = 第 1 次 + 全形標點
        if path.suffix == ".json":
            assert json.loads(restored[path]) == zh_punct_obj(json.loads(first[path]))
        else:
            assert restored[path].decode("utf-8") == zh_punct(first[path].decode("utf-8"))
    assert validate_research_artifacts(settings.artifacts_dir, _D, include_soft=False) == []
    assert any("還原" in m for m in warned)


def test_fallback_warning_names_agent_crash_not_soft_rules(tmp_path):
    """最後一次 agent 逾時但產物合法且規則全過:WARNING 要講 agent 失敗,不能說「軟規則仍未全過」。"""
    settings = _settings(tmp_path)
    calls: list[str] = []

    def invoke(prompt: str) -> None:
        calls.append(prompt)
        if len(calls) == 1:
            _write_soft_only_artifacts(settings)
            return
        _write_valid_artifacts(settings.artifacts_dir)  # 修好了,但收尾時逾時
        raise subprocess.TimeoutExpired("claude", 2100)

    with _warnings() as warned:
        assert run_local_research(_D, settings, invoke=invoke, max_attempts=2)
    final = warned[-1]
    assert "agent 執行失敗" in final and "照樣出片" in final
    assert "軟規則仍未全過" not in final


def test_fallback_warning_names_rate_limit_when_nothing_ran(tmp_path):
    """撞額度等不到重置、本次沒跑出新產物,沿用既有合法產物:WARNING 講額度上限。"""
    settings = _settings(tmp_path)
    _write_valid_artifacts(settings.artifacts_dir)  # 例如稍早雲端 routine 已產出

    def invoke(prompt: str) -> None:
        raise RateLimitedError("usage limit", reset_at=None)

    with _warnings() as warned:
        assert run_local_research(_D, settings, invoke=invoke, sleep=lambda s: None)
    final = warned[-1]
    assert "額度上限" in final and "照樣出片" in final
    assert "軟規則仍未全過" not in final


# --- 全形標點正規化（研究產物源頭）---------------------------------------------------
# 模型照 prompt 的寫法產出半形的逗號、冒號、分號、驚嘆號、問號與括號，
# 公開的字幕、標題、報告看起來就不一致。
# 研究一收工（可出片的每條路徑）就把當日 brief/script/report 就地正規化。


def _write_halfwidth_artifacts(settings, *, soft_only: bool = False) -> None:
    """合法產物，文字是模型慣用的半形標點（含不該被動的千分位、時間、網址、行內碼）。"""
    arts = settings.artifacts_dir
    _write_valid_artifacts(arts)
    script_path = arts / f"script_{_D}.json"
    script = json.loads(script_path.read_text())
    script["segments"][0]["vo"] = "測試開場,先看重點:標普收7,670點(昨收),美東8:30公布!"
    script["segments"][0]["headline"] = "測試開場,看這裡"
    if soft_only:
        script["gags"] = []  # 軟錯（S7）：可出片但規則沒全過
    script_path.write_text(json.dumps(script), encoding="utf-8")
    (arts / f"report_{_D}.md").write_text(
        "# 報告\n\n標普收紅,VIX 回落;詳見 [來源](https://x.com/a,b) 與 `pmb run, x`。\n"
        + "內容 " * 200,
        encoding="utf-8",
    )


def _assert_fullwidth_outputs(settings) -> None:
    arts = settings.artifacts_dir
    script = json.loads((arts / f"script_{_D}.json").read_text(encoding="utf-8"))
    expected_vo = "測試開場，先看重點：標普收7,670點（昨收），美東8:30公布！"
    assert script["segments"][0]["vo"] == expected_vo
    assert script["segments"][0]["headline"] == "測試開場，看這裡"
    brief = json.loads((arts / f"brief_{_D}.json").read_text(encoding="utf-8"))
    assert brief["items"][0]["headline"] == "（dry-run 範例）隔夜美股小幅走高，缺乏單一主導敘事"
    report = (arts / f"report_{_D}.md").read_text(encoding="utf-8")
    assert "標普收紅，VIX 回落；詳見 [來源](https://x.com/a,b) 與 `pmb run, x`。" in report
    assert validate_research_artifacts(arts, _D, include_soft=False) == []


def test_run_local_research_normalizes_outputs_to_fullwidth(tmp_path):
    settings = _settings(tmp_path)

    def invoke(prompt: str) -> None:
        _write_halfwidth_artifacts(settings)

    assert run_local_research(_D, settings, invoke=invoke) is True
    _assert_fullwidth_outputs(settings)
    assert validate_research_artifacts(settings.artifacts_dir, _D) == []  # 軟規則也照樣過


def test_soft_only_ship_also_normalizes(tmp_path):
    """重試用盡只剩軟錯、降級出片的路徑也要正規化。"""
    settings = _settings(tmp_path)

    def invoke(prompt: str) -> None:
        _write_halfwidth_artifacts(settings, soft_only=True)

    assert run_local_research(_D, settings, invoke=invoke, max_attempts=1) is True
    _assert_fullwidth_outputs(settings)


def test_restored_shippable_outputs_are_normalized(tmp_path):
    """最後一次把產物寫壞 → 還原第 1 次可出片的產物 → 還原後的產物也要正規化。"""
    settings = _settings(tmp_path)
    calls: list[str] = []

    def invoke(prompt: str) -> None:
        calls.append(prompt)
        if len(calls) == 1:
            _write_halfwidth_artifacts(settings, soft_only=True)
            return
        (settings.artifacts_dir / f"script_{_D}.json").write_text('{"segments": [', "utf-8")
        raise subprocess.TimeoutExpired("claude", 2100)

    assert run_local_research(_D, settings, invoke=invoke, max_attempts=2) is True
    _assert_fullwidth_outputs(settings)


def test_normalization_failure_restores_originals_and_still_ships(tmp_path, monkeypatch):
    """正規化後硬驗證不過（理論上不可能）：還原原始位元組、記 WARNING，這一天照樣出片。"""
    settings = _settings(tmp_path)
    _write_halfwidth_artifacts(settings)
    originals = {p: p.read_bytes() for p in _outputs(settings) if p.exists()}

    def fake_validate(arts, target, *, include_soft=True):
        return [] if include_soft else ["forced failure"]  # 只有正規化後的硬驗證失敗

    monkeypatch.setattr(local_runner, "validate_research_artifacts", fake_validate)
    with _warnings() as warned:
        assert run_local_research(_D, settings, invoke=lambda p: None) is True
    assert {p: p.read_bytes() for p in originals} == originals
    assert any("正規化" in m and "還原" in m for m in warned)


def test_normalize_research_outputs_rewrites_json_and_markdown(tmp_path):
    settings = _settings(tmp_path)
    _write_halfwidth_artifacts(settings)

    assert normalize_research_outputs(settings.artifacts_dir, _D) is True
    _assert_fullwidth_outputs(settings)
    script_path = settings.artifacts_dir / f"script_{_D}.json"
    text = script_path.read_text(encoding="utf-8")
    assert text == json.dumps(json.loads(text), ensure_ascii=False, indent=2) + "\n"
    assert "測試開場" in text  # ensure_ascii=False：中文不轉成 \uXXXX


def test_normalize_research_outputs_is_idempotent(tmp_path):
    settings = _settings(tmp_path)
    _write_halfwidth_artifacts(settings)
    assert normalize_research_outputs(settings.artifacts_dir, _D) is True
    first = {p: p.read_bytes() for p in _outputs(settings) if p.exists()}
    assert normalize_research_outputs(settings.artifacts_dir, _D) is True
    assert {p: p.read_bytes() for p in first} == first


def test_normalize_research_outputs_leaves_unreadable_files_alone(tmp_path):
    """缺檔或 JSON 壞掉：回 False、不動任何檔（交給驗證去報錯，不在這裡丟例外）。"""
    settings = _settings(tmp_path)
    _write_halfwidth_artifacts(settings)
    (settings.artifacts_dir / f"brief_{_D}.json").write_text("{broken", encoding="utf-8")
    before = {p: p.read_bytes() for p in _outputs(settings) if p.exists()}
    with _warnings() as warned:
        assert normalize_research_outputs(settings.artifacts_dir, _D) is False
    assert {p: p.read_bytes() for p in before} == before
    assert warned


def test_normalization_exception_restores_all_three_files(tmp_path, monkeypatch):
    """brief、script 改寫之後才在 report 出錯（任何例外，不只 OSError／ValueError）→ 三份全還原。"""
    settings = _settings(tmp_path)
    _write_halfwidth_artifacts(settings)
    originals = {p: p.read_bytes() for p in _outputs(settings)[:3]}

    def boom(text):
        raise IndexError("injected")

    monkeypatch.setattr(local_runner, "zh_punct", boom)  # Markdown 報告最後處理
    with _warnings() as warned:
        assert normalize_research_outputs(settings.artifacts_dir, _D) is False
    assert {p: p.read_bytes() for p in originals} == originals
    assert any("正規化" in m and "還原" in m for m in warned)


def test_run_local_research_still_ships_when_normalization_raises(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    _write_halfwidth_artifacts(settings)
    originals = {p: p.read_bytes() for p in _outputs(settings)[:3]}

    def boom(text):
        raise IndexError("injected")

    monkeypatch.setattr(local_runner, "zh_punct", boom)
    assert run_local_research(_D, settings, invoke=lambda p: None) is True
    assert {p: p.read_bytes() for p in originals} == originals
