"""CLI 純邏輯測試:fetch 目標日解析(休市 skip)、快照文字輸出、一鍵作業前置守衛。"""

import datetime as dt

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
