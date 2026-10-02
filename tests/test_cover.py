"""直式封面（1080×1920）測試：cover_spec 挑內容、build_cover_ass 排版、render_cover 渲染。"""

import datetime as dt
import re
import shutil
from pathlib import Path

import pytest
from matplotlib.image import imread

from pmb.charts.cards import accent_for
from pmb.publish import cover
from pmb.publish.cover import (
    COVER_ASS_TEMPLATE,
    CoverSpec,
    build_cover_ass,
    cover_accent,
    cover_spec,
    render_cover,
)
from pmb.schemas.script import Script
from pmb.video.ass import BG_HEX, GOLD_HEX, MUTED_HEX, WHITE_HEX, ass_color, rounded_rect
from pmb.video.textfit import line_px

DAY = dt.date(2026, 10, 2)  # toordinal % 6 == 1 → 調色盤第 2 色 #0353A4
FONT = "PingFang TC"
_BOUND_L, _BOUND_R = 70, 1010  # 文字左右緣：邊距各 70
_BOUND_Y = 1500  # 關鍵文字底緣上限：手機網格會把影片標題疊在縮圖下方約四分之一
_HEADLINE_Y_WITH_STAT, _HEADLINE_Y_BARE = 640, 820
_KICKER_GAP = 40  # kicker 底緣到大標頂緣的距離

_HOOK = {"vo": "開場。", "headline": "鷹鴿吵不完", "tag": "今日盤前", "t_start": 0, "duration": 1}
_CHART = {"vo": "圖。", "chart_id": "c", "stat": "+1.06%", "stat_label": "標普昨收"}
_CHARTS = [{"id": "c", "module": "leverage_decay", "params": {}}]


def _script(*segments: dict) -> Script:
    return Script.model_validate({"segments": list(segments), "charts": _CHARTS})


def _spec(**overrides) -> CoverSpec:
    fields = {
        "headline": "鷹鴿吵不完", "kicker": "今日盤前", "stat": "+1.06%", "stat_label": "標普昨收",
        "date": DAY,
    }
    return CoverSpec(**{**fields, **overrides})


# ---------- ASS 事件解析（只看 build_cover_ass 的輸出，不看像素） ----------

_EVENT_RE = re.compile(
    r"Dialogue: (?P<layer>\d+),[^,]*,[^,]*,free,,0,0,0,,"
    r"\{\\an(?P<an>\d)\\pos\((?P<x>\d+),(?P<y>\d+)\)(?P<tags>[^}]*)\}(?P<body>.*)"
)


def _events(ass: str) -> list[dict]:
    parsed = []
    for line in ass.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        m = _EVENT_RE.match(line)
        assert m, f"事件不是靜態 \\pos 定位：{line}"
        tags = m["tags"]
        fs = re.search(r"\\fs(\d+)", tags)
        color = re.search(r"\\1c(&H[0-9A-F]{6}&)", tags)
        is_shape = "\\p1" in tags
        parsed.append({
            "layer": int(m["layer"]), "an": int(m["an"]), "x": int(m["x"]), "y": int(m["y"]),
            "fs": int(fs[1]) if fs else None, "color": color[1] if color else None,
            "shape": is_shape,
            "body": m["body"].split("{\\p0}")[0] if is_shape else m["body"],
        })
    return parsed


def _texts(ass: str) -> list[dict]:
    return [e for e in _events(ass) if not e["shape"]]


def _shapes(ass: str) -> list[dict]:
    return [e for e in _events(ass) if e["shape"]]


def _text_at(ass: str, x: int, y: int) -> dict | None:
    return next((e for e in _texts(ass) if (e["x"], e["y"]) == (x, y)), None)


# ---------- cover_spec ----------


def test_cover_spec_prefers_hook_headline_kicker_and_first_stat():
    """封面 = 開場鉤子字卡的大標與 kicker，配第一個帶大數字的段落（標籤＋數字成對）。"""
    spec = cover_spec(_script(_HOOK, _CHART), DAY)
    assert spec == CoverSpec("鷹鴿吵不完", "今日盤前", "+1.06%", "標普昨收", DAY)


def test_cover_spec_without_hook_card_is_none():
    script = _script({"vo": "圖。", "chart_id": "c", "t_start": 0, "duration": 1})
    assert cover_spec(script, DAY) is None


def test_cover_spec_without_any_stat_has_no_stat_or_label():
    spec = cover_spec(_script(_HOOK, {"vo": "圖。", "chart_id": "c"}), DAY)
    assert (spec.stat, spec.stat_label) == (None, None)
    assert (spec.headline, spec.kicker) == ("鷹鴿吵不完", "今日盤前")


def test_cover_spec_takes_bignum_value_and_label_when_it_comes_first():
    script = _script(
        {"vo": "開場。", "headline": "債市暴走", "tag": "債市日"},
        {"kind": "bignum", "vo": "5.26%。", "value": "5.26%", "label": "10年期"},
        _CHART,
    )
    spec = cover_spec(script, DAY)
    assert (spec.stat_label, spec.stat) == ("10年期", "5.26%")


def test_cover_spec_chart_without_stat_label_gives_stat_with_no_label():
    spec = cover_spec(_script(_HOOK, {"vo": "圖。", "chart_id": "c", "stat": "+1.06%"}), DAY)
    assert (spec.stat_label, spec.stat) == (None, "+1.06%")


def test_cover_spec_takes_the_first_split_panel_with_a_stat_and_its_label():
    script = _script(
        _HOOK,
        {"kind": "split", "vo": "好。壞。",
         "top": {"label": "利多", "text": "財報超預期"},
         "bottom": {"label": "利空", "text": "殖利率飆升", "stat": "5.26%"}},
        _CHART,
    )
    spec = cover_spec(script, DAY)
    assert (spec.stat_label, spec.stat) == ("利空", "5.26%")


def test_cover_spec_ignores_recap_results():
    """對帳結果是列的結論（如「沒守住5.2%」），不當封面大數字。"""
    script = _script(
        _HOOK,
        {"kind": "recap", "vo": "對帳。",
         "rows": [{"ask": "守5.2%", "result": "沒守住5.2%", "mark": "no"}]},
    )
    assert cover_spec(script, DAY).stat is None


def test_cover_spec_normalizes_halfwidth_punctuation():
    """封面是公開圖片：大標、小標與標籤的半形標點在出口轉全形，大數字的千分位維持原樣。"""
    script = _script(
        {"vo": "開場。", "headline": "債市暴走,Fed不急", "tag": "今日盤前:速報"},
        {"vo": "圖。", "chart_id": "c", "stat": "7,670", "stat_label": "標普(昨收)"},
    )
    spec = cover_spec(script, DAY)
    assert spec.headline == "債市暴走，Fed不急"
    assert spec.kicker == "今日盤前：速報"
    assert spec.stat_label == "標普（昨收）"
    assert spec.stat == "7,670"


# ---------- build_cover_ass ----------


def _headline(ass: str, y: int) -> dict:
    """大標事件（置中、白字）；找不到就讓測試明確失敗。"""
    ev = _text_at(ass, 540, y)
    assert ev is not None, f"y={y} 沒有文字事件"
    return ev


def _headline_lines(ev: dict) -> int:
    return ev["body"].count("\\N") + 1


def test_cover_header_is_vertical_1080x1920_with_only_the_free_style():
    assert "PlayResX: 1080" in COVER_ASS_TEMPLATE and "PlayResY: 1920" in COVER_ASS_TEMPLATE
    styles = [ln for ln in COVER_ASS_TEMPLATE.splitlines() if ln.startswith("Style:")]
    assert len(styles) == 1 and styles[0].startswith("Style: free,")
    ass = build_cover_ass(_spec(), FONT)
    assert "PlayResX: 1080" in ass and f"Style: free,{FONT}," in ass


def test_cover_events_are_all_static():
    ass = build_cover_ass(_spec(), FONT)
    assert "\\move" not in ass and "\\fad" not in ass and "\\t(" not in ass
    assert len(_events(ass)) >= 6  # 條、品牌行、kicker、大標、框、標籤、數字都有


@pytest.mark.parametrize("date", [dt.date(2026, 10, 2), dt.date(2026, 10, 3)])
def test_cover_accent_is_the_palette_color_for_the_date(date):
    assert cover_accent(date) == accent_for(date.toordinal())


def test_consecutive_dates_have_different_accents_and_strip_colors():
    d1, d2 = dt.date(2026, 10, 2), dt.date(2026, 10, 3)
    assert cover_accent(d1) != cover_accent(d2)
    strip1 = _shapes(build_cover_ass(_spec(date=d1), FONT))[0]["color"]
    strip2 = _shapes(build_cover_ass(_spec(date=d2), FONT))[0]["color"]
    assert strip1 != strip2


def test_bottom_strip_is_full_width_in_accent_times_055_and_has_no_text():
    """底部條：y=1500..1920、全寬，色 = 底色逐通道 ×0.55（#0353A4 → #022E5A）；條內不放字。"""
    ass = build_cover_ass(_spec(), FONT)
    strip = _shapes(ass)[0]
    assert (strip["x"], strip["y"], strip["an"]) == (0, 1500, 7)
    assert strip["color"] == ass_color("#022E5A")
    assert strip["body"] == rounded_rect(1080, 420, 0)
    assert all(ev["y"] <= 1500 for ev in _texts(ass))  # 沒有任何文字的錨點落在條內
    # 隔天（#2A9D8F → #17564F）
    other = _shapes(build_cover_ass(_spec(date=dt.date(2026, 10, 3)), FONT))[0]
    assert other["color"] == ass_color("#17564F")


def test_brand_line_is_white_52px_top_centered_with_unpadded_date():
    ass = build_cover_ass(_spec(), FONT)
    ev = _text_at(ass, 540, 130)
    assert ev["body"] == "美股早發車 · 10/2 盤前"
    assert (ev["an"], ev["fs"], ev["color"]) == (8, 52, ass_color(WHITE_HEX))
    custom = build_cover_ass(_spec(date=dt.date(2026, 12, 25)), FONT, channel="早安美股")
    assert _text_at(custom, 540, 130)["body"] == "早安美股 · 12/25 盤前"


def test_brand_line_too_long_is_fitted_to_940px():
    ass = build_cover_ass(_spec(), FONT, channel="美股早發車頻道名很長很長很長很長很長很長很長很長")
    ev = _text_at(ass, 540, 130)
    assert line_px(ev["body"], ev["fs"]) <= 940 and ev["fs"] <= 52


def test_headline_is_white_bold_centered_at_640_with_a_stat():
    ass = build_cover_ass(_spec(), FONT)
    ev = _headline(ass, 640)
    assert ev["an"] == 5 and ev["color"] == ass_color(WHITE_HEX) and ev["layer"] == 1
    assert ev["body"] == "鷹鴿吵不完" and ev["fs"] == 150
    # 粗體來自 free 樣式（Bold=1），事件不覆寫成 \b0
    assert "\\b0" not in ass


def test_headline_without_a_stat_is_centered_at_820():
    ass = build_cover_ass(_spec(stat=None, stat_label=None), FONT)
    assert _headline(ass, 820)["body"] == "鷹鴿吵不完"
    assert _text_at(ass, 540, 640) is None


def test_authored_headline_line_breaks_are_kept_up_to_three_lines():
    ev = _headline(build_cover_ass(_spec(headline="別人恐懼\n我貪婪"), FONT), 640)
    assert ev["body"] == "別人恐懼\\N我貪婪"
    three = _headline(build_cover_ass(_spec(headline="一\n二\n三"), FONT), 640)
    assert three["body"] == "一\\N二\\N三" and three["fs"] == 150


def test_long_headline_shrinks_through_the_size_ladder_and_wraps_to_three_lines():
    headline = "荷姆茲海峽通行量比戰前掉了九成五，原油站上95美元，市場嚇壞了"
    ev = _headline(build_cover_ass(_spec(headline=headline), FONT), 640)
    lines = ev["body"].split("\\N")
    assert ev["fs"] in (150, 132, 116, 100) and len(lines) <= 3
    assert all(line_px(line, ev["fs"]) <= 940 for line in lines)


@pytest.mark.parametrize("stat", ["+1.06%", None])
@pytest.mark.parametrize(
    "headline, lines",
    [
        ("鷹鴿吵不完", 1),
        ("別人恐懼\n我貪婪", 2),
        ("荷姆茲海峽通行量\n比戰前掉了九成五\n原油站上95美元", 3),
    ],
)
def test_kicker_sits_above_the_headline_for_one_two_and_three_lines(headline, lines, stat):
    """kicker 是金色 64px、底緣對齊（\\an2）；底緣 = 大標頂緣 − 40，1、2、3 行都一樣。"""
    ass = build_cover_ass(_spec(headline=headline, stat=stat, stat_label=None), FONT)
    anchor = _HEADLINE_Y_WITH_STAT if stat else _HEADLINE_Y_BARE
    head = _headline(ass, anchor)
    assert _headline_lines(head) == lines
    head_top = anchor - lines * head["fs"] / 2
    kicker = next(e for e in _texts(ass) if e["body"] == "今日盤前")
    assert (kicker["an"], kicker["fs"], kicker["x"], kicker["color"]) == (
        2, 64, 540, ass_color(GOLD_HEX)
    )
    assert kicker["y"] == head_top - _KICKER_GAP < head_top  # 在大標上方、整數座標


def test_missing_kicker_draws_nothing():
    ass = build_cover_ass(_spec(), FONT)
    bare = build_cover_ass(_spec(kicker=None), FONT)
    assert "今日盤前" not in bare
    assert len(_texts(bare)) == len(_texts(ass)) - 1


def test_stat_box_label_and_value_layout():
    ass = build_cover_ass(_spec(), FONT)
    box = next(e for e in _shapes(ass) if e["y"] == 960)
    assert (box["x"], box["y"], box["an"], box["color"]) == (120, 960, 7, ass_color(BG_HEX))
    assert box["body"] == rounded_rect(840, 440, 36)
    label, value = _text_at(ass, 540, 1050), _text_at(ass, 540, 1230)
    assert (label["body"], label["an"], label["fs"], label["color"]) == (
        "標普昨收", 5, 64, ass_color(MUTED_HEX)
    )
    assert (value["body"], value["an"], value["color"]) == ("+1.06%", 5, ass_color(GOLD_HEX))
    # 數字從 220px 起試，放不進 760px 寬就逐級縮（「+1.06%」約 220px 寬 ≈ 700px，放得下）
    assert value["fs"] == 220 and line_px(value["body"], value["fs"]) <= 760


def test_stat_without_label_moves_the_value_up_to_1180():
    ass = build_cover_ass(_spec(stat_label=None), FONT)
    assert _text_at(ass, 540, 1050) is None and _text_at(ass, 540, 1230) is None
    assert _text_at(ass, 540, 1180)["body"] == "+1.06%"


def test_long_stat_value_shrinks_to_fit_760px():
    ev = _text_at(build_cover_ass(_spec(stat="+1,234,567.89%"), FONT), 540, 1230)
    assert ev["fs"] < 220 and line_px(ev["body"], ev["fs"]) <= 760


def test_no_stat_draws_no_box_label_or_value():
    """沒有大數字：沒有深藍框、沒有標籤與數字，大標移到 y=820。"""
    with_stat = build_cover_ass(_spec(), FONT)
    without = build_cover_ass(_spec(stat=None, stat_label=None), FONT)
    assert any(e["y"] == 960 for e in _shapes(with_stat))
    assert [e["y"] for e in _shapes(without)] == [1500]  # 只剩底部條
    for y in (1050, 1180, 1230):
        assert _text_at(without, 540, y) is None


def test_a_label_without_a_stat_is_not_drawn():
    ass = build_cover_ass(_spec(stat=None, stat_label="孤兒標籤"), FONT)
    assert "孤兒標籤" not in ass


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"stat": None, "stat_label": None},
        {"stat_label": None},
        {"headline": "荷姆茲海峽通行量比戰前掉了九成五，原油站上95美元，市場嚇壞了"},
        {"headline": "荷姆茲海峽通行量\n比戰前掉了九成五\n原油站上95美元"},
        {"headline": "x" * 80, "stat": None, "stat_label": None},
        {"headline": "x" * 80},
        {"kicker": "今日盤前速報：" * 8},
        {"stat": "+1,234,567.89%", "stat_label": "超級無敵長的標籤文字超級無敵長的標籤文字"},
        {"stat": "WWWWWWWWWWWW"},
    ],
)
def test_every_text_event_stays_inside_the_canvas_margins_and_above_1500(overrides):
    """每個文字事件（依擬合寬度估）x 在 70..1010、底緣 <= 1500；色塊不在此限。

    全部文字都置中（\\an2 / 5 / 8，x=540）；底緣依錨點算：\\an5 = y + 行數×字級/2、
    \\an8（頂緣對齊）= y + 行數×字級、\\an2（底緣對齊）= y。
    """
    ass = build_cover_ass(_spec(**overrides), FONT, channel="美股早發車頻道名很長很長很長很長")
    for ev in _texts(ass):
        assert ev["x"] == 540 and ev["an"] in (2, 5, 8), ev["body"]
        lines = ev["body"].split("\\N")
        width = max(line_px(line, ev["fs"]) for line in lines)
        assert _BOUND_L <= ev["x"] - width / 2 and ev["x"] + width / 2 <= _BOUND_R, ev["body"]
        block = len(lines) * ev["fs"]
        bottom = {8: ev["y"] + block, 5: ev["y"] + block / 2, 2: ev["y"]}[ev["an"]]
        assert bottom <= _BOUND_Y, (ev["body"], bottom)


def test_a_three_line_headline_stays_clear_of_the_stat_box():
    """有大數字時，3 行 150px 的大標底緣（640 + 225 = 865）也要停在深藍框（y=960）之上。"""
    headline = "荷姆茲海峽通行量\n比戰前掉了九成五\n原油站上95美元"
    ass = build_cover_ass(_spec(headline=headline), FONT)
    ev = _headline(ass, 640)
    assert ev["y"] + _headline_lines(ev) * ev["fs"] / 2 <= 960 - 40


# ---------- render_cover ----------


def test_render_cover_runs_ffmpeg_with_the_accent_background_and_ass_in_a_temp_cwd(
    tmp_path, monkeypatch
):
    seen: dict = {}

    def fake_run(args, cwd):
        seen.update(args=list(args), cwd=Path(cwd))
        ass_file = Path(cwd) / "cover.ass"
        seen["ass_text"] = ass_file.read_text(encoding="utf-8")  # 呼叫時 .ass 已寫好

    monkeypatch.setattr(cover, "_run_ffmpeg", fake_run)
    monkeypatch.chdir(tmp_path)
    out = render_cover(_spec(), "cover_x.png", font=FONT, channel="頻道乙")

    args = seen["args"]
    assert out == (tmp_path / "cover_x.png").resolve() and Path(args[-1]) == out  # 絕對路徑
    assert args[0] == "ffmpeg" and "-y" in args
    assert "color=c=0x0353A4:s=1080x1920:d=1" in args  # 日期 → 調色盤第 2 色，當背景色源
    assert args[args.index("-vf") + 1] == "subtitles=cover.ass"
    assert args[args.index("-frames:v") + 1] == "1"
    assert seen["cwd"] != tmp_path and not seen["cwd"].exists()  # 暫存目錄用完即清
    assert "頻道乙 · 10/2 盤前" in seen["ass_text"] and f"Style: free,{FONT}," in seen["ass_text"]


def test_render_cover_creates_the_output_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(cover, "_run_ffmpeg", lambda args, cwd: None)
    out = render_cover(_spec(), tmp_path / "a" / "b" / "c.png", font=FONT)
    assert out.parent.is_dir()


def test_render_cover_propagates_ffmpeg_failure(tmp_path, monkeypatch):
    def boom(args, cwd):
        raise RuntimeError("ffmpeg 失敗(rc=1)")

    monkeypatch.setattr(cover, "_run_ffmpeg", boom)
    with pytest.raises(RuntimeError, match="ffmpeg"):
        render_cover(_spec(), tmp_path / "c.png", font=FONT)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="需要 ffmpeg")
def test_real_render_writes_a_1080x1920_png_with_the_designed_colors(tmp_path):
    """整合：真的跑 ffmpeg + libass（PingFang TC），PNG 是 1080×1920，底色、深色條、深藍框都對。"""
    out = render_cover(_spec(), tmp_path / "cover.png", font=FONT)
    img = imread(out)
    assert img.shape[:2] == (1920, 1080)

    def px(x: int, y: int) -> tuple[int, ...]:
        return tuple(int(round(v * 255)) for v in img[y, x, :3])

    def near(a: tuple[int, ...], hex_rgb: str, tol: int = 10) -> bool:
        want = tuple(int(hex_rgb[i : i + 2], 16) for i in (0, 2, 4))
        return all(abs(p - w) <= tol for p, w in zip(a, want, strict=True))

    assert near(px(1060, 40), "0353A4")  # 右上角：背景（accent）
    assert near(px(1060, 1490), "0353A4")  # 條上緣之上：仍是背景
    assert near(px(1060, 1510), "022E5A")  # 條上緣之下：accent × 0.55
    assert near(px(20, 1900), "022E5A")  # 左下角：條是全寬
    assert near(px(200, 1380), BG_HEX)  # 深藍框內、沒有字的左下角
    assert near(px(60, 1200), "0353A4")  # 框左側（x < 120）：背景
    assert not near(px(1060, 40), BG_HEX)
