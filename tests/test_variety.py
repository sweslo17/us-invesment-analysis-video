"""反重複與風格軟規則測試(v4 規格 §5)。"""

import datetime as dt
import json

from pmb.research.variety import (
    DayRecord,
    check_gags,
    check_lengths,
    check_numbers,
    check_structure,
    check_variety,
    load_recent_scripts,
    numeric_cores,
    soft_script_errors,
    summarize_recent,
)
from pmb.schemas.script import Script


def _script(middle: list[dict], *, hook_tag="債市日", author="巴菲特", gags=("梗一", "梗二"),
            lesson: str | None = None) -> Script:
    segs = [{"kind": "card", "vo": "開場。", "headline": "殖利率暴走", "tag": hook_tag}]
    segs += middle
    if lesson:
        segs.append({"kind": "card", "vo": "一句白話。", "headline": lesson, "tag": "名詞小教室"})
    segs.append({"kind": "card", "vo": "金句。", "headline": "別人恐懼\n我先看債",
                 "tag": f"{author} 不知道有沒有說過"})
    return Script.model_validate({
        "segments": segs,
        "charts": [{"id": "a", "module": "overnight_vs_close", "params": {}},
                   {"id": "b", "module": "rates_trend", "params": {}}],
        "gags": list(gags),
    })


_CHART_A = {"kind": "chart", "vo": "標普跌0.17%。", "chart_id": "a", "stat": "-0.17%"}
_CHART_B = {"kind": "chart", "vo": "十年期5.26%。", "chart_id": "b", "stat": "5.26%"}
_BIG = {"kind": "bignum", "vo": "十年期5.26%。", "value": "5.26%", "label": "10年期殖利率"}
_DIALOG = {"kind": "dialogue", "lines": [
    {"speaker": "Fed", "voice": "a", "text": "十月不急。"},
    {"speaker": "債市", "voice": "b", "text": "你不急,我急。"}]}


def _day(d: int, script: Script) -> DayRecord:
    return DayRecord(dt.date(2026, 9, d), script)


def test_good_script_with_no_history_passes_everything():
    s = _script([_CHART_A, _BIG, _CHART_B])
    assert soft_script_errors(s, []) == []


def test_structure_requires_hook_quote_and_two_charts():
    s = Script.model_validate({
        "segments": [_CHART_A, _BIG],
        "charts": [{"id": "a", "module": "overnight_vs_close", "params": {}}],
    })
    errors = check_structure(s)
    assert any("hook" in e for e in errors)
    assert any("金句" in e for e in errors)
    assert any("圖表段至少 2" in e for e in errors)


def test_same_kind_sequence_as_recent_day_is_rejected():
    today = _script([_CHART_A, _BIG, _CHART_B])
    same = _script([_CHART_B, _BIG, _CHART_A], hook_tag="別的", author="蒙格")
    errors = check_variety(today, [_day(29, _script([_CHART_A, _DIALOG, _CHART_B])),
                                   _day(28, same)])
    assert any("段型序列" in e and "2026-09-28" in e for e in errors)


def test_sequence_older_than_three_days_is_allowed():
    today = _script([_CHART_A, _BIG, _CHART_B])
    other = _script([_CHART_A, _DIALOG, _CHART_B], hook_tag="x", author="蒙格")
    recent = [_day(29, other), _day(28, other), _day(27, other), _day(26, today)]
    assert not any("段型序列" in e for e in check_variety(today, recent))


def test_first_content_same_as_yesterday_is_rejected():
    today = _script([_CHART_A, _BIG, _CHART_B])
    yesterday = _script([_CHART_A, _DIALOG, _CHART_B], hook_tag="x", author="蒙格")
    errors = check_variety(today, [_day(29, yesterday)])
    assert any("hook 後第一段" in e and "overnight_vs_close" in e for e in errors)


def test_needs_a_new_kind_and_a_different_set_than_yesterday():
    no_new = _script([_CHART_A, _CHART_B])
    assert any("至少用 1 段新段型" in e for e in check_variety(no_new, []))
    today = _script([_CHART_B, _BIG, _CHART_A])
    yesterday = _script([_CHART_A, _CHART_B, _BIG], hook_tag="x", author="蒙格")
    assert any("新段型組合" in e for e in check_variety(today, [_day(29, yesterday)]))


def test_quote_author_kicker_and_lesson_repeats_are_rejected():
    today = _script([_CHART_B, _BIG, _CHART_A], author="彼得·林區", lesson="期限溢酬")
    yesterday = _script([_CHART_A, _DIALOG, _CHART_B], author="彼得林區")  # 同一人、同 kicker
    older = _script([_CHART_A, _DIALOG, _CHART_B], hook_tag="x", author="蒙格", lesson="期限溢酬")
    errors = check_variety(today, [_day(29, yesterday), _day(10, older)])
    assert any("金句名人" in e for e in errors)
    assert any("hook 小標" in e for e in errors)
    assert any("名詞小教室「期限溢酬」" in e and "2026-09-10" in e for e in errors)


def test_gags_minimum():
    assert check_gags(_script([_CHART_A, _BIG, _CHART_B], gags=("只有一個",)))
    assert check_gags(_script([_CHART_A, _BIG, _CHART_B])) == []


def test_lengths_over_limit_are_reported_per_field():
    long_dialog = {"kind": "dialogue", "lines": [
        {"speaker": "聯準會主席辦公室", "voice": "a",
         "text": "這一句話真的非常非常非常非常非常長喔"},
        {"speaker": "債市", "voice": "b", "text": "嗯。"}]}
    errors = check_lengths(_script([_CHART_A, long_dialog, _CHART_B]))
    assert any("speaker" in e for e in errors) and any("text" in e for e in errors)


def test_numbers_on_screen_must_be_spoken():
    bad = {"kind": "bignum", "vo": "十年期殖利率創新高。", "value": "5.26%", "label": "10年期"}
    errors = check_numbers(_script([_CHART_A, bad, _CHART_B]))
    assert any("5.26%" in e for e in errors)
    comma = {"kind": "bignum", "vo": "標普收7670點。", "value": "7,670點", "label": "標普"}
    assert check_numbers(_script([_CHART_A, comma, _CHART_B])) == []


def test_numeric_cores_strip_sign_commas_and_units():
    assert numeric_cores("+16.2萬") == ["16.2"]
    assert numeric_cores("-0.27%") == ["0.27"]
    assert numeric_cores("7,670點、5.26%") == ["7670", "5.26"]
    assert numeric_cores("創新高") == []


def test_load_recent_scripts_newest_first_skips_broken_and_future(tmp_path):
    good = _script([_CHART_A, _BIG, _CHART_B])
    for d in ("2026-09-25", "2026-09-28", "2026-09-30"):
        (tmp_path / f"script_{d}.json").write_text(good.model_dump_json(), encoding="utf-8")
    (tmp_path / "script_2026-09-29.json").write_text("{broken", encoding="utf-8")
    recent = load_recent_scripts(tmp_path, dt.date(2026, 9, 30), 5)
    assert [r.date for r in recent] == [dt.date(2026, 9, 28), dt.date(2026, 9, 25)]
    assert load_recent_scripts(tmp_path / "missing", dt.date(2026, 9, 30), 5) == []


def test_summarize_recent_lists_sequence_hook_quote_gags_and_lessons():
    s = _script([_CHART_A, _BIG, _CHART_B], lesson="期限溢酬", gags=("Fed 不急債市急",))
    text = summarize_recent([_day(29, s)])
    assert "2026-09-29" in text
    assert "card → chart:overnight_vs_close → bignum → chart:rates_trend → card → card" in text
    assert "殖利率暴走" in text and "債市日" in text
    assert "巴菲特" in text and "Fed 不急債市急" in text
    assert "期限溢酬" in text
    assert summarize_recent([]) == ""


def test_legacy_history_scripts_work_with_rules():
    from pathlib import Path

    raw = json.loads((Path(__file__).parent / "fixtures" / "legacy_script_2026-09-29.json")
                     .read_text(encoding="utf-8"))
    legacy = Script.model_validate(raw)
    today = _script([_CHART_A, _BIG, _CHART_B])
    check_variety(today, [_day(29, legacy)])  # 不得拋例外
    assert "2026-09-29" in summarize_recent([_day(29, legacy)])
