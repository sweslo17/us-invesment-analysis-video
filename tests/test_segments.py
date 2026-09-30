"""段型 renderer 共用機制測試:句子計畫、停頓、時間軸、registry(不跑 ffmpeg)。"""

import random
import re
from pathlib import Path

import pytest

from pmb.schemas.script import BignumSegment, DialogueSegment, RecapSegment, SplitSegment
from pmb.video.ass import POP_IN, ass_color, rounded_rect, text_event
from pmb.video.captions import NO_LINE_START, is_beat, split_sentences, strip_beat
from pmb.video.segments.base import (
    BEAT_GAP,
    GAP,
    TAIL,
    RenderContext,
    Take,
    Utterance,
    append_outro,
    caption_events,
    plan_vo,
    segment_duration,
    take_starts,
)
from pmb.video.segments.bignum import count_up_frames, parse_number, value_font_size
from pmb.video.segments.dialogue import bubble_layout, speakable_lines
from pmb.video.segments.recap import result_layout, row_times
from pmb.video.segments.registry import renderer_for
from pmb.video.segments.split import panel_text_layout, reveal_times
from pmb.video.segments.sting import StingSegment
from pmb.video.textfit import FLOOR_SIZE, fit_lines, fit_one_line, line_px, wrap_px


def test_ellipsis_ends_a_sentence_and_marks_a_beat():
    out = split_sentences("好消息是Fed說不急……壞消息是債市沒在聽。")
    assert out == ["好消息是Fed說不急……", "壞消息是債市沒在聽。"]
    assert is_beat(out[0]) and not is_beat(out[1])
    assert is_beat("先別急⋯⋯」")
    assert strip_beat("不急……") == "不急"


def test_ellipsis_after_sentence_end_attaches_to_previous_sentence():
    out = split_sentences("Fed說不急。……債市不信。")
    assert out == ["Fed說不急。……", "債市不信。"]
    assert is_beat(out[0]) and not is_beat(out[1])
    assert [u.gap_after for u in plan_vo("Fed說不急。……債市不信。")] == [BEAT_GAP, GAP]


def test_leading_ellipsis_is_kept_in_first_sentence_and_is_not_a_beat():
    out = split_sentences("……好吧,Fed又改口了。")
    assert out == ["……好吧,Fed又改口了。"]
    assert not is_beat(out[0])


def test_split_sentences_never_drops_trailing_punctuation_runs():
    assert split_sentences("真的假的!?") == ["真的假的!?"]
    assert split_sentences("好吧。……") == ["好吧。……"]
    assert split_sentences("……") == []


def test_plan_vo_uses_long_gap_after_beat():
    utts = plan_vo("Fed說不急……債市說我急。")
    assert [u.gap_after for u in utts] == [BEAT_GAP, GAP]
    assert utts[0].tts_text == "Fed說不急" and utts[0].text == "Fed說不急……"
    assert all(u.voice == "narrator" and u.caption for u in utts)


def test_take_starts_and_duration_follow_per_take_gaps():
    takes = [Take("a", "a.mp3", 2.0, [], BEAT_GAP), Take("b", "b.mp3", 1.0, [], GAP)]
    assert take_starts(takes) == pytest.approx([0.0, 2.5])
    assert take_starts(takes, lead_in=0.15) == pytest.approx([0.15, 2.65])
    assert segment_duration(takes) == pytest.approx(2.0 + 0.5 + 1.0 + TAIL)
    assert segment_duration(takes, lead_in=0.15, min_duration=10.0) == pytest.approx(10.0)


def test_caption_events_skip_takes_without_caption():
    takes = [Take("泡泡句。", "a.mp3", 1.0, [], GAP, False), Take("旁白句。", "b.mp3", 1.0, [])]
    events = caption_events(takes, take_starts(takes))
    assert len(events) == 1
    assert "旁白句" in re.sub(r"\{[^}]*\}", "", events[0])  # 卡拉OK標籤把字拆開,先剝掉再比
    assert events[0].startswith("Dialogue: 0,0:00:01.18")


def test_append_outro_adds_once():
    utts = [Utterance("金句。")]
    outro = "以上非投資建議,明天盤前見。"
    assert append_outro(utts, outro)[-1].text == outro
    already = [Utterance("金句。"), Utterance(outro)]
    assert append_outro(already, outro) == already
    assert append_outro(utts, None) == utts


def test_registry_knows_chart_and_card_and_rejects_unknown():
    assert renderer_for("chart") is not None and renderer_for("card") is not None
    with pytest.raises(ValueError):
        renderer_for("hologram")


def _ctx(takes, duration=6.0, work_dir=Path("/tmp"), lead_in=0.0):
    return RenderContext(index=2, duration=duration, takes=takes,
                         starts=take_starts(takes, lead_in), font="F", work_dir=work_dir,
                         badge="美股早發車 · 9/30")


def test_ass_color_and_rounded_rect():
    assert ass_color("#185FA5") == "&HA55F18&"
    path = rounded_rect(100, 60, 20)
    assert path.startswith("m 20 0 l 80 0 b 100 0") and path.count(" b ") == 4


def _dialogue(**kw):
    return DialogueSegment(lines=kw.get("lines", [
        {"speaker": "Fed", "voice": "a", "text": "十月升息,不急。"},
        {"speaker": "債市", "voice": "b", "text": "你不急,我急。"},
    ]), vo=kw.get("vo", ""))


def test_dialogue_utterances_use_line_voices_without_captions_then_narrator():
    seg = _dialogue(vo="意思是長天期利率自己往上衝。")
    utts = renderer_for("dialogue").utterances(seg)
    assert [(u.voice, u.caption) for u in utts] == [("a", False), ("b", False), ("narrator", True)]


def test_dialogue_bubbles_pop_at_their_take_start(tmp_path):
    seg = _dialogue()
    takes = [Take("十月升息,不急。", "a.mp3", 1.5, [], GAP, False),
             Take("你不急,我急。", "b.mp3", 1.2, [], GAP, False)]
    visual = renderer_for("dialogue").render(seg, _ctx(takes, work_dir=tmp_path))
    assert visual.is_card and visual.stem == "dialogue"
    assert (tmp_path / visual.image).exists()
    ass = visual.ass
    assert "Style: free" in ass and "\\p1" in ass
    assert "Fed" in ass and "債市" in ass
    # 第二個泡泡在第二句起點(1.5 + 0.18)出現
    assert "Dialogue: 0,0:00:01.68" in ass or "Dialogue: 1,0:00:01.68" in ass
    assert ",sub," not in ass  # 泡泡句不上底部字幕
    # 右側 B 角泡泡不越過 x=910(按讚欄)
    for line in ass.splitlines():
        if "\\pos(" in line or "\\move(" in line:
            x = int(line.split("\\move(")[1].split(",")[0]) if "\\move(" in line else 0
            assert x <= 910


def test_unspeakable_line_is_dropped_consistently():
    seg = _dialogue(lines=[
        {"speaker": "Fed", "voice": "a", "text": "……?"},
        {"speaker": "債市", "voice": "b", "text": "我急。"},
        {"speaker": "Fed", "voice": "a", "text": "蛤。"},
    ])
    kept = speakable_lines(seg)
    assert [line.text for line in kept] == ["我急。", "蛤。"]
    assert len(renderer_for("dialogue").utterances(seg)) == 2


def test_bubble_layout_shrinks_then_truncates_long_text():
    # 容量依 PingFang TC 實測校準:60px 一行約 17 個全形字、48px 約 22 個
    lines, fs = bubble_layout("短句")
    assert lines == ["短句"] and fs == 60
    assert bubble_layout("字" * 17) == (["字" * 17], 60)  # 剛好一行
    lines, fs = bubble_layout("字" * 18)
    assert len(lines) == 2 and fs == 60  # 多一個字就換行,但還不用縮字級
    lines, fs = bubble_layout("這一句真的" + "超級" * 12 + "長,長到兩行都裝不下喔")
    assert fs == 48 and len(lines) == 2  # 60px 要 3 行 → 改 48px 收成 2 行
    lines, fs = bubble_layout("字" * 50)
    assert fs == 40 and len(lines) == 2 and not lines[1].endswith("…")  # 48px 要 3 行 → 續縮放得下
    lines, fs = bubble_layout("字" * 80)
    assert fs == FLOOR_SIZE and len(lines) == 2 and lines[1].endswith("…")  # 縮到底還放不下才截斷
    assert bubble_layout("十月升息\n不急。")[0] == ["十月升息 不急。"]  # 內文換行不影響斷行與框高


def _events(ass: str):
    """(泡泡框 [(x, y, w, h)], 角色名頂緣 y 清單);座標取 ``\\move`` 的終點、框尺寸取繪圖路徑。"""
    boxes, label_tops = [], []
    for ln in ass.splitlines():
        if not ln.startswith("Dialogue:") or ",free," not in ln:
            continue
        x, y = (int(v) for v in re.search(r"\\move\(-?\d+,-?\d+,(-?\d+),(-?\d+),", ln).groups())
        if "\\p1" in ln:
            nums = [int(n) for n in re.findall(r"-?\d+", re.search(r"\}(m [^{]+)\{", ln).group(1))]
            boxes.append((x, y, max(nums[0::2]), max(nums[1::2])))
        elif "\\fs40" in ln:
            label_tops.append(y)
    return boxes, label_tops


def _render_ass(seg, tmp_path):
    renderer = renderer_for("dialogue")
    takes = [Take(u.text, f"{i}.mp3", 1.0, [], GAP, False)
             for i, u in enumerate(renderer.utterances(seg))]
    return renderer.render(seg, _ctx(takes, work_dir=tmp_path)).ass


def test_dialogue_shapes_stay_inside_safe_zone(tmp_path):
    """最長的四句、兩種聲線:每個圓角框的右緣 <= 910(按讚欄之外)、下緣 <= 1520(底部 UI 之上)。"""
    long_text = "這一句真的超級超級超級超級超級超級長,長到兩行都裝不下喔"
    seg = _dialogue(lines=[
        {"speaker": "Fed", "voice": "a", "text": long_text},
        {"speaker": "債市", "voice": "b", "text": long_text},
        {"speaker": "Fed", "voice": "a", "text": "字" * 60},
        {"speaker": "債市", "voice": "b", "text": "VIX 一路衝上 2026 點"},
    ])
    boxes, _ = _events(_render_ass(seg, tmp_path))
    assert len(boxes) == 4
    for x, y, w, h in boxes:
        assert x + w <= 910 and y + h <= 1520


def test_two_line_bubbles_leave_room_for_the_next_label(tmp_path):
    """libass 行距 = 字級:四個兩行 60px 泡泡交錯排,每個泡泡底緣離下一槽角色名頂緣 >= 10px。"""
    texts = ["十月升息不急,但債市完全不買單,而且覺得自己被大家當成冤大頭。",
             "你說不急就不急,債市的帳本上,我手上的部位可不是這麼說的喔。",
             "那我問你,殖利率都創新高了,你還敢說不急嗎?給個痛快話。",
             "敢啊,鴿派的話我可以一天講三遍,債市愛不愛聽我都完全不管啦。"]
    for text in texts:
        lines, fs = bubble_layout(text)
        assert fs == 60 and len(lines) == 2 and all(13 <= len(ln) <= 16 for ln in lines), text
    seg = _dialogue(lines=[
        {"speaker": "Fed" if k % 2 == 0 else "債市", "voice": "ab"[k % 2], "text": t}
        for k, t in enumerate(texts)
    ])
    boxes, label_tops = _events(_render_ass(seg, tmp_path))
    assert len(boxes) == len(label_tops) == 4
    for (_, y, _, h), next_label in zip(boxes, label_tops[1:], strict=False):
        assert next_label - (y + h) >= 10


@pytest.mark.parametrize("run", ["1234567890" * 4, "x" * 40, "W" * 40, "VIX" + "9" * 37])
def test_unbreakable_ascii_run_never_leaves_the_bubble_column(run, tmp_path):
    """wrap_lines 不會從中間切英數串;泡泡要縮字級(下限 36)到放得進,A/B 兩側框都在 70..870。"""
    lines, fs = bubble_layout(run)
    assert 36 <= fs <= 60 and len(lines) <= 2
    seg = _dialogue(lines=[
        {"speaker": "Fed", "voice": "a", "text": run},
        {"speaker": "債市", "voice": "b", "text": run},
    ])
    boxes, _ = _events(_render_ass(seg, tmp_path))
    assert len(boxes) == 2
    for x, _, w, _ in boxes:
        assert 70 <= x and x + w <= 870


def test_text_event_escapes_override_braces_and_raw_newlines():
    ev = text_event(0, 1, 10, 20, "a{b}c\nd\\Ne", size=40, color="&H000000&")
    assert ev.split("}", 1)[1] == "a｛b｝c\\Nd\\Ne"  # 花括號全形化、真換行變 \N、既有的 \N 不動
    assert "\n" not in ev


def _split(vo="好消息是Fed說不急。壞消息是債市沒在聽。", **kw):
    return SplitSegment(vo=vo, top={"label": "好消息", "text": kw.get("top", "Fed說不急"),
                                    "tone": "good"},
                        bottom={"label": "壞消息", "text": "債市沒在聽", "stat": "5.26%",
                                "tone": "bad"})


def test_split_bottom_panel_appears_at_second_sentence(tmp_path):
    takes = [Take("好消息是Fed說不急。", "a.mp3", 2.0, []),
             Take("壞消息是債市沒在聽。", "b.mp3", 2.0, [])]
    ctx = _ctx(takes, work_dir=tmp_path)
    assert reveal_times(ctx) == pytest.approx((0.0, 2.18))
    visual = renderer_for("split").render(_split(), ctx)
    assert visual.stem == "split" and "好消息" in visual.ass and "5.26%" in visual.ass
    assert "0:00:02.18" in visual.ass
    assert ",sub," in visual.ass  # 旁白照常上字幕


def test_split_single_sentence_reveals_bottom_at_half(tmp_path):
    takes = [Take("一句話講完。", "a.mp3", 3.0, [])]
    assert reveal_times(_ctx(takes, duration=4.0, work_dir=tmp_path)) == pytest.approx((0.0, 2.0))


def test_panel_text_layout_fits_or_shrinks():
    assert panel_text_layout("Fed說不急", has_stat=False) == (["Fed說不急"], 96)
    lines, size = panel_text_layout("債市完全沒在聽而且還很生氣", has_stat=True)
    assert size == 80 and len(lines) <= 2
    body = "債市完全沒在聽而且還很生氣啊真的假的欸欸"
    assert len(body) == 20
    lines, size = panel_text_layout(body, has_stat=True)  # 96px 一行放不下 → 80px 兩行
    assert size == 80 and len(lines) == 2 and not lines[-1].endswith("…")
    assert panel_text_layout("字" * 13, has_stat=True) == (["字" * 13], 80)
    assert panel_text_layout("字" * 10, has_stat=True) == (["字" * 10], 96)
    lines, size = panel_text_layout("字" * 40, has_stat=True)  # 80px 兩行裝不下 → 續縮,內容完整
    assert len(lines) == 2 and size < 80 and not lines[-1].endswith("…")
    lines, size = panel_text_layout("字" * 80, has_stat=True)  # 縮到底還放不下 → 截斷補「…」
    assert len(lines) == 2 and size == FLOOR_SIZE and lines[-1].endswith("…")
    assert len(panel_text_layout("字" * 40, has_stat=False)[0]) == 2


def test_fit_lines_fits_shrinks_then_truncates_with_ellipsis():
    kw = {"max_width": 750, "sizes": (96, 80)}
    assert fit_lines("短句", max_lines=1, **kw) == (["短句"], 96)  # 放得下就用最大字級
    assert fit_lines("字" * 13, max_lines=1, **kw) == (["字" * 13], 80)  # 96px 放不下 → 第二字級
    assert fit_lines("字" * 14, max_lines=1, **kw) == (["字" * 14], 72)  # 列表字級不夠 → 每次縮 4px
    lines, size = fit_lines("字" * 200, max_lines=2, **kw)
    assert size == FLOOR_SIZE and len(lines) == 2 and lines[-1].endswith("…")  # 縮到底才截斷
    assert not lines[0].endswith("…")


def test_fit_lines_normalises_whitespace_and_newlines():
    lines, _ = fit_lines(" 十月升息\n\n不急。\t對吧  ", max_width=750, sizes=(60,), max_lines=2)
    assert lines == ["十月升息 不急。 對吧"]
    assert fit_lines("", max_width=750, sizes=(60,), max_lines=2) == ([], 60)


def test_fit_lines_keeps_a_fitting_text_on_one_line_despite_punctuation():
    """整段放得進寬度就是一行:行寬過半後遇標點「想斷行」只是 wrap_px 的偏好,不能讓
    max_lines=1 誤判放不下而縮字級、截斷。"""
    text = "好消息是Fed說不急，債市沒在聽"
    assert line_px(text, 60) <= 750 < line_px(text, 96)
    assert wrap_px(text, 60, 750) != [text]  # 前提:wrap_px 會在逗號斷行
    assert fit_lines(text, max_width=750, sizes=(60,), max_lines=1) == ([text], 60)
    assert fit_lines(text, max_width=750, sizes=(60,), max_lines=2) == ([text], 60)
    assert fit_lines(text, max_width=750, sizes=(60, 48), max_lines=1) == ([text], 60)  # 第一個字級
    assert fit_lines(text, max_width=750, sizes=(96, 60), max_lines=1) == ([text], 60)  # 96 放不下


@pytest.mark.parametrize("text", [
    "x" * 40, "W" * 60, "A" * 30, "1234567890" * 5, "字" * 200, "a b c " * 30, "5.26%" * 12,
    "VIX 與 10 年期殖利率同步飆升到 2026 年新高點", "好,壞。" * 30, "{花括號}" * 20,
])
@pytest.mark.parametrize(("max_width", "sizes", "max_lines"), [
    (750, (96, 80), 1), (750, (96, 80), 2), (756, (60, 48), 2), (200, (48,), 1),
])
def test_fit_lines_every_line_fits_the_width(text, max_width, sizes, max_lines):
    lines, size = fit_lines(text, max_width=max_width, sizes=sizes, max_lines=max_lines)
    assert 1 <= len(lines) <= max_lines and size >= FLOOR_SIZE
    assert all(line_px(ln, size) <= max_width for ln in lines)
    assert all("\n" not in ln and ln == ln.strip() for ln in lines)


def test_line_px_measures_braces_as_the_fullwidth_glyphs_text_event_renders():
    assert line_px("{}", 60) == line_px("｛｝", 60)


def test_wrap_px_keeps_number_runs_whole_unless_a_run_alone_overflows():
    assert wrap_px("收盤在7747點", 60, 200) == ["收盤在", "7747點"]  # 放不下就整串移到下一行
    lines = wrap_px("x" * 40, 60, 400)  # 單一英數串自己就超寬才硬切
    assert len(lines) > 1 and "".join(lines) == "x" * 40
    assert all(line_px(ln, 60) <= 400 for ln in lines)


def test_fit_lines_never_starts_a_line_with_a_closer():
    """「。」放不下就把前一個字一起帶到下一行,不讓句號自己成一行(寬度保證照舊)。"""
    lines, size = fit_lines("一二三四五六七八九十。", max_width=750, sizes=(96, 80), max_lines=2)
    assert (lines, size) == (["一二三四五六七八九", "十。"], 96)
    assert all(line_px(ln, size) <= 750 for ln in lines)


def test_bubble_keeps_trailing_ellipsis_with_its_word():
    """泡泡 17 字 +「……」:「……」不可自成一行,連前一個字一起換行。"""
    text = "一二三四五六七八九十一二三四五六七……"
    lines, size = bubble_layout(text)
    assert size == 60 and "".join(lines) == text
    assert lines[-1] == "七……"
    assert all(line_px(ln, size) <= 756 for ln in lines)


def _random_wrap_text(rng: random.Random) -> str:
    """中文字、短數字串、1–2 個行首禁則字元交錯;數字串與禁則字元都不連著出現,
    所以一定有字詞可以帶著禁則字元換行。"""
    parts: list[str] = []
    prev = "cjk"
    for _ in range(rng.randint(1, 30)):
        kinds = ["cjk"] * 14 + ["num"] * 3 * (prev != "num") + ["closer"] * 3 * (prev != "closer")
        prev = rng.choice(kinds)
        if prev == "cjk":
            parts.append(rng.choice("一二三四五六七八九十市場美股債"))
        elif prev == "num":
            parts.append(str(rng.randint(0, 9999)))
        else:
            parts.append("".join(rng.choice("。，、…」）!?%") for _ in range(rng.randint(1, 2))))
    return "".join(parts)


def test_wrap_px_property_widths_hold_and_no_closer_starts_a_line():
    rng = random.Random(20261001)
    for _ in range(2000):
        text = _random_wrap_text(rng)
        for size, max_width in ((96, 750), (60, 756), (72, 730), (48, 400)):
            lines = wrap_px(text, size, max_width)
            assert "".join(lines) == text
            assert all(line_px(ln, size) <= max_width for ln in lines), (text, lines)
            assert all(ln[0] not in NO_LINE_START for ln in lines[1:]), (text, lines)


def _text_extents(ass: str):
    """(錨點 x, 錨點 y, 字級, 是否底部對齊, 斷行清單) 依事件順序;只取 free 樣式的文字事件。"""
    out = []
    for ln in ass.splitlines():
        if not ln.startswith("Dialogue:") or ",free," not in ln or "\\p1" in ln:
            continue
        x, y = (int(v) for v in re.search(r"\\move\(-?\d+,-?\d+,(-?\d+),(-?\d+),", ln).groups())
        size = int(re.search(r"\\fs(\d+)", ln).group(1))
        out.append((x, y, size, "\\an1" in ln, ln.split("}", 1)[1].split("\\N")))
    return out


@pytest.mark.parametrize(("top", "bottom", "stat", "label"), [
    ("Fed說不急", "債市沒在聽", "5.26%", "壞消息"),
    ("x" * 40, "A" * 30, "5.26%", "壞消息"),  # 不可斷的長英數串
    ("Fed說不急", "債市沒在聽", "一二三四五六七八九十一二", "壞消息"),  # 12 個全形字的大數字
    ("Fed說不急\n再說一次\n第三行\n第四行", "債\n市\n沒\n在\n聽", "5.26%", "壞消息"),  # 含換行
    ("字" * 60, "字" * 60, "W" * 20, "壞" * 40),  # 全部過長:縮字級後截斷
    ("Fed說不急", "債市完全沒在聽而且還很生氣啊真的假的欸欸", "5.26%", "壞消息"),  # 20 字兩行
])
def test_split_text_never_leaves_its_panel(top, bottom, stat, label, tmp_path):
    """逐個文字事件:估計右緣(錨點 x + line_px)<= 890、行數在允許範圍(下格有大數字時內文最多 2 行)、
    文字不超出所屬格子,下格內文底緣(y + 行數 × 字級)不壓到大數字頂緣(格底 - 24 - 數字字級)。
    事件順序 = 上格 [標籤, 內文] + 下格 [標籤, 內文, 大數字]。"""
    takes = [Take("好。", "a.mp3", 1.0, []), Take("壞。", "b.mp3", 1.0, [])]
    seg = SplitSegment(vo="好。壞。",
                       top={"label": "好消息", "text": top, "tone": "good"},
                       bottom={"label": label, "text": bottom, "stat": stat, "tone": "bad"})
    ass = renderer_for("split").render(seg, _ctx(takes, work_dir=tmp_path)).ass
    boxes, _ = _events(ass)
    events = _text_extents(ass)
    assert len(boxes) == 2 and len(events) == 5
    panels = [boxes[0]] * 2 + [boxes[1]] * 3
    for (x, y, size, bottom_anchored, lines), allowed, (bx, by, bw, bh) in zip(
            events, [1, 2, 1, 2, 1], panels, strict=True):
        assert 1 <= len(lines) <= allowed
        assert x >= bx and x + max(line_px(ln, size) for ln in lines) <= bx + bw <= 890
        bottom_edge = y if bottom_anchored else y + len(lines) * size
        assert by <= y and bottom_edge <= by + bh
    (_, body_y, body_size, _, body_lines), (_, stat_y, stat_size, _, _) = events[3], events[4]
    assert stat_y - stat_size - (body_y + len(body_lines) * body_size) >= 40


def test_parse_number_handles_common_formats():
    assert parse_number("5.26%")[:3] == ("", 5.26, "%")
    assert parse_number("-0.27%")[:3] == ("-", 0.27, "%")
    p = parse_number("7,670點")
    assert (p.number, p.suffix, p.commas, p.decimals) == (7670.0, "點", True, 0)
    assert parse_number("+16.2萬")[:3] == ("+", 16.2, "萬")
    assert parse_number("約5%")[:3] == ("約", 5.0, "%")
    assert parse_number("N/A") is None


def test_count_up_frames_end_exactly_on_value_and_keep_format():
    frames = count_up_frames("7,670點", 5.0)
    assert frames[0] == (0.0, 0.2, "0點")
    assert frames[-1] == (pytest.approx(0.8), 5.0, "7,670點")
    assert all("," in text or text == "0點" or float(text[:-1].replace(",", "")) < 1000
               for _, _, text in frames[1:-1])
    texts = [t for _, _, t in count_up_frames("5.26%", 5.0)]
    assert all(t.endswith("%") and len(t.split(".")[1]) == 3 for t in texts)  # 兩位小數 + %


def test_count_up_falls_back_to_static_and_handles_short_segments():
    assert count_up_frames("N/A", 3.0) == [(0.0, 3.0, "N/A")]
    frames = count_up_frames("5.26%", 0.5)
    assert frames[-1] == (pytest.approx(0.48), 0.5, "5.26%")  # 段比動畫短:最後一幀硬停在定值
    assert all(t0 < t1 <= 0.5 for t0, t1, _ in frames)


@pytest.mark.parametrize("seg_end", [0.05, 0.2, 0.3, 0.8, 0.81, 2.0])
def test_count_up_frames_invariants_for_any_segment_length(seg_end):
    """最後一幀一定是原字串、每幀 t0 < t1、不超過段尾、幀與幀首尾相接。"""
    frames = count_up_frames("7,670點", seg_end)
    assert frames[-1][2] == "7,670點" and frames[-1][1] == pytest.approx(seg_end)
    assert all(t0 < t1 <= seg_end + 1e-9 for t0, t1, _ in frames)
    assert all(a[1] == pytest.approx(b[0]) for a, b in zip(frames, frames[1:], strict=False))


def test_value_font_size_shrinks_for_wide_values():
    assert value_font_size("5.26%") == 260
    assert value_font_size("+16.2萬億美元") < 260


def test_value_font_size_uses_the_shared_width_model():
    """用 textfit.line_px 量整串:不論長短都 <= 740px;再長就縮到 36 為止。"""
    for value in ["5.26%", "7,670點", "+16.2萬億美元", "+123,456,789.12萬億美元", "W" * 12]:
        size = value_font_size(value)
        assert FLOOR_SIZE <= size <= 260 and line_px(value, size) <= 740
        assert size == 260 or line_px(value, size + 1) > 740  # 是「最大」的合格字級
    assert value_font_size("字" * 200) == FLOOR_SIZE


def test_bignum_render_has_label_context_and_frames(tmp_path):
    seg = BignumSegment(vo="十年期5.26%。", value="5.26%", label="10年期殖利率",
                        context="2007年以來最高")
    takes = [Take("十年期5.26%。", "a.mp3", 2.0, [])]
    visual = renderer_for("bignum").render(seg, _ctx(takes, duration=3.0, work_dir=tmp_path))
    assert visual.stem == "bignum" and visual.is_card
    assert "10年期殖利率" in visual.ass and "2007年以來最高" in visual.ass
    assert visual.ass.count("5.26%") >= 2 and ",sub," in visual.ass
    assert "\\1c&H66D1FF&" in visual.ass  # 大數字用品牌金(ASS 為 BGR)


def _bignum_extents(ass: str):
    """(種類, 錨點 x, 字級, 斷行清單) 依事件順序;大數字幀用 \\pos、label/context 用 \\move。"""
    out = []
    for ln in ass.splitlines():
        if not ln.startswith("Dialogue:") or ",free," not in ln:
            continue
        size = int(re.search(r"\\fs(\d+)", ln).group(1))
        assert "\\an5" in ln  # 全部置中錨點:左右緣 = x ± line_px / 2
        if "\\pos(" in ln:
            kind, x = "value", int(re.search(r"\\pos\((\d+),", ln).group(1))
        else:
            x = int(re.search(r"\\move\((\d+),", ln).group(1))
            y = int(re.search(r"\\move\(\d+,\d+,\d+,(\d+),", ln).group(1))
            kind = "label" if y < 700 else "context"
        out.append((kind, x, size, ln.split("}", 1)[1].split("\\N")))
    return out


@pytest.mark.parametrize(("value", "label", "context"), [
    ("5.26%", "10年期殖利率", "2007年以來最高"),
    ("+123,456,789.12萬億美元", "字" * 30, "這句脈絡真的很長" * 5),  # 30 字 label、40 字 context
    ("W" * 30, "L" * 40, "x" * 80),  # 不可斷的長英數串
    ("字" * 60, "標籤" * 30, "脈絡" * 40),  # 全部過長:縮字級後截斷
    ("{5}%", "標{籤}\n兩行", "脈絡\n換行{}"),  # 花括號與換行不破壞事件
])
def test_bignum_text_never_leaves_the_safe_column(value, label, context, tmp_path):
    """逐個文字事件(label / 每一幀大數字 / context):置中後估計左緣 >= 0、右緣 <= 910(按讚欄之外),
    行數在允許範圍(label 1、大數字 1、context <= 2)。"""
    seg = BignumSegment(vo="講大數字。", value=value, label=label, context=context)
    takes = [Take("講大數字。", "a.mp3", 2.0, [])]
    ass = renderer_for("bignum").render(seg, _ctx(takes, duration=3.0, work_dir=tmp_path)).ass
    events = _bignum_extents(ass)
    assert {k for k, *_ in events} == {"label", "value", "context"}
    allowed = {"label": 1, "value": 1, "context": 2}
    for kind, x, size, lines in events:
        assert x == 540 and 1 <= len(lines) <= allowed[kind] and size >= FLOOR_SIZE
        half = max(line_px(ln, size) for ln in lines) / 2
        assert x - half >= 0 and x + half <= 910, (kind, lines, size)
    sizes = {size for kind, _, size, _ in events if kind == "value"}
    assert len(sizes) == 1  # 數字跳動時字級不變
    assert "{" not in "".join(ln.split("}", 1)[1] for ln in ass.splitlines()
                              if ",free," in ln)  # 文字內沒有會開關 override 的花括號


def test_row_times_follow_sentences_or_spread_evenly():
    assert row_times(2, [0.0, 2.2, 4.0], 6.0) == [0.0, 2.2]
    assert row_times(3, [0.0], 6.0) == pytest.approx([0.0, 2.0, 4.0])


def test_recap_render_rows_marks_and_default_title(tmp_path):
    seg = RecapSegment(vo="昨天說看威廉斯。結果十年期沒守住5.2%。", rows=[
        {"ask": "威廉斯怎麼說", "result": "十月不急", "mark": "yes"},
        {"ask": "10年期守不守5.2%", "result": "沒守住5.26%", "mark": "no"},
        {"ask": "消費者信心", "result": "12年新低", "mark": "mixed"},
    ])
    takes = [Take("昨天說看威廉斯。", "a.mp3", 2.0, []),
             Take("結果十年期沒守住5.2%。", "b.mp3", 2.0, [])]
    visual = renderer_for("recap").render(seg, _ctx(takes, duration=6.0, work_dir=tmp_path))
    ass = visual.ass
    assert visual.stem == "recap" and "昨天說要看的" in ass
    assert "威廉斯怎麼說" in ass and "沒守住5.26%" in ass and "12年新低" in ass
    assert ass.count("\\p1") == 3 + 2  # 三個 mark + 兩條分隔線
    # 2 句 < 3 列 → 三列平均分布在 6 秒段內:0 / 2 / 4 秒
    assert "Dialogue: 1,0:00:02.00" in ass and "Dialogue: 1,0:00:04.00" in ass


def test_recap_rows_follow_sentence_starts_when_enough_sentences(tmp_path):
    seg = RecapSegment(vo="一。二。", rows=[
        {"ask": "甲", "result": "乙", "mark": "yes"}, {"ask": "丙", "result": "丁", "mark": "no"}])
    takes = [Take("一。", "a.mp3", 2.0, []), Take("二。", "b.mp3", 1.0, [])]
    ass = renderer_for("recap").render(seg, _ctx(takes, duration=4.0, work_dir=tmp_path)).ass
    assert "Dialogue: 1,0:00:02.18" in ass  # 第二列在第二句起點


_RECAP_RESULT_MAX_W = 730  # 結果欄 x=160 → 右緣 890,避開右側按讚欄


def test_result_layout_shrinks_long_results():
    assert result_layout("十月不急") == (["十月不急"], 72)
    too_long = "這個結果寫得太長太長太長了吧" * 2 + "啊啊"  # 30 字:72px 兩行裝不下
    lines, size = result_layout(too_long)
    assert size == 60 and len(lines) == 2
    assert all(line_px(ln, size) <= _RECAP_RESULT_MAX_W for ln in lines)
    lines, size = result_layout("字" * 200)  # 縮到底還放不下:截成兩行並補「…」
    assert len(lines) == 2 and lines[-1].endswith("…") and size >= FLOOR_SIZE
    assert all(line_px(ln, size) <= _RECAP_RESULT_MAX_W for ln in lines)


def test_result_layout_keeps_a_one_line_result_at_full_size():
    text = "字" * 14  # 14 個全形字:72px 剛好一行放得下(14 × 72 × 0.713 < 730)
    assert result_layout(text) == ([text], 72)


def test_recap_text_never_leaves_its_row_or_the_safe_column(tmp_path):
    """三列都塞滿 30 字的 ask、40 字的 result:每個文字事件估計右緣(錨點 x + line_px)<= 890,
    ask 一行、result 最多兩行,且每列內文底緣不壓到下一列頂緣(列距 250px)。"""
    rows = [{"ask": f"問{k}" + "問" * 28, "result": f"答{k}" + "答" * 38, "mark": mark}
            for k, mark in enumerate(("yes", "no", "mixed"))]
    seg = RecapSegment(vo="一。二。三。", rows=rows)
    takes = [Take("一。", "a.mp3", 1.0, []), Take("二。", "b.mp3", 1.0, []),
             Take("三。", "c.mp3", 1.0, [])]
    ass = renderer_for("recap").render(seg, _ctx(takes, duration=4.0, work_dir=tmp_path)).ass
    events = _text_extents(ass)
    assert len(events) == 6  # 每列 ask + result
    tops = [330, 580, 830]
    for k, top in enumerate(tops):
        (ax, ay, a_size, _, a_lines), (rx, ry, r_size, _, r_lines) = events[2 * k: 2 * k + 2]
        assert len(a_lines) == 1 and 1 <= len(r_lines) <= 2
        assert ay == top and ry == top + 56
        assert ax + line_px(a_lines[0], a_size) <= 890
        assert rx + max(line_px(ln, r_size) for ln in r_lines) <= 890
        assert ay + a_size <= ry  # ask 底緣不壓到 result 頂緣
        next_top = tops[k + 1] if k + 1 < len(tops) else top + 250
        assert ry + len(r_lines) * r_size <= next_top


def test_recap_ask_with_punctuation_stays_one_line_without_ellipsis():
    ask = "十年期殖利率會不會守住百分之五點二，還是失守？"
    assert line_px(ask, 44) < 820  # 整句放得下(ask 欄 x=70 → 右緣 890)
    assert fit_one_line(ask, 44, 820) == (ask, 44)


def test_recap_result_with_punctuation_stays_one_line_at_full_size():
    text = "殖利率破5.26%，創一年新高"
    assert line_px(text, 72) <= _RECAP_RESULT_MAX_W
    assert result_layout(text) == ([text], 72)


def test_panel_with_stat_keeps_96px_when_punctuated_text_fits_one_line():
    """有大數字的格子:整段 96px 一行放得下就用 96px,不因逗號斷行偏好誤降到 80px。"""
    text = "一二三四五六，七八"
    assert line_px(text, 96) <= 750
    assert panel_text_layout(text, has_stat=True) == ([text], 96)


def test_split_one_line_fit_keeps_size_when_punctuated_text_fits():
    text = "一二三四五六七八，九"
    assert fit_one_line(text, 100, 750) == (text, 100)


def test_fit_one_line_shrinks_then_truncates():
    assert fit_one_line("字" * 13, 96, 750) == ("字" * 13, 80)  # 96px 放不下 → 縮字級
    text, size = fit_one_line("字" * 60, 96, 750)
    assert size == FLOOR_SIZE and text.endswith("…") and line_px(text, size) <= 750


def test_static_text_event_uses_pos_without_slide_or_fade_and_escapes():
    ev = text_event(0.2, 0.24, 540, 820, "{5.26%}", size=200, color="&H66D1FF&", align=5,
                    move_px=None)
    assert "\\pos(540,820)" in ev and "\\move" not in ev and "\\fad" not in ev
    assert ev.endswith("｛5.26%｝") and ev.startswith("Dialogue: 1,0:00:00.20,0:00:00.24,free,")
    popped = text_event(0.0, 1.0, 540, 760, "美股早發車", size=120, color="&H66D1FF&", align=5,
                        move_px=None, effect=POP_IN)
    assert popped.endswith(POP_IN + "美股早發車")


def test_sting_has_lead_in_min_duration_and_no_caption(tmp_path):
    renderer = renderer_for("sting")
    seg = StingSegment(text="美股早發車,發車!", channel="美股早發車", sfx="/abs/sting.wav")
    utts = renderer.utterances(seg)
    assert len(utts) == 1 and utts[0].caption is False
    takes = [Take("美股早發車,發車!", "s.mp3", 0.5, [], GAP, False)]
    assert segment_duration(takes, lead_in=renderer.lead_in,
                            min_duration=renderer.min_duration) == pytest.approx(1.2)
    visual = renderer.render(seg, _ctx(takes, duration=1.2, work_dir=tmp_path,
                                       lead_in=renderer.lead_in))
    assert visual.sfx == "/abs/sting.wav" and visual.stem == "sting"
    assert "美股早發車" in visual.ass and ",sub," not in visual.ass


def test_sting_is_optional_so_tts_failure_can_skip_it():
    assert renderer_for("sting").optional is True
    assert renderer_for("card").optional is False


def _sting_text_events(ass: str) -> list[tuple[int, int, str]]:
    """(錨點 x, 字級, 純文字) 依事件順序;只取 free 樣式、非繪圖的文字事件(wordmark、slogan)。"""
    out = []
    for ln in ass.splitlines():
        if not ln.startswith("Dialogue:") or ",free," not in ln or "\\p1" in ln:
            continue
        x = int(re.search(r"\\(?:pos|move)\((-?\d+),", ln).group(1))
        size = int(re.search(r"\\fs(\d+)", ln).group(1))
        out.append((x, size, re.sub(r"\{[^}]*\}", "", ln.split(",", 9)[9])))
    return out


@pytest.mark.parametrize(("slogan", "channel"), [
    ("美股早發車,發車!", "美股早發車"),
    ("字" * 30, "頻" * 12),  # 30 字口號:縮字級後單行放得下
    ("字" * 60, "頻" * 40),  # 縮到下限還放不下:補「…」截成單行
    ("Ab{cd}" * 6, "Channel{X}"),  # 花括號不可開關 override、不可破壞置中
])
def test_sting_slogan_and_wordmark_stay_centered_inside_safe_width(slogan, channel, tmp_path):
    takes = [Take(slogan, "s.mp3", 0.5, [], GAP, False)]
    seg = StingSegment(text=slogan, channel=channel)
    ass = renderer_for("sting").render(seg, _ctx(takes, duration=1.2, work_dir=tmp_path,
                                                 lead_in=0.15)).ass
    events = _sting_text_events(ass)
    assert len(events) == 2  # wordmark + slogan,各一行(沒有 \\N)
    for x, size, text in events:
        assert x == 540 and "\\N" not in text and size >= FLOOR_SIZE
        half = line_px(text, size) / 2
        assert 170 <= 540 - half and 540 + half <= 910
    assert "{cd}" not in ass  # 花括號已轉全形
    (_, wordmark_size, _), (_, slogan_size, _) = events
    assert wordmark_size <= 120 and slogan_size <= 84  # 字級只會縮不會放大
