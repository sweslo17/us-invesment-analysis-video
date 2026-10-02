"""段型渲染的共用介面與時間工具(v4 規格 §3、§4)。

每種段型一個 renderer:``utterances`` 回傳要念的句子計畫(文字、聲線、句後停頓、是否上
字幕),``render`` 回傳畫面(底圖 + 完整 .ass)。assemble 只負責逐句配音量測、時間軸與
ffmpeg,不認得任何段型——新增段型 = 新增一個 renderer 並在 registry 註冊。
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

from pmb.charts.cards import render_solid_background
from pmb.schemas.script import VoiceKey
from pmb.tts.edge import WordBoundary
from pmb.video.ass import BG_HEX, ass_time
from pmb.video.captions import build_caption_pages, is_beat, split_sentences, strip_beat

GAP = 0.18  # 句間呼吸(秒)
BEAT_GAP = 0.5  # 「……」後停一拍:冷面反差的 punchline 前
TAIL = 0.35  # 段尾停頓(秒)


class Utterance(NamedTuple):
    """一句要念的話:顯示文字(字幕/泡泡)、聲線、句後停頓、是否上底部字幕。"""

    text: str
    voice: VoiceKey = "narrator"
    gap_after: float = GAP
    caption: bool = True

    @property
    def tts_text(self) -> str:
        return strip_beat(self.text)


class Take(NamedTuple):
    """一句配音的實測結果(供段級串接與字幕對時)。"""

    text: str
    audio: str  # work_dir 內檔名
    duration: float  # 實測秒數(probe)
    words: list[WordBoundary]
    gap_after: float = GAP
    caption: bool = True


def plan_vo(vo: str, voice: VoiceKey = "narrator") -> list[Utterance]:
    """旁白 → 逐句計畫;以「……」收尾的句子後面停一拍。"""
    return [Utterance(s, voice, BEAT_GAP if is_beat(s) else GAP) for s in split_sentences(vo)]


def append_outro(utterances: list[Utterance], outro: str | None) -> list[Utterance]:
    """最後一段接上收尾口號;模型已自己寫了同義句(去標點後含「非投資建議」與「盤前見」)就不重複。"""
    if not outro or not utterances:
        return utterances
    spoken = re.sub(r"\W", "", "".join(u.text for u in utterances))
    if "非投資建議" in spoken and "盤前見" in spoken:
        return utterances
    return [*utterances, Utterance(outro)]


def take_starts(takes: list[Take], lead_in: float = 0.0) -> list[float]:
    """各句在段內的起點:前一句長度 + 該句的句後停頓累加。"""
    starts: list[float] = []
    t = lead_in
    for take in takes:
        starts.append(t)
        t += take.duration + take.gap_after
    return starts


def segment_duration(
    takes: list[Take], *, lead_in: float = 0.0, min_duration: float = 0.0
) -> float:
    """段長 = 前導 + 各句長 + 句間停頓(最後一句不算)+ 段尾停頓,至少 ``min_duration``。"""
    if not takes:
        return max(lead_in, min_duration)
    speech = sum(t.duration for t in takes) + sum(t.gap_after for t in takes[:-1])
    return max(lead_in + speech + TAIL, min_duration)


def caption_events(takes: list[Take], starts: list[float]) -> list[str]:
    """逐頁卡拉OK底部字幕(``caption=False`` 的句子不上字幕,例如對話泡泡)。"""
    events: list[str] = []
    for take, offset in zip(takes, starts, strict=True):
        if not take.caption:
            continue
        for page in build_caption_pages(take.text, take.words, take.duration):
            text = "".join(f"{{\\k{cs}}}{chunk}" for chunk, cs in page.karaoke)
            events.append(
                f"Dialogue: 0,{ass_time(offset + page.start)},{ass_time(offset + page.end)},"
                f"sub,,0,0,0,,{text}"
            )
    return events


@dataclass(frozen=True)
class RenderContext:
    """renderer 渲染一段所需的一切(段長、各句實測與起點、字型、角標/CTA…)。"""

    index: int  # 段在 script 裡的索引(字卡配色與檔名用)
    duration: float
    takes: list[Take]
    starts: list[float]
    font: str
    work_dir: Path
    badge: str | None = None
    cta: str | None = None
    chart_paths: dict[str, str] = field(default_factory=dict)
    banner: bool = False  # 這段顯示標題橫幅:用下移的版面(``pmb.video.ass.top_layout``)


class Visual(NamedTuple):
    image: str  # work_dir 內底圖檔名
    is_card: bool  # True = 全屏底圖;False = 圖表框(縮排 + 滑入)
    ass: str  # 完整 .ass 內容
    stem: str  # .ass 檔名前綴(seg / card / dialogue …)
    sfx: str | None = None  # 段首疊的音效檔(絕對路徑)
    chart_box: tuple[int, int] | None = None  # 圖表框 (上緣, 高),只有圖表段(非 is_card)有


class SegmentRenderer(ABC):
    """段型 renderer 介面。``lead_in`` 是段首靜音秒數、``min_duration`` 是段長下限;
    ``optional`` 的段(系統插入的口號轉場)配音失敗就略過,不讓整支片失敗。"""

    lead_in: float = 0.0
    min_duration: float = 0.0
    optional: bool = False

    def utterances(self, seg: Any) -> list[Utterance]:
        return plan_vo(seg.vo)

    @abstractmethod
    def render(self, seg: Any, ctx: RenderContext) -> Visual: ...


def canvas_background(work_dir: Path) -> str:
    """新段型共用的畫布底圖:純色 ``BG_HEX``,與圖表段的 ffmpeg 色源同色(一支片只畫一次)。

    刻意不用字卡的漸層:漸層經 Ken Burns 放大會露出一道色階斷層(2026-09-30 彩排)。
    """
    name = "canvas_bg.png"
    if not (work_dir / name).exists():
        render_solid_background(str(work_dir / name), color=f"#{BG_HEX}")
    return name
