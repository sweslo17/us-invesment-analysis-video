"""CLI 純邏輯測試:fetch 目標日解析(休市 skip)、快照文字輸出、一鍵作業前置守衛。"""

import datetime as dt
import json
import types

from pmb import cli
from pmb.cli import format_snapshot, resolve_fetch_target, today_blockers
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


def test_cover_spec_prefers_hook_headline_and_first_stat():
    """封面 = 開場鉤子字卡的大標 + 第一個圖表段的大數字(有就用),不再是日期字卡。"""
    from pmb.cli import cover_spec
    from pmb.schemas.script import Script

    script = Script.model_validate({
        "segments": [
            {"vo": "開場。", "headline": "鷹鴿吵不完", "tag": "今日盤前",
             "t_start": 0, "duration": 1},
            {"vo": "圖。", "chart_id": "c", "stat": "+1.06%", "stat_label": "標普昨收",
             "t_start": 1, "duration": 1},
        ],
        "charts": [{"id": "c", "module": "leverage_decay", "params": {}}],
    })
    spec = cover_spec(script)
    assert spec == {
        "headline": "鷹鴿吵不完", "tag": "今日盤前", "stat": "+1.06%", "accent_index": 0,
    }


def test_cover_spec_without_headline_card_is_none():
    from pmb.cli import cover_spec
    from pmb.schemas.script import Script

    script = Script.model_validate({
        "segments": [{"vo": "圖。", "chart_id": "c", "t_start": 0, "duration": 1}],
        "charts": [{"id": "c", "module": "leverage_decay", "params": {}}],
    })
    assert cover_spec(script) is None


def test_cover_spec_takes_bignum_value_when_it_comes_first():
    from pmb.cli import cover_spec
    from pmb.schemas.script import Script

    script = Script.model_validate({
        "segments": [
            {"vo": "開場。", "headline": "債市暴走", "tag": "債市日"},
            {"kind": "bignum", "vo": "5.26%。", "value": "5.26%", "label": "10年期"},
            {"vo": "圖。", "chart_id": "c", "stat": "+1.06%"},
        ],
        "charts": [{"id": "c", "module": "leverage_decay", "params": {}}],
    })
    assert cover_spec(script)["stat"] == "5.26%"


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


def test_render_cover_normalizes_halfwidth_punctuation(tmp_path, monkeypatch):
    """封面是公開圖片：大標與小標的半形標點在出口轉全形，大數字維持原樣。"""
    arts = tmp_path / "artifacts"
    arts.mkdir()
    script = {
        "segments": [
            {"vo": "開場。", "headline": "債市暴走,Fed不急", "tag": "今日盤前:速報"},
            {"vo": "圖。", "chart_id": "c", "stat": "7,670", "stat_label": "標普(昨收)"},
        ],
        "charts": [{"id": "c", "module": "leverage_decay", "params": {}}],
    }
    (arts / "script_2026-09-30.json").write_text(json.dumps(script), encoding="utf-8")
    captured: dict = {}

    def fake_render(out, headline, **kwargs):
        captured.update(out=out, headline=headline, **kwargs)

    monkeypatch.setattr("pmb.charts.cards.render_headline_card", fake_render)
    settings = types.SimpleNamespace(artifacts_dir=arts, channel_name="美股早發車")
    cover = cli._render_cover(dt.date(2026, 9, 30), settings)
    assert cover == arts / "cover_2026-09-30.png"
    assert captured["headline"] == "債市暴走，Fed不急"
    assert captured["tag"] == "今日盤前：速報"
    assert captured["stat"] == "7,670"
