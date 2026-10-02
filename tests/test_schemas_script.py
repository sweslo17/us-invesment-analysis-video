"""script schema(規格 §6.3)測試:segment↔chart 交叉驗證、時長。"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pmb.schemas.script import (
    BignumSegment,
    CardSegment,
    ChartSegment,
    DialogueSegment,
    RecapSegment,
    Script,
    SplitSegment,
)


def _valid_script() -> dict:
    return {
        "segments": [
            {"vo": "隔夜四大指數收紅,費半領漲", "chart_id": "idx", "t_start": 0, "duration": 12},
            {"vo": "Fed 轉鷹,點陣圖暗示升息", "chart_id": "lev", "t_start": 12, "duration": 18},
        ],
        "charts": [
            {"id": "idx", "module": "index_overnight_grid", "params": {}},
            {"id": "lev", "module": "leverage_decay", "params": {}},
        ],
    }


def test_valid_script_parses_and_reports_total_duration():
    script = Script.model_validate(_valid_script())
    assert len(script.segments) == 2
    assert script.total_duration == pytest.approx(30.0)
    assert script.coverage_gaps == []  # 預設無缺口


def test_script_records_chart_coverage_gaps():
    data = _valid_script()
    data["coverage_gaps"] = ["想講『信用利差擴大』但沒有對應圖表模組"]
    script = Script.model_validate(data)
    assert "信用利差" in script.coverage_gaps[0]


def test_segment_chart_id_must_reference_a_chart():
    data = _valid_script()
    data["segments"][0]["chart_id"] = "nope"
    with pytest.raises(ValidationError):
        Script.model_validate(data)


def test_duplicate_chart_ids_are_rejected():
    data = _valid_script()
    data["charts"][1]["id"] = "idx"  # 與第一張重複
    with pytest.raises(ValidationError):
        Script.model_validate(data)


def test_unknown_chart_module_is_rejected():
    data = _valid_script()
    data["charts"][0]["module"] = "hologram"
    with pytest.raises(ValidationError):
        Script.model_validate(data)


def test_headline_card_segment_is_valid_without_chart():
    data = _valid_script()
    data["segments"].insert(
        0, {"vo": "Fed 轉鷹了!", "headline": "Fed 轉鷹 🦅", "t_start": 0, "duration": 2}
    )
    script = Script.model_validate(data)
    assert script.segments[0].headline == "Fed 轉鷹 🦅"
    assert script.segments[0].kind == "card"


def test_segment_must_have_chart_or_headline():
    data = _valid_script()
    data["segments"][0] = {"vo": "空的", "t_start": 0, "duration": 2}
    with pytest.raises(ValidationError):
        Script.model_validate(data)


def test_segment_cannot_have_both_chart_and_headline():
    data = _valid_script()
    data["segments"][0]["headline"] = "兩個都填"
    with pytest.raises(ValidationError):
        Script.model_validate(data)


def test_chart_segment_accepts_optional_stat_callout():
    """圖表段可帶一個「大數字 callout」(stat + stat_label),合成時疊在圖下方留白處。"""
    data = _valid_script()
    data["segments"][0]["stat"] = "+1.06%"
    data["segments"][0]["stat_label"] = "標普昨收"
    script = Script.model_validate(data)
    assert script.segments[0].stat == "+1.06%"
    assert script.segments[0].stat_label == "標普昨收"
    # 沒填就是 None(舊 script 相容)
    assert script.segments[1].stat is None and script.segments[1].stat_label is None


# --- v4:kind union ---
_FIXTURES = Path(__file__).parent / "fixtures"


def test_legacy_scripts_without_kind_still_load_and_infer_kinds():
    for name in ("legacy_script_2026-09-29.json", "legacy_script_2026-09-30.json"):
        data = json.loads((_FIXTURES / name).read_text(encoding="utf-8"))
        script = Script.model_validate(data)
        for raw, seg in zip(data["segments"], script.segments, strict=True):
            expected = "chart" if raw.get("chart_id") else "card"
            assert seg.kind == expected
        assert script.gags == []


def test_legacy_card_with_explicit_null_chart_id_is_card():
    data = _valid_script()
    data["segments"][0] = {"vo": "x", "headline": "標題", "chart_id": None,
                           "t_start": 0, "duration": 1}
    assert isinstance(Script.model_validate(data).segments[0], CardSegment)


def test_all_new_kinds_parse_with_explicit_kind():
    data = _valid_script()
    data["segments"] += [
        {"kind": "dialogue", "lines": [
            {"speaker": "Fed", "voice": "a", "text": "十月不急。"},
            {"speaker": "債市", "voice": "b", "text": "你不急,我急。"},
        ]},
        {"kind": "split", "vo": "好消息是Fed不急。壞消息是債市沒在聽。",
         "top": {"label": "好消息", "text": "Fed說不急", "tone": "good"},
         "bottom": {"label": "壞消息", "text": "債市沒在聽", "stat": "5.26%", "tone": "bad"}},
        {"kind": "bignum", "vo": "十年期5.26%。", "value": "5.26%", "label": "10年期殖利率"},
        {"kind": "recap", "vo": "昨天說看威廉斯。",
         "rows": [{"ask": "威廉斯怎麼說", "result": "十月不急", "mark": "yes"}]},
    ]
    script = Script.model_validate(data)
    kinds = [type(s) for s in script.segments[-4:]]
    assert kinds == [DialogueSegment, SplitSegment, BignumSegment, RecapSegment]
    # 序列化後帶 kind,重載一致
    again = Script.model_validate_json(script.model_dump_json())
    assert [s.kind for s in again.segments] == [s.kind for s in script.segments]


def test_unknown_kind_is_rejected():
    data = _valid_script()
    data["segments"][0]["kind"] = "hologram"
    with pytest.raises(ValidationError):
        Script.model_validate(data)


def test_dialogue_needs_two_speakers_and_consistent_voices():
    base = {"kind": "dialogue", "vo": ""}
    one_speaker = {**base, "lines": [
        {"speaker": "Fed", "voice": "a", "text": "一"},
        {"speaker": "Fed", "voice": "a", "text": "二"}]}
    flip_voice = {**base, "lines": [
        {"speaker": "Fed", "voice": "a", "text": "一"},
        {"speaker": "債市", "voice": "b", "text": "二"},
        {"speaker": "Fed", "voice": "b", "text": "三"}]}
    too_many = {**base, "lines": [
        {"speaker": f"S{i}", "voice": "a" if i % 2 else "b", "text": "x"} for i in range(5)]}
    for seg in (one_speaker, flip_voice, too_many):
        data = _valid_script()
        data["segments"].append(seg)
        with pytest.raises(ValidationError):
            Script.model_validate(data)


def test_recap_rows_between_one_and_three():
    for rows in ([], [{"ask": "a", "result": "b", "mark": "yes"}] * 4):
        data = _valid_script()
        data["segments"].append({"kind": "recap", "vo": "x。", "rows": rows})
        with pytest.raises(ValidationError):
            Script.model_validate(data)


def test_spoken_text_and_display_numbers():
    d = DialogueSegment(lines=[
        {"speaker": "Fed", "voice": "a", "text": "不急。"},
        {"speaker": "債市", "voice": "b", "text": "我急。"}], vo="旁白。")
    assert d.spoken_text == "不急。我急。旁白。"
    assert d.display_numbers == []
    c = ChartSegment(vo="漲1.06%", chart_id="c", stat="+1.06%")
    assert c.display_numbers == ["+1.06%"]
    s = SplitSegment(vo="x。y。", top={"label": "a", "text": "b", "stat": "5%"},
                     bottom={"label": "c", "text": "d"})
    assert s.display_numbers == ["5%"]
    b = BignumSegment(vo="5.26%", value="5.26%", label="殖利率")
    assert b.display_numbers == ["5.26%"]
    r = RecapSegment(vo="x。", rows=[{"ask": "a", "result": "沒守住5.2%", "mark": "no"}])
    assert r.display_numbers == ["沒守住5.2%"]


def test_display_stats_pairs_label_with_value_per_segment_kind():
    """封面要「標籤 + 數字」成對：圖表段取 stat_label、全屏大數字取 label、好壞格子取各格 label。"""
    d = DialogueSegment(lines=[
        {"speaker": "Fed", "voice": "a", "text": "不急。"},
        {"speaker": "債市", "voice": "b", "text": "我急。"}])
    assert d.display_stats == []
    c = ChartSegment(vo="x", chart_id="c", stat="+1.06%", stat_label="標普昨收")
    assert c.display_stats == [("標普昨收", "+1.06%")]
    assert ChartSegment(vo="x", chart_id="c", stat="+1.06%").display_stats == [(None, "+1.06%")]
    assert ChartSegment(vo="x", chart_id="c", stat_label="沒有數字").display_stats == []
    b = BignumSegment(vo="x", value="5.26%", label="殖利率")
    assert b.display_stats == [("殖利率", "5.26%")]
    s = SplitSegment(vo="x。y。", top={"label": "利多", "text": "b", "stat": "5%"},
                     bottom={"label": "利空", "text": "d"})
    assert s.display_stats == [("利多", "5%")]  # 沒有 stat 的格子不列
    s2 = SplitSegment(vo="x。y。", top={"label": "利多", "text": "b", "stat": "5%"},
                      bottom={"label": "利空", "text": "d", "stat": "-3%"})
    assert s2.display_stats == [("利多", "5%"), ("利空", "-3%")]
    r = RecapSegment(vo="x。", rows=[{"ask": "a", "result": "沒守住5.2%", "mark": "no"}])
    assert r.display_stats == []  # 對帳結果是列的結論，不當封面大數字


def test_hook_is_the_first_card_even_when_it_is_not_at_index_zero():
    data = _valid_script()
    data["segments"] += [
        {"vo": "開場。", "headline": "債市暴走", "tag": "債市日"},
        {"vo": "收尾。", "headline": "金句\n對句"},
    ]
    script = Script.model_validate(data)
    index, seg = script.hook()
    assert index == 2
    assert isinstance(seg, CardSegment) and seg.headline == "債市暴走"


def test_hook_is_none_when_the_script_has_no_card():
    assert Script.model_validate(_valid_script()).hook() is None
