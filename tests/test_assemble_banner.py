"""assemble 接上今日標題橫幅：哪些段有橫幅、ffmpeg 濾鏡鏈順序、版面位置，以及橫幅關掉時
畫面與濾鏡鏈維持原樣。整合測試用靜音配音實跑 ffmpeg，並攔下每支 clip 的 filter_complex。"""

import datetime as dt
import re
import shutil
from pathlib import Path
from typing import NamedTuple

import pytest
from loguru import logger

from pmb.schemas.script import Script
from pmb.schemas.snapshot import LeverageMath, Snapshot
from pmb.tts.edge import silent_synth
from pmb.video import assemble as asm
from pmb.video.assemble import assemble_video
from pmb.video.banner import BANNER_ASS
from pmb.video.segments.sting import StingSegment

_NEEDS_FFMPEG = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="需要 ffmpeg/ffprobe（靜音配音 + 實際合成）",
)

_HEADLINE = "航母開三艘\nVIX卻打哈欠"
_BADGE = "美股早發車 · 9/30"
_BANNER_FILTER = f"subtitles={BANNER_ASS}"
_CANVAS = "0x0D1B2A"


def _snapshot() -> Snapshot:
    return Snapshot(
        session_date=dt.date(2026, 9, 30),
        generated_at=dt.datetime(2026, 9, 30, 12, 0, tzinfo=dt.UTC),
        leverage_math=[LeverageMath(market="S&P 500", realized_vol=0.165, vol_target_leverage=0.91,
                                    drag_1x=0.0136, drag_2x=0.0545, drag_3x=0.1226)],
    )


def _hook() -> dict:
    return {"vo": "開場一句。", "headline": _HEADLINE, "tag": "盤前快報"}


def _chart(title: str | None = "槓桿耗損") -> dict:
    return {"vo": "圖表一句。", "chart_id": "lev", "title": title, "stat": "+1.06%",
            "stat_label": "標普昨收"}


_CHARTS = [{"id": "lev", "module": "leverage_decay", "params": {}}]


def _full_script() -> dict:
    """開場字卡、圖表、名詞小教室字卡、好壞兩格、收尾字卡。"""
    return {
        "segments": [
            _hook(),
            _chart(),
            {"vo": "名詞解釋。", "headline": "VIX是什麼", "tag": "名詞小教室"},
            {"kind": "split", "vo": "好消息。壞消息。", "title": "好壞參半",
             "top": {"label": "好", "text": "漲", "stat": "5%", "tone": "good"},
             "bottom": {"label": "壞", "text": "跌", "tone": "bad"}},
            {"vo": "收尾。", "headline": "金句\n對句", "tag": "巴菲特 不知道有沒有說過"},
        ],
        "charts": _CHARTS,
    }


class _Run(NamedTuple):
    work: Path
    graphs: dict[str, str]  # clip 檔名 → 該支 clip 的 filter_complex
    logs: list[str]  # 這次合成的 INFO 以上日誌（只留訊息本文）


def _assemble(tmp_path_factory, script_data: dict, *, banner: bool = True,
              slogan_intro: str | None = None) -> _Run:
    """靜音配音實跑 assemble_video，順手攔下每支 clip 的 filter_complex（仍真的執行 ffmpeg）
    與日誌。"""
    work = tmp_path_factory.mktemp("work")
    graphs: dict[str, str] = {}
    logs: list[str] = []
    real = asm._run_ffmpeg

    def spy(args, cwd):
        if "-filter_complex" in args:
            graphs[args[-1]] = args[args.index("-filter_complex") + 1]
        return real(args, cwd=cwd)

    sink = logger.add(lambda m: logs.append(m.record["message"]), level="INFO")
    try:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(asm, "_run_ffmpeg", spy)
            assemble_video(
                Script.model_validate(script_data), _snapshot(), work / "out.mp4",
                synth_fn=lambda text, path, planned, voice: silent_synth(text, path, duration=0.5),
                work_dir=work / "w", font="PingFang TC", master_audio=False,
                slogan_intro=slogan_intro, banner=banner,
            )
    finally:
        logger.remove(sink)
    return _Run(work / "w", graphs, logs)


@pytest.fixture(scope="module")
def banner_on(tmp_path_factory) -> _Run:
    return _assemble(tmp_path_factory, _full_script(), slogan_intro="美股早發車，發車！")


@pytest.fixture(scope="module")
def banner_off(tmp_path_factory) -> _Run:
    return _assemble(tmp_path_factory, _full_script(), banner=False,
                     slogan_intro="美股早發車，發車！")


def _has_badge(run: _Run, ass_name: str) -> bool:
    text = (run.work / ass_name).read_text(encoding="utf-8")
    return ",badge,," in text and _BADGE in text


def _headline_logs(run: _Run) -> list[str]:
    """今日主標相關的日誌（每支片應該剛好一行，說明開了或為什麼關）。"""
    return [m for m in run.logs if "今日主標" in m]


def _video_tail(graph: str) -> str:
    """濾鏡鏈裡接在進度條之後、輸出 ``[v]`` 的那一段（淡入、橫幅、淡出）。"""
    match = re.search(r"\[v2\][^;]*\[v\]", graph)
    assert match, graph
    return match.group(0)


def _chart_overlay(graph: str) -> tuple[int, int]:
    """圖表縮排框的疊圖 y 與圖高：從 overlay 與 zoompan 的輸出尺寸讀回來。"""
    oy = int(re.search(r"\[bg\]\[ken\]overlay=\d+:'(\d+)\+", graph).group(1))
    out_h = int(re.search(r":s=\d+x(\d+):fps=", graph).group(1))
    return oy, out_h


# 版面單位序列（含 hook 後插入的口號轉場）：
# u0 hook 字卡、u1 口號轉場、u2 圖表、u3 名詞小教室字卡、u4 好壞兩格、u5 收尾字卡
_UNIT_ASS = {0: "card0.ass", 1: "sting0.ass", 2: "seg1.ass", 3: "card2.ass", 4: "split3.ass",
             5: "card4.ass"}


# ── 誰有橫幅：規則本身 ────────────────────────────────────────────────────────────

def _units(*segments: dict) -> tuple[Script, list]:
    script = Script.model_validate({"segments": list(segments), "charts": _CHARTS})
    units = list(enumerate(script.segments))
    return script, units


def _unit_kinds(units, picked: set[int]) -> list[tuple[int, str]]:
    return [(i, seg.kind) for u, (i, seg) in enumerate(units) if u in picked]


def test_bannered_units_skip_hook_sting_and_closing_card_but_keep_mid_cards():
    lesson = {"vo": "x。", "headline": "名詞", "tag": "名詞小教室"}
    script, units = _units(_hook(), _chart(), lesson, {"vo": "收尾。", "headline": "結語"})
    units.insert(1, (0, StingSegment(text="口號", channel="頻道")))
    picked = asm._bannered_units(units, hook_index=script.hook()[0],
                                 n_script_segments=len(script.segments))
    assert _unit_kinds(units, picked) == [(1, "chart"), (2, "card")]


def test_bannered_units_start_after_a_hook_that_is_not_first():
    script, units = _units(_chart(), _hook(), _chart(), {"vo": "收尾。", "headline": "結語"})
    units.insert(1, (0, StingSegment(text="口號", channel="頻道")))
    picked = asm._bannered_units(units, hook_index=script.hook()[0],
                                 n_script_segments=len(script.segments))
    assert _unit_kinds(units, picked) == [(2, "chart")]  # 鉤子之前的圖表段還沒有主標可顯示


def test_bannered_units_keep_a_chart_that_closes_the_video():
    script, units = _units(_hook(), _chart())
    picked = asm._bannered_units(units, hook_index=0, n_script_segments=len(script.segments))
    assert _unit_kinds(units, picked) == [(1, "chart")]


# ── 橫幅開啟：產物與濾鏡鏈 ─────────────────────────────────────────────────────────

@_NEEDS_FFMPEG
def test_banner_ass_is_written_once_with_the_hook_headline(banner_on):
    path = banner_on.work / BANNER_ASS
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "航母開三艘" in text and "VIX卻打哈欠" in text
    assert [p.name for p in banner_on.work.glob("banner*.ass")] == [BANNER_ASS]


@_NEEDS_FFMPEG
def test_chart_mid_card_and_split_are_bannered_without_the_badge(banner_on):
    for u in (2, 3, 4):
        text = (banner_on.work / _UNIT_ASS[u]).read_text(encoding="utf-8")
        assert ",badge,," not in text and _BADGE not in text, _UNIT_ASS[u]
        graph = banner_on.graphs[f"clip{u}.mp4"]
        assert _BANNER_FILTER in graph, u
        assert graph.index("fade=t=in") < graph.index(_BANNER_FILTER)  # 先淡入、再疊橫幅


@_NEEDS_FFMPEG
def test_hook_sting_and_closing_card_have_no_banner_and_keep_the_badge(banner_on):
    for u in (0, 1, 5):
        assert _has_badge(banner_on, _UNIT_ASS[u]), _UNIT_ASS[u]
        assert _BANNER_FILTER not in banner_on.graphs[f"clip{u}.mp4"], u


@_NEEDS_FFMPEG
def test_banner_logs_the_headline_and_how_many_segments_carry_it(banner_on):
    (line,) = _headline_logs(banner_on)
    assert "航母開三艘" in line and "3 段" in line


@_NEEDS_FFMPEG
def test_banner_follows_the_fade_in_and_sits_in_front_of_the_video_tail(banner_on):
    tail = _video_tail(banner_on.graphs["clip2.mp4"])
    assert tail == f"[v2]fade=t=in:st=0:d={asm._FADE_IN}:color={_CANVAS},{_BANNER_FILTER}[v]"


@_NEEDS_FFMPEG
def test_bannered_chart_is_centred_in_the_shorter_box_below_the_banner(banner_on):
    oy, out_h = _chart_overlay(banner_on.graphs["clip2.mp4"])
    top_gap, bottom_gap = oy - 424, 1120 - (oy + out_h)
    assert top_gap >= 0 and bottom_gap >= 0  # 圖在 424..1120 之內
    assert abs(top_gap - bottom_gap) <= 1  # 置中


@_NEEDS_FFMPEG
def test_bannered_segment_titles_use_the_smaller_title_style(banner_on):
    chart = (banner_on.work / "seg1.ass").read_text(encoding="utf-8")
    assert ",title_b,," in chart and ",title,," not in chart


# ── 橫幅關掉：與原版一致 ──────────────────────────────────────────────────────────

@_NEEDS_FFMPEG
def test_banner_off_writes_no_banner_and_no_filter_references_it(banner_off):
    assert not (banner_off.work / BANNER_ASS).exists()
    assert banner_off.graphs  # 確實攔到了濾鏡鏈
    assert all(BANNER_ASS not in graph for graph in banner_off.graphs.values())
    assert _headline_logs(banner_off) == ["今日主標橫幅關閉：設定關閉（VIDEO_BANNER=false）"]


@_NEEDS_FFMPEG
def test_banner_off_keeps_the_badge_on_every_unit_and_the_plain_title(banner_off):
    for name in _UNIT_ASS.values():
        assert _has_badge(banner_off, name), name
    chart = (banner_off.work / "seg1.ass").read_text(encoding="utf-8")
    assert ",title,," in chart and ",title_b,," not in chart


@_NEEDS_FFMPEG
def test_banner_off_chart_overlay_keeps_the_original_270_based_centring(banner_off):
    oy, out_h = _chart_overlay(banner_off.graphs["clip2.mp4"])
    assert oy == 270 + (850 - out_h) // 2


@_NEEDS_FFMPEG
def test_banner_off_video_tail_is_the_original_fade_only_chain(banner_off):
    last = len(_UNIT_ASS) - 1
    for u in range(last):  # 非最後一支：只有淡入
        assert _video_tail(banner_off.graphs[f"clip{u}.mp4"]) == (
            f"[v2]fade=t=in:st=0:d={asm._FADE_IN}:color={_CANVAS}[v]"
        ), u
    final = _video_tail(banner_off.graphs[f"clip{last}.mp4"])  # 最後一支：淡入再淡出
    assert re.fullmatch(
        rf"\[v2\]fade=t=in:st=0:d={asm._FADE_IN}:color={_CANVAS},"
        rf"fade=t=out:st=[\d.]+:d={asm._FADE_OUT}:color={_CANVAS}\[v\]",
        final,
    ), final


# ── 邊界 ──────────────────────────────────────────────────────────────────────────

@_NEEDS_FFMPEG
def test_script_without_any_card_gets_no_banner_and_no_error(tmp_path_factory):
    run = _assemble(tmp_path_factory, {"segments": [_chart(), _chart(title="第二張")],
                                       "charts": _CHARTS})
    assert not (run.work / BANNER_ASS).exists()
    assert all(BANNER_ASS not in graph for graph in run.graphs.values())
    assert _has_badge(run, "seg0.ass") and _has_badge(run, "seg1.ass")
    assert _headline_logs(run) == ["今日主標橫幅關閉：講稿沒有開場字卡"]


@_NEEDS_FFMPEG
def test_blank_hook_headline_draws_no_banner(tmp_path_factory):
    blank = {"kind": "card", "vo": "開場。", "headline": "  \n ", "tag": "k"}
    run = _assemble(tmp_path_factory, {"segments": [blank, _chart()], "charts": _CHARTS})
    assert not (run.work / BANNER_ASS).exists()
    assert all(BANNER_ASS not in graph for graph in run.graphs.values())
    assert _has_badge(run, "seg1.ass")
    assert _headline_logs(run) == ["今日主標橫幅關閉：開場字卡的標題是空的"]


@_NEEDS_FFMPEG
def test_banner_comes_before_the_fade_out_when_the_last_clip_is_bannered(tmp_path_factory):
    run = _assemble(tmp_path_factory, {"segments": [_hook(), _chart()], "charts": _CHARTS})
    assert re.fullmatch(
        rf"\[v2\]fade=t=in:st=0:d={asm._FADE_IN}:color={_CANVAS},{_BANNER_FILTER},"
        rf"fade=t=out:st=[\d.]+:d={asm._FADE_OUT}:color={_CANVAS}\[v\]",
        _video_tail(run.graphs["clip1.mp4"]),
    )
