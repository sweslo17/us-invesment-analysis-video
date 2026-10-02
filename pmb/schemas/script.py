"""講稿 + 圖表 spec schema(pydantic v2)——規格 §6.3;v4 段型見
docs/superpowers/specs/2026-09-30-video-variety-humor-design.md §3。

每段有 ``kind``,以 discriminated union 區分六種段型。舊 script 沒有 kind,依欄位推斷
(有 chart_id → chart、有 headline → card),歷史檔案照樣載得回來。

這裡只放**結構性**硬規則(必填、數量、對話角色/聲線一致、chart_id 綁定);字數上限、
反重複、梗數、數字一致等風格規則是軟規則,在 ``pmb.research.variety``,不擋出片。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Discriminator, Field, Tag, model_validator

from pmb.schemas.chart import ChartSpec

VoiceKey = Literal["narrator", "a", "b"]
# v4 新段型(反重複規則 S4 用:每支至少一段、組合不跟昨天一樣)
NEW_KINDS: frozenset[str] = frozenset({"dialogue", "split", "bignum", "recap"})


class _SegmentBase(BaseModel):
    vo: str = ""  # 旁白逐字稿
    # 舊欄位:時間軸一向以實測配音長度為準,模型不必再填
    t_start: float = 0.0
    duration: float = 0.0

    @property
    def spoken_text(self) -> str:
        """實際念出來的字(字數預算與數字一致性檢查用)。"""
        return self.vo

    @property
    def display_numbers(self) -> list[str]:
        """畫面上顯示的數字字串(軟規則 N1:要也出現在念出來的字裡)。"""
        return []


class ChartSegment(_SegmentBase):
    """圖表段:綁一張圖(chart_id)+ 選配頂部標題與大數字 callout(stat/stat_label)。"""

    kind: Literal["chart"] = "chart"
    vo: str
    chart_id: str
    title: str | None = None
    stat: str | None = None
    stat_label: str | None = None

    @property
    def display_numbers(self) -> list[str]:
        return [self.stat] if self.stat else []


class CardSegment(_SegmentBase):
    """字卡:全屏大字。hook、名詞小教室(tag=名詞小教室)、片尾金句共用。"""

    kind: Literal["card"] = "card"
    vo: str
    headline: str
    tag: str | None = None


class DialogueLine(BaseModel):
    speaker: str  # 角色名:機構或市場擬人(Fed、債市…),不得是真實人物
    voice: Literal["a", "b"]  # a=男聲、b=女聲(實際聲線見 settings.tts_voice_a/b)
    text: str


class DialogueSegment(_SegmentBase):
    """對話框:2–4 句,泡泡隨各自配音逐句彈出;``vo`` 是講完後的旁白解說(選填)。"""

    kind: Literal["dialogue"] = "dialogue"
    title: str | None = None
    lines: list[DialogueLine] = Field(min_length=2, max_length=4)

    @property
    def spoken_text(self) -> str:
        return "".join(line.text for line in self.lines) + self.vo

    @model_validator(mode="after")
    def _cast_is_consistent(self) -> DialogueSegment:
        voices: dict[str, str] = {}
        for line in self.lines:
            if voices.setdefault(line.speaker, line.voice) != line.voice:
                raise ValueError(f"對話角色「{line.speaker}」前後用了不同聲線")
        if len(voices) < 2:
            raise ValueError("對話至少要有 2 個不同角色")
        return self


class Panel(BaseModel):
    label: str
    text: str
    stat: str | None = None
    tone: Literal["good", "bad", "neutral"] = "neutral"


class SplitSegment(_SegmentBase):
    """好壞消息:上下兩格;上格段首出現、下格在旁白第 2 句開始時出現。"""

    kind: Literal["split"] = "split"
    vo: str
    title: str | None = None
    top: Panel
    bottom: Panel

    @property
    def display_numbers(self) -> list[str]:
        return [p.stat for p in (self.top, self.bottom) if p.stat]


class BignumSegment(_SegmentBase):
    """全屏大數字:value 從 0 跳到定值 + label + 一行脈絡。"""

    kind: Literal["bignum"] = "bignum"
    vo: str
    value: str
    label: str
    context: str | None = None

    @property
    def display_numbers(self) -> list[str]:
        return [self.value]


class RecapRow(BaseModel):
    ask: str  # 昨天說要看的事
    result: str
    mark: Literal["yes", "no", "mixed"]  # ✓ 發生/符合預期、✗ 沒發生/不如預期、〰 好壞參半/未定


class RecapSegment(_SegmentBase):
    """對帳:1–3 列「昨天說要看的 → 結果」,逐列跟著旁白出現。"""

    kind: Literal["recap"] = "recap"
    vo: str
    title: str | None = None
    rows: list[RecapRow] = Field(min_length=1, max_length=3)

    @property
    def display_numbers(self) -> list[str]:
        return [row.result for row in self.rows]


def _segment_kind(value: Any) -> str | None:
    """discriminator:有 kind 用 kind;舊檔依欄位推斷。chart_id/headline 都填或都沒填 → None
    (pydantic 會報「抽不出 tag」,等同舊版「兩者擇一」規則)。"""
    if isinstance(value, dict):
        if value.get("kind"):
            return value["kind"]
        has_chart, has_card = bool(value.get("chart_id")), bool(value.get("headline"))
        if has_chart != has_card:
            return "chart" if has_chart else "card"
        return None
    return getattr(value, "kind", None)


Segment = Annotated[
    Union[  # noqa: UP007 — pydantic 的 Tag 需要逐一 Annotated 的成員
        Annotated[ChartSegment, Tag("chart")],
        Annotated[CardSegment, Tag("card")],
        Annotated[DialogueSegment, Tag("dialogue")],
        Annotated[SplitSegment, Tag("split")],
        Annotated[BignumSegment, Tag("bignum")],
        Annotated[RecapSegment, Tag("recap")],
    ],
    Discriminator(_segment_kind),
]


class Script(BaseModel):
    segments: list[Segment]
    charts: list[ChartSpec]
    # 研究時「想講但固定圖表庫沒得配」的需求描述;人工 gate 當 alert,據此擴充模組庫
    coverage_gaps: list[str] = []
    # 模型自報今天用了哪些梗(每個一句話);供隔天回顧塊避免重複、做 callback
    gags: list[str] = []

    @property
    def total_duration(self) -> float:
        return sum(seg.duration for seg in self.segments)

    def hook(self) -> tuple[int, CardSegment] | None:
        """開場鉤子：第一個字卡段（索引，段）；沒有字卡回 None。封面與今日主標共用。"""
        return next(
            ((i, seg) for i, seg in enumerate(self.segments) if isinstance(seg, CardSegment)),
            None,
        )

    @model_validator(mode="after")
    def _check_chart_bindings(self) -> Script:
        chart_ids = [c.id for c in self.charts]
        if len(chart_ids) != len(set(chart_ids)):
            raise ValueError("charts[].id 不可重複")
        valid = set(chart_ids)
        for seg in self.segments:
            if isinstance(seg, ChartSegment) and seg.chart_id not in valid:
                raise ValueError(f"segment.chart_id「{seg.chart_id}」對不到任何 charts[].id")
        return self
