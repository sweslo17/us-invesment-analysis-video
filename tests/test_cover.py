"""16:9 封面測試：cover_spec 挑內容、build_cover_ass 排版、render_cover 渲染。"""

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
_BOUND_X = 1210  # 文字右緣上限：1280 - 70 的邊距
_BOUND_Y = 720

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


def test_cover_header_is_16x9_with_only_the_free_style():
    assert "PlayResX: 1280" in COVER_ASS_TEMPLATE and "PlayResY: 720" in COVER_ASS_TEMPLATE
    styles = [ln for ln in COVER_ASS_TEMPLATE.splitlines() if ln.startswith("Style:")]
    assert len(styles) == 1 and styles[0].startswith("Style: free,")
    ass = build_cover_ass(_spec(), FONT)
    assert "PlayResX: 1280" in ass and f"Style: free,{FONT}," in ass


def test_cover_events_are_all_static():
    ass = build_cover_ass(_spec(), FONT)
    assert "\\move" not in ass and "\\fad" not in ass and "\\t(" not in ass
    assert len(_events(ass)) >= 6  # 條、條字、框、標籤、數字、大標、kicker 都有


@pytest.mark.parametrize("date", [dt.date(2026, 10, 2), dt.date(2026, 10, 3)])
def test_cover_accent_is_the_palette_color_for_the_date(date):
    assert cover_accent(date) == accent_for(date.toordinal())


def test_consecutive_dates_have_different_accents_and_strip_colors():
    d1, d2 = dt.date(2026, 10, 2), dt.date(2026, 10, 3)
    assert cover_accent(d1) != cover_accent(d2)
    strip1 = _shapes(build_cover_ass(_spec(date=d1), FONT))[0]["color"]
    strip2 = _shapes(build_cover_ass(_spec(date=d2), FONT))[0]["color"]
    assert strip1 != strip2


def test_bottom_strip_is_full_width_in_accent_times_055():
    """底部條：y=576、全寬、高 144，色 = 底色逐通道 ×0.55（#0353A4 → #022E5A）。"""
    ass = build_cover_ass(_spec(), FONT)
    strip = _shapes(ass)[0]
    assert (strip["x"], strip["y"], strip["an"]) == (0, 576, 7)
    assert strip["color"] == ass_color("#022E5A")
    assert strip["body"] == rounded_rect(1280, 144, 0)
    # 隔天（#2A9D8F → #17564F）
    other = _shapes(build_cover_ass(_spec(date=dt.date(2026, 10, 3)), FONT))[0]
    assert other["color"] == ass_color("#17564F")


def test_bottom_strip_text_has_channel_and_unpadded_date():
    ass = build_cover_ass(_spec(), FONT)
    ev = _text_at(ass, 70, 648)
    assert ev["body"] == "美股早發車 · 10/2 盤前"
    assert (ev["an"], ev["fs"], ev["color"]) == (4, 44, ass_color(WHITE_HEX))
    custom = build_cover_ass(_spec(date=dt.date(2026, 12, 25)), FONT, channel="早安美股")
    assert _text_at(custom, 70, 648)["body"] == "早安美股 · 12/25 盤前"


def test_kicker_is_gold_46px_top_left_and_missing_kicker_draws_nothing():
    ass = build_cover_ass(_spec(), FONT)
    kicker = _text_at(ass, 70, 70)
    assert (kicker["body"], kicker["an"], kicker["fs"], kicker["color"]) == (
        "今日盤前", 7, 46, ass_color(GOLD_HEX)
    )
    bare = build_cover_ass(_spec(kicker=None), FONT)
    assert _text_at(bare, 70, 70) is None
    assert len(_texts(bare)) == len(_texts(ass)) - 1


def test_headline_is_white_bold_left_anchored_at_340():
    ass = build_cover_ass(_spec(), FONT)
    ev = _text_at(ass, 70, 340)
    assert ev["an"] == 4 and ev["color"] == ass_color(WHITE_HEX) and ev["layer"] == 1
    assert ev["body"] == "鷹鴿吵不完" and ev["fs"] == 120
    # 粗體來自 free 樣式（Bold=1），事件不覆寫成 \b0
    assert "\\b0" not in ass


def test_authored_headline_line_breaks_are_kept():
    ev = _text_at(build_cover_ass(_spec(headline="別人恐懼\n我貪婪"), FONT), 70, 340)
    assert ev["body"] == "別人恐懼\\N我貪婪"


def test_stat_box_label_and_value_layout():
    ass = build_cover_ass(_spec(), FONT)
    box = next(e for e in _shapes(ass) if e["x"] == 820)
    assert (box["x"], box["y"], box["color"]) == (820, 130, ass_color(BG_HEX))
    assert "400" in box["body"] and "320" in box["body"]
    label, value = _text_at(ass, 1020, 185), _text_at(ass, 1020, 330)
    assert (label["body"], label["an"], label["fs"], label["color"]) == (
        "標普昨收", 5, 44, ass_color(MUTED_HEX)
    )
    assert (value["body"], value["an"], value["color"]) == ("+1.06%", 5, ass_color(GOLD_HEX))
    # 數字從 128px 起試，放不進 340px 寬就逐級縮（「+1.06%」縮到 120px）
    assert 112 <= value["fs"] <= 128 and line_px(value["body"], value["fs"]) <= 340


def test_stat_without_label_centers_the_value_in_the_box():
    ass = build_cover_ass(_spec(stat_label=None), FONT)
    assert _text_at(ass, 1020, 185) is None and _text_at(ass, 1020, 330) is None
    assert _text_at(ass, 1020, 290)["body"] == "+1.06%"


def test_no_stat_draws_no_box_and_headline_gets_the_full_width():
    """沒有大數字：沒有深藍框、沒有標籤與數字；大標寬度從 640 放寬到 1140。"""
    headline = "債市暴走升息預期降溫"  # 10 個字：120px 約 856px 寬
    with_stat = build_cover_ass(_spec(headline=headline), FONT)
    without = build_cover_ass(_spec(headline=headline, stat=None, stat_label=None), FONT)
    assert any(e["x"] == 820 for e in _shapes(with_stat))
    assert not any(e["x"] == 820 for e in _shapes(without))
    assert _text_at(without, 1020, 185) is None and _text_at(without, 1020, 290) is None
    narrow, wide = _text_at(with_stat, 70, 340), _text_at(without, 70, 340)
    assert "\\N" in narrow["body"] or narrow["fs"] < 120  # 640 放不下 120px 的一行
    assert wide["body"] == headline and wide["fs"] == 120  # 1140 放得下


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
        {"kicker": "今日盤前速報：" * 8},
        {"stat": "+1,234,567.89%", "stat_label": "超級無敵長的標籤文字超級無敵長的標籤文字"},
        {"stat": "WWWWWWWWWWWW"},
    ],
)
def test_every_text_event_stays_inside_the_canvas_margins(overrides):
    """每個文字事件（依擬合寬度估）右緣 <= 1210、底緣 <= 720；色塊不在此限。"""
    ass = build_cover_ass(_spec(**overrides), FONT, channel="美股早發車頻道名很長很長很長很長")
    for ev in _texts(ass):
        lines = ev["body"].split("\\N")
        width = max(line_px(line, ev["fs"]) for line in lines)
        height = len(lines) * ev["fs"] * 1.25  # 行高偏保守
        right = ev["x"] + (width / 2 if ev["an"] == 5 else width)
        bottom = ev["y"] + (height if ev["an"] == 7 else height / 2)
        assert right <= _BOUND_X, (ev["body"], right)
        assert bottom <= _BOUND_Y, (ev["body"], bottom)
        assert ev["x"] - (width / 2 if ev["an"] == 5 else 0) >= 0


def test_text_never_enters_the_stat_box_column_when_there_is_a_stat():
    """有大數字時，左側大標與 kicker 要停在深藍框（x=820）之前。"""
    ass = build_cover_ass(_spec(headline="荷姆茲海峽通行量比戰前掉了九成五，原油站上95美元"), FONT)
    for ev in _texts(ass):
        if ev["an"] in (4, 7) and ev["y"] < 576:
            width = max(line_px(line, ev["fs"]) for line in ev["body"].split("\\N"))
            assert ev["x"] + width <= 820 - 10, ev["body"]


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
    assert "color=c=0x0353A4:s=1280x720:d=1" in args  # 日期 → 調色盤第 2 色，當背景色源
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
def test_real_render_writes_a_1280x720_png_with_the_designed_colors(tmp_path):
    """整合：真的跑 ffmpeg + libass（PingFang TC），PNG 是 1280×720，底色/深色條/深藍框位置正確。"""
    out = render_cover(_spec(), tmp_path / "cover.png", font=FONT)
    img = imread(out)
    assert img.shape[:2] == (720, 1280)

    def px(x: int, y: int) -> tuple[int, ...]:
        return tuple(int(round(v * 255)) for v in img[y, x, :3])

    def near(a: tuple[int, ...], hex_rgb: str, tol: int = 10) -> bool:
        want = tuple(int(hex_rgb[i : i + 2], 16) for i in (0, 2, 4))
        return all(abs(p - w) <= tol for p, w in zip(a, want, strict=True))

    assert near(px(1250, 40), "0353A4")  # 右上角：背景（accent）
    assert near(px(1250, 700), "022E5A")  # 右下角：底部條（accent × 0.55）
    assert near(px(860, 440), BG_HEX)  # 深藍框內、沒有字的左下角
    assert not near(px(1250, 40), BG_HEX)
