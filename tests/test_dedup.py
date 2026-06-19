"""horizon-aware 去重測試(規格 §5.5):短期狠去重,中長期當 open thread 保留。"""

import datetime as dt

from pmb.research.dedup import dedup_items, load_previous_brief
from pmb.schemas.brief import Brief, BriefItem


def _item(headline: str, horizon: str) -> BriefItem:
    return BriefItem(
        headline=headline,
        horizon=horizon,
        vs_thesis="confirms",
        materiality=2,
        confidence="developing",
        audience_value="...",
    )


def test_short_term_duplicate_is_dropped_case_insensitive():
    yesterday = [_item("Fed 維持利率", "ST")]
    today = [_item("fed 維持利率 ", "ST")]  # 大小寫 / 空白不同,視為重複
    assert dedup_items(today, yesterday) == []


def test_short_term_new_item_is_kept():
    yesterday = [_item("Fed 維持利率", "ST")]
    today = [_item("非農超預期", "ST")]
    out = dedup_items(today, yesterday)
    assert [i.headline for i in out] == ["非農超預期"]


def test_long_term_duplicate_is_kept_as_open_thread():
    yesterday = [_item("AI capex 趨勢", "LT")]
    today = [_item("AI capex 趨勢", "LT")]
    out = dedup_items(today, yesterday)
    assert len(out) == 1  # 中長期不因昨天提過而被蓋掉


def test_empty_yesterday_keeps_everything():
    today = [_item("a", "ST"), _item("b", "MT")]
    assert len(dedup_items(today, [])) == 2


def _minimal_brief(date_str: str) -> Brief:
    return Brief.model_validate(
        {
            "date": date_str,
            "regime": {
                "vol": "normal",
                "rates": "stable",
                "stock_bond_corr": "neutral",
                "breadth": "mixed",
            },
            "thesis_delta": {"changed": False},
            "lead_horizon": "ST",
        }
    )


def test_load_previous_brief_picks_most_recent_before_date(tmp_path):
    for d in ("2026-06-15", "2026-06-16", "2026-06-17"):
        (tmp_path / f"brief_{d}.json").write_text(
            _minimal_brief(d).model_dump_json(), encoding="utf-8"
        )
    prev = load_previous_brief(tmp_path, dt.date(2026, 6, 18))
    assert prev is not None
    assert prev.date == dt.date(2026, 6, 17)


def test_load_previous_brief_none_when_no_earlier_brief(tmp_path):
    (tmp_path / "brief_2026-06-18.json").write_text(
        _minimal_brief("2026-06-18").model_dump_json(), encoding="utf-8"
    )
    assert load_previous_brief(tmp_path, dt.date(2026, 6, 18)) is None
