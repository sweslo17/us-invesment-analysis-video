"""CLI 純邏輯測試:fetch 目標日解析(休市 skip)、快照文字輸出、一鍵作業前置守衛。"""

import datetime as dt
import json
import types
from pathlib import Path

import pytest
from loguru import logger

from pmb import cli
from pmb.cli import format_snapshot, resolve_fetch_target, today_blockers
from pmb.schemas.script import Script
from pmb.schemas.snapshot import Quote, RegimeMetrics, Snapshot


def test_today_blockers_lists_all_when_empty(tmp_path):
    blockers = today_blockers(tmp_path, "2026-06-18")
    assert "取數" in blockers
    assert any("brief" in b for b in blockers)
    assert any("講稿" in b for b in blockers)


def test_today_blockers_empty_when_prerequisites_present(tmp_path):
    for name in ("snapshot_2026-06-18.json", "brief_2026-06-18.json", "script_2026-06-18.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    assert today_blockers(tmp_path, "2026-06-18") == []


def test_today_blockers_partial_still_blocks(tmp_path):
    (tmp_path / "snapshot_2026-06-18.json").write_text("{}", encoding="utf-8")
    assert today_blockers(tmp_path, "2026-06-18")  # 缺研究 → 非空


def test_resolve_fetch_target_today_trading_day_returns_today():
    assert resolve_fetch_target(dt.date(2026, 6, 18), None) == dt.date(2026, 6, 18)


def test_resolve_fetch_target_today_holiday_returns_none_to_skip():
    # 2026-06-19 Juneteenth 休市 → 應 skip
    assert resolve_fetch_target(dt.date(2026, 6, 19), None) is None


def test_resolve_fetch_target_explicit_date_overrides_skip():
    assert resolve_fetch_target(dt.date(2026, 6, 19), dt.date(2026, 6, 18)) == dt.date(2026, 6, 18)


def test_format_snapshot_includes_key_numbers():
    snap = Snapshot(
        session_date=dt.date(2026, 6, 18),
        generated_at=dt.datetime(2026, 6, 19, 11, 30, tzinfo=dt.UTC),
        futures=[Quote(ticker="ES=F", name="S&P 500 期貨", last=110.0, previous_close=100.0)],
        volatility=Quote(ticker="^VIX", name="VIX", last=20.0, previous_close=18.0),
        regime=RegimeMetrics(vix=20.0, realized_vol_20d=0.15),
    )
    text = format_snapshot(snap)
    assert "2026-06-18" in text
    assert "ES=F" in text
    assert "10.0" in text  # +10% overnight
    assert "VIX" in text


def test_validate_research_command_reports_errors_and_rc(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_settings", lambda: types.SimpleNamespace(artifacts_dir=tmp_path))
    rc = cli.main(["validate-research", "--date", "2026-07-10"])
    out = capsys.readouterr().out
    assert rc == 1 and "缺 brief_2026-07-10.json" in out


def test_research_prompt_command_includes_recent_history_block(tmp_path, monkeypatch, capsys):
    """pmb research-prompt 印的 prompt 要與本機研究同一份:含「最近 N 個交易日」回顧塊。"""
    from pmb.schemas.script import Script

    arts, state = tmp_path / "artifacts", tmp_path / "state"
    arts.mkdir()
    state.mkdir()
    day = dt.date(2026, 7, 10)
    snap = Snapshot(session_date=day, generated_at=dt.datetime.now(tz=dt.UTC))
    (arts / f"snapshot_{day}.json").write_text(snap.model_dump_json(), encoding="utf-8")
    yesterday = Script.model_validate({
        "segments": [{"kind": "card", "vo": "開場。", "headline": "昨天的鉤子", "tag": "債市日"}],
        "charts": [],
    })
    (arts / "script_2026-07-09.json").write_text(yesterday.model_dump_json(), encoding="utf-8")
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("研究任務模板", encoding="utf-8")
    settings = types.SimpleNamespace(artifacts_dir=arts, state_dir=state, prompt_path=prompt_path,
                                     ensure_dirs=lambda: None)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    assert cli.main(["research-prompt", "--date", str(day)]) == 0
    out = capsys.readouterr().out
    assert "研究任務模板" in out and "最近 1 個交易日的影片" in out and "昨天的鉤子" in out


def test_voice_map_maps_narrator_and_both_roles_to_their_settings():
    """voice_key → edge-tts 聲線(規格 §4、§9):旁白 / A 角 / B 角各自對到設定,三個 key 都要有。"""
    from typing import get_args

    from pmb.schemas.script import VoiceKey

    settings = types.SimpleNamespace(tts_voice="zh-TW-HsiaoChenNeural",
                                     tts_voice_a="zh-TW-YunJheNeural",
                                     tts_voice_b="zh-TW-HsiaoYuNeural")
    voices = cli.voice_map(settings)
    assert voices == {"narrator": "zh-TW-HsiaoChenNeural", "a": "zh-TW-YunJheNeural",
                      "b": "zh-TW-HsiaoYuNeural"}
    assert set(voices) == set(get_args(VoiceKey))


def _cover_settings(arts):
    return types.SimpleNamespace(artifacts_dir=arts, channel_name="頻道甲", video_font="字型乙")


def _write_script(arts, segments):
    charts = [{"id": "c", "module": "leverage_decay", "params": {}}]
    script = {"segments": segments, "charts": charts}
    (arts / "script_2026-09-30.json").write_text(json.dumps(script), encoding="utf-8")


def test_render_cover_normalizes_halfwidth_punctuation(tmp_path, monkeypatch):
    """封面是公開圖片：大標與小標的半形標點在出口轉全形，大數字維持原樣；字型與頻道名取自設定。"""
    arts = tmp_path / "artifacts"
    arts.mkdir()
    _write_script(arts, [
        {"vo": "開場。", "headline": "債市暴走,Fed不急", "tag": "今日盤前:速報"},
        {"vo": "圖。", "chart_id": "c", "stat": "7,670", "stat_label": "標普(昨收)"},
    ])
    captured: dict = {}

    def fake_render(spec, out, **kwargs):
        captured.update(spec=spec, out=out, **kwargs)
        return Path(out)

    monkeypatch.setattr(cli, "render_cover", fake_render)
    cover = cli._render_cover(dt.date(2026, 9, 30), _cover_settings(arts))
    assert cover == arts / "cover_2026-09-30.png"
    spec = captured["spec"]
    assert spec.headline == "債市暴走，Fed不急"
    assert spec.kicker == "今日盤前：速報"
    assert (spec.stat_label, spec.stat) == ("標普（昨收）", "7,670")
    assert spec.date == dt.date(2026, 9, 30)
    assert captured["out"] == arts / "cover_2026-09-30.png"
    assert (captured["font"], captured["channel"]) == ("字型乙", "頻道甲")


def test_render_cover_without_script_or_hook_is_none(tmp_path, monkeypatch):
    arts = tmp_path / "artifacts"
    arts.mkdir()
    monkeypatch.setattr(cli, "render_cover", lambda *a, **k: pytest.fail("不該渲染"))
    settings = _cover_settings(arts)
    assert cli._render_cover(dt.date(2026, 9, 30), settings) is None  # 沒有講稿
    _write_script(arts, [{"vo": "圖。", "chart_id": "c"}])  # 有講稿但沒有字卡
    assert cli._render_cover(dt.date(2026, 9, 30), settings) is None


def test_render_cover_failure_warns_and_returns_none(tmp_path, monkeypatch):
    """封面渲染失敗（ffmpeg 掛了）只記 WARNING、回 None，上傳照常進行、只是沒有自訂縮圖。"""
    arts = tmp_path / "artifacts"
    arts.mkdir()
    _write_script(arts, [{"vo": "開場。", "headline": "債市暴走", "tag": "債市日"}])

    def boom(spec, out, **kwargs):
        raise RuntimeError("ffmpeg 失敗(rc=1)")

    monkeypatch.setattr(cli, "render_cover", boom)
    messages: list[str] = []
    sink = logger.add(lambda m: messages.append(m.record["level"].name + " " + m.record["message"]),
                      level="WARNING")
    try:
        assert cli._render_cover(dt.date(2026, 9, 30), _cover_settings(arts)) is None
    finally:
        logger.remove(sink)
    assert any(m.startswith("WARNING") and "ffmpeg" in m for m in messages)


@pytest.mark.parametrize("enabled", [True, False])
def test_cmd_assemble_passes_the_banner_setting(tmp_path, monkeypatch, enabled):
    """VIDEO_BANNER 設定原樣帶進 assemble_video（今日主標橫幅的開關）。"""
    day = dt.date(2026, 9, 30)
    script = Script.model_validate({
        "segments": [{"kind": "card", "vo": "開場。", "headline": "債市暴走", "tag": "債市日"}],
        "charts": [],
    })
    snapshot = Snapshot(session_date=day, generated_at=dt.datetime(2026, 9, 30, 12, tzinfo=dt.UTC))
    (tmp_path / f"script_{day}.json").write_text(script.model_dump_json(), encoding="utf-8")
    (tmp_path / f"snapshot_{day}.json").write_text(snapshot.model_dump_json(), encoding="utf-8")
    settings = types.SimpleNamespace(
        artifacts_dir=tmp_path, ensure_dirs=lambda: None, video_font="F", channel_name="頻道",
        bgm_gain_db=-14.0, slogan_intro="口號", slogan_outro="收尾", sting_enable=True,
        video_banner=enabled,
    )
    captured: dict = {}
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "assemble_video", lambda *args, **kwargs: captured.update(kwargs))
    monkeypatch.setattr(cli, "probe_duration", lambda path: 1.0)
    assert cli.main(["assemble", "--date", str(day), "--dry-run"]) == 0
    assert captured["banner"] is enabled
