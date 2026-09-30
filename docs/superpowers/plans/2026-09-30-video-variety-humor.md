# 影片 v4(多變化段型 + 頻道人設梗)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓每日 Shorts 不再套版:6 種段型積木自由組合、反重複驗證、鄉民梗 + 冷面反差人設、雙聲對話配音、開場口號轉場與收尾口號。

**Architecture:** Script 的 segment 改為以 `kind` 區分的 discriminated union(舊檔依欄位推斷);合成端拆出 `pmb/video/segments/` 段型註冊,每種段型各自提供「要念的句子計畫」與「畫面(底圖 + ASS 疊層)」,assemble 只管配音量測、時間軸與 ffmpeg。研究端新增 `pmb/research/variety.py` 做反重複/風格軟規則與「最近 5 天」回顧塊,軟規則不擋出片。

**Tech Stack:** Python 3.12、Poetry、pydantic v2(callable `Discriminator` + `Tag`)、ffmpeg + libass(ASS 繪圖指令 `\p1`)、edge-tts、numpy(程序化音效)、pytest、ruff。

**Spec:** `docs/superpowers/specs/2026-09-30-video-variety-humor-design.md`

## Global Constraints

- 所有工作都在 worktree `/Users/sweslo17/Documents/code/us-invesment-analysis-video/.worktrees/video-variety`(分支 `feat/video-variety`);**不得碰主 checkout、不得 push、不得跑 `pmb publish`/`pmb auto`/任何上傳**。
- 指令一律 `poetry run …`;測試 `poetry run pytest -q`;lint `poetry run ruff check .`(規則 E/F/I/W/UP/B,line-length 100)。**不要跑 `ruff format`**(repo 只跑 ruff check;`assemble.py`/`cards.py` 刻意非 format 風格)。
- 程式註解、docstring、log、錯誤訊息用**繁體中文**,沿用 repo 語氣;log 用 `loguru.logger`。
- 版面安全區:文字不得落在 y > 1520(底部 400px Shorts UI)或 x > 910(右側 170px 按讚欄)。畫布 1080×1920、畫布色 `#0D1B2A`、品牌金 `#FFD166`。
- 數字只能引用快照(prompt 規則);畫面上的數字必須也出現在該段念出來的字裡(軟規則 N1)。
- 風格類規則(字數上限、反重複、梗數、數字一致)全是**軟規則**:不得寫進 schema 讓它變成硬錯。schema 只放結構性檢查。
- 字數預算不變:`TARGET_VO_CHARS = (380, 450)`、`MAX_VO_CHARS = 520`,改以 `spoken_text` 加總。
- 每個 commit 訊息結尾加一行空行後 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。
- 每個任務結束時全部測試綠燈、`ruff check` 乾淨。

## Review Focus

1. **舊 script 相容**:歷史 `artifacts/script_*.json` 沒有 `kind`、有的 `chart_id: null` + `headline`——必須全部載得回來,推斷正確;兩者都填或都沒填要明確報錯(Task 1 用真實舊檔 fixture 測)。
2. **對話句無可發音內容**(例如 `text="……?"`):泡泡與配音的對應不能錯位(Task 5 測 `speakable_lines` 對齊)。
3. **模型無視字數上限**(泡泡 40 字、格子 30 字、大數字 12 字元):renderer 要換行/縮字級/截斷,不得讓 ffmpeg 或版面炸掉(Task 5–8 各有超長輸入測試)。
4. **大數字格式千奇百怪**(`-0.27%`、`7,670點`、`1.77倍`、`約5%`、`N/A`、段長短於 count-up):要能解析或退回靜態,不得例外(Task 7 測)。
5. **沒有歷史 / 歷史檔壞掉**(第一天、artifacts 被清、某天 script 半截):反重複規則自動通過、回顧塊為空、只記 WARNING(Task 2 測)。

---

### Task 1: Script schema 改為 kind union(含舊檔推斷)

**Files:**
- Modify: `pmb/schemas/script.py`(整檔改寫)
- Modify: `pmb/cli.py`(`cover_spec`、`cmd_research` 印出段落那行)
- Modify: `pmb/video/assemble.py:742-767`(Pass B 分辨段型改用 isinstance;Task 4 會整段換掉)
- Modify: `pmb/research/script_builder.py:9-14,100-113`(改建構 `CardSegment`/`ChartSegment`)
- Modify: `tests/test_schemas_script.py`、`tests/test_orchestrator.py:12,17`、`tests/test_script_builder.py:43-44`、`tests/test_cli.py`(新增 cover 測試)
- Create: `tests/fixtures/legacy_script_2026-09-29.json`、`tests/fixtures/legacy_script_2026-09-30.json`(從主 checkout 複製)

**Interfaces:**
- Produces(後續所有任務依賴):
  - `VoiceKey = Literal["narrator", "a", "b"]`、`NEW_KINDS: frozenset[str]`
  - `ChartSegment(kind="chart", vo, chart_id, title?, stat?, stat_label?)`
  - `CardSegment(kind="card", vo, headline, tag?)`
  - `DialogueLine(speaker, voice: Literal["a","b"], text)`、`DialogueSegment(kind="dialogue", vo="", title?, lines[2..4])`
  - `Panel(label, text, stat?, tone: Literal["good","bad","neutral"]="neutral")`、`SplitSegment(kind="split", vo, title?, top, bottom)`
  - `BignumSegment(kind="bignum", vo, value, label, context?)`
  - `RecapRow(ask, result, mark: Literal["yes","no","mixed"])`、`RecapSegment(kind="recap", vo, title?, rows[1..3])`
  - 每種段型:`.kind`、`.spoken_text: str`、`.display_numbers: list[str]`、`.t_start`/`.duration`(預設 0)
  - `Segment`(Annotated union 型別,不可直接建構)、`Script(segments, charts, coverage_gaps=[], gags=[])`

- [ ] **Step 1: 複製真實舊檔當 fixture**

```bash
mkdir -p tests/fixtures
cp /Users/sweslo17/Documents/code/us-invesment-analysis-video/artifacts/script_2026-09-29.json tests/fixtures/legacy_script_2026-09-29.json
cp /Users/sweslo17/Documents/code/us-invesment-analysis-video/artifacts/script_2026-09-30.json tests/fixtures/legacy_script_2026-09-30.json
```

- [ ] **Step 2: 寫失敗測試**(加到 `tests/test_schemas_script.py` 檔尾;並把既有的 `test_headline_card_segment_is_valid_without_chart` 最後一行 `assert script.segments[0].chart_id is None` 改成 `assert script.segments[0].kind == "card"`)

```python
# --- v4:kind union ---
import json
from pathlib import Path

from pmb.schemas.script import (
    BignumSegment,
    CardSegment,
    ChartSegment,
    DialogueSegment,
    RecapSegment,
    SplitSegment,
)

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
        {"speaker": "Fed", "voice": "a", "text": "一"}, {"speaker": "Fed", "voice": "a", "text": "二"}]}
    flip_voice = {**base, "lines": [
        {"speaker": "Fed", "voice": "a", "text": "一"}, {"speaker": "債市", "voice": "b", "text": "二"},
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
```

- [ ] **Step 3: 跑測試確認失敗**

Run: `poetry run pytest tests/test_schemas_script.py -q`
Expected: FAIL(`ImportError: cannot import name 'BignumSegment'`)

- [ ] **Step 4: 改寫 `pmb/schemas/script.py`**(整檔取代)

```python
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
```

若 ruff 對 `Union` 報 UP007 以外的規則(例如 I001 排序),依 ruff 訊息修正;`# noqa: UP007` 保留。

- [ ] **Step 5: 更新 call sites**

`pmb/research/script_builder.py`:import 改為 `from pmb.schemas.script import CardSegment, ChartSegment, Script`;`card()` 回傳型別與建構改成 `CardSegment(vo=vo or headline, headline=headline, tag=tag, t_start=0.0, duration=card_dur)`;`chart_seg()` 改成 `ChartSegment(vo=vo, chart_id=charts[idx].id, title=_CHART_TITLES.get(module), t_start=0.0, duration=per_chart)`;型別註記 `-> Segment` 改為 `-> CardSegment` / `-> ChartSegment`。

`tests/test_orchestrator.py`:`from pmb.schemas.script import Script, Segment` → `from pmb.schemas.script import ChartSegment, Script`;`Segment(vo="x", chart_id="c0", t_start=0, duration=10)` → `ChartSegment(vo="x", chart_id="c0", t_start=0, duration=10)`。

`tests/test_script_builder.py:43-44`:
```python
    cards = [s for s in script.segments if s.kind == "card"]
    chart_segs = [s for s in script.segments if s.kind == "chart"]
```

`pmb/cli.py` 的 `cmd_research` 印段落那行(約 228 行)改為:
```python
        label = getattr(seg, "chart_id", None) or seg.kind
        print(f"  [{seg.t_start:>4.0f}s +{seg.duration:.0f}s · {label}] {seg.spoken_text}")
```

`pmb/cli.py` 的 `cover_spec` 整個函式改為:
```python
def cover_spec(script) -> dict | None:
    """決定封面內容:開場鉤子字卡的大標 + kicker,再配第一個帶大數字的段落(有就用)。

    大數字依段落順序取圖表段 stat / 全屏大數字 value / 好壞消息格子的 stat;對帳結果不算。
    封面是靜態圖,大數字是最能在頻道頁/搜尋結果抓眼球的元素。沒有字卡就回 None。
    """
    hook = next(((i, seg) for i, seg in enumerate(script.segments) if seg.kind == "card"), None)
    if hook is None:
        return None
    idx, seg = hook
    stat = next(
        (
            s.display_numbers[0]
            for s in script.segments
            if s.kind in ("chart", "bignum", "split") and s.display_numbers
        ),
        None,
    )
    return {"headline": seg.headline, "tag": seg.tag, "stat": stat, "accent_index": idx}
```

`pmb/video/assemble.py` Pass B(`for i, seg in enumerate(script.segments):` 迴圈內):把 `seg.headline is not None` 兩處改成 `seg.kind == "card"`,並在 `if seg.kind == "card":` 之前加:
```python
        if seg.kind not in ("chart", "card"):
            raise ValueError(f"段型「{seg.kind}」尚未支援合成")
```
(Task 4 會以 registry 取代整段。)

- [ ] **Step 6: 新增 cover 測試**(`tests/test_cli.py` 檔尾)

```python
def test_cover_spec_takes_bignum_value_when_it_comes_first():
    from pmb.cli import cover_spec
    from pmb.schemas.script import Script

    script = Script.model_validate({
        "segments": [
            {"vo": "開場。", "headline": "債市暴走", "tag": "債市日"},
            {"kind": "bignum", "vo": "5.26%。", "value": "5.26%", "label": "10年期"},
            {"vo": "圖。", "chart_id": "c", "stat": "+1.06%"},
        ],
        "charts": [{"id": "c", "module": "leverage_decay", "params": {}}],
    })
    assert cover_spec(script)["stat"] == "5.26%"
```

- [ ] **Step 7: 跑全部測試**

Run: `poetry run pytest -q && poetry run ruff check .`
Expected: 全綠、ruff 無錯

- [ ] **Step 8: 對主 checkout 的全部歷史 script 做一次性相容驗證**(不入庫)

Run:
```bash
poetry run python -c "
import glob
from pmb.schemas.script import Script
paths = sorted(glob.glob('/Users/sweslo17/Documents/code/us-invesment-analysis-video/artifacts/script_*.json'))
bad = []
for p in paths:
    try: Script.model_validate_json(open(p, encoding='utf-8').read())
    except Exception as e: bad.append((p, str(e)[:120]))
print(len(paths), 'scripts;', len(bad), 'failed'); [print(b) for b in bad]
"
```
Expected: `N scripts; 0 failed`。若有失敗,檢查原因(舊 schema 當時也會拒的檔可列為已知例外並在 commit 訊息註明)。

- [ ] **Step 9: Commit**

```bash
git add pmb/schemas/script.py pmb/cli.py pmb/video/assemble.py pmb/research/script_builder.py tests/
git commit -m "feat(schema): segment 改為 kind union——新增 dialogue/split/bignum/recap,舊檔自動推斷

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: 反重複與風格軟規則模組 `variety.py`

**Files:**
- Create: `pmb/research/variety.py`
- Test: `tests/test_variety.py`

**Interfaces:**
- Consumes: Task 1 的段型類別、`NEW_KINDS`、`Script`。
- Produces:
  - `DayRecord(NamedTuple: date: dt.date, script: Script)`
  - `load_recent_scripts(artifacts_dir: str | Path, before: dt.date, n: int) -> list[DayRecord]`(新到舊)
  - `soft_script_errors(script: Script, recent: list[DayRecord]) -> list[str]`
  - `summarize_recent(recent: list[DayRecord], *, days: int = 5) -> str`(空歷史回 `""`)
  - 常數 `LESSON_LOOKBACK = 20`、`LESSON_TAG = "名詞小教室"`、`QUOTE_SUFFIX = "不知道有沒有說過"`
  - 個別檢查(測試用):`check_structure`、`check_variety`、`check_gags`、`check_lengths`、`check_numbers`、`numeric_cores`

- [ ] **Step 1: 寫失敗測試** `tests/test_variety.py`

```python
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
        {"speaker": "聯準會主席辦公室", "voice": "a", "text": "這一句話真的非常非常非常非常非常長喔"},
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
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `poetry run pytest tests/test_variety.py -q`
Expected: FAIL(`ModuleNotFoundError: pmb.research.variety`)

- [ ] **Step 3: 實作 `pmb/research/variety.py`**

```python
"""影片反重複與風格軟規則(v4 規格 §5)。

全部是**軟規則**:研究重試時帶給模型修,最後仍不過照樣出片(見 local_runner)。
歷史以 artifacts 裡「日期早於今天、存在的 script 檔」為準(= 交易日);讀不到的日子跳過。
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import NamedTuple

from loguru import logger
from pydantic import ValidationError

from pmb.schemas.script import (
    NEW_KINDS,
    BignumSegment,
    CardSegment,
    ChartSegment,
    DialogueSegment,
    RecapSegment,
    Script,
    SplitSegment,
)

LESSON_TAG = "名詞小教室"
QUOTE_SUFFIX = "不知道有沒有說過"
SIGNATURE_LOOKBACK = 3  # S2:段型序列不可跟前 3 個交易日任一天一樣
LESSON_LOOKBACK = 20  # S5:名詞小教室術語 20 個交易日內不重複
SUMMARY_DAYS = 5  # 回顧塊列最近 5 天
MIN_GAGS = 2
MIN_CHARTS = 2

_SCRIPT_RE = re.compile(r"^script_(\d{4}-\d{2}-\d{2})\.json$")
_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_NAME_NOISE_RE = re.compile(r"[\s·・.]")


class DayRecord(NamedTuple):
    date: dt.date
    script: Script


def load_recent_scripts(artifacts_dir: str | Path, before: dt.date, n: int) -> list[DayRecord]:
    """讀 ``before`` 之前(不含)最近 ``n`` 份可解析的 script,新到舊;壞檔跳過並記 WARNING。"""
    root = Path(artifacts_dir)
    if not root.is_dir():
        return []
    dated: list[tuple[dt.date, Path]] = []
    for path in root.glob("script_*.json"):
        match = _SCRIPT_RE.match(path.name)
        if match is None:
            continue
        day = dt.date.fromisoformat(match.group(1))
        if day < before:
            dated.append((day, path))
    out: list[DayRecord] = []
    for day, path in sorted(dated, reverse=True):
        if len(out) >= n:
            break
        try:
            out.append(DayRecord(day, Script.model_validate_json(path.read_text(encoding="utf-8"))))
        except (ValidationError, ValueError, OSError) as exc:
            logger.warning("略過無法解析的歷史 script {}:{}", path.name, str(exc)[:200])
    return out


def _module_of(seg, script: Script) -> str | None:
    if isinstance(seg, ChartSegment):
        return next((c.module for c in script.charts if c.id == seg.chart_id), None)
    return None


def kind_signature(script: Script) -> tuple[str, ...]:
    return tuple(seg.kind for seg in script.segments)


def describe_sequence(script: Script) -> str:
    """例:``card → chart:overnight_vs_close → dialogue → card``。"""
    parts = []
    for seg in script.segments:
        module = _module_of(seg, script)
        parts.append(f"{seg.kind}:{module}" if module else seg.kind)
    return " → ".join(parts)


def first_content(script: Script) -> tuple[str, str | None] | None:
    """hook 之後第一段的 (kind, 模組);系統插入的口號轉場不在 script 裡,所以就是 index 1。"""
    if len(script.segments) < 2:
        return None
    seg = script.segments[1]
    return seg.kind, _module_of(seg, script)


def hook_card(script: Script) -> CardSegment | None:
    first = script.segments[0] if script.segments else None
    return first if isinstance(first, CardSegment) else None


def quote_card(script: Script) -> CardSegment | None:
    last = script.segments[-1] if script.segments else None
    if isinstance(last, CardSegment) and (last.tag or "").strip().endswith(QUOTE_SUFFIX):
        return last
    return None


def quote_author(script: Script) -> str | None:
    """金句卡 tag「彼得·林區 不知道有沒有說過」→「彼得林區」(去空白與間隔號,同一人才比得出來)。"""
    card = quote_card(script)
    if card is None:
        return None
    name = (card.tag or "").strip()[: -len(QUOTE_SUFFIX)]
    return _NAME_NOISE_RE.sub("", name) or None


def lesson_term(script: Script) -> str | None:
    for seg in script.segments:
        if isinstance(seg, CardSegment) and (seg.tag or "").strip() == LESSON_TAG:
            return seg.headline.replace("\n", "").strip()
    return None


def new_kinds_used(script: Script) -> frozenset[str]:
    return frozenset(seg.kind for seg in script.segments if seg.kind in NEW_KINDS)


def numeric_cores(text: str) -> list[str]:
    """數字核心:去掉正負號、千分位逗號與單位(``+16.2萬`` → ``16.2``)。"""
    return [m.group().replace(",", "") for m in _NUM_RE.finditer(text)]


def check_structure(script: Script) -> list[str]:
    """S1:hook 開場、金句收尾、至少 2 張圖。"""
    errors: list[str] = []
    if hook_card(script) is None:
        errors.append("結構:第一段必須是 hook 字卡(kind=card)")
    if quote_card(script) is None:
        errors.append(f"結構:最後一段必須是金句字卡(kind=card,tag 以「{QUOTE_SUFFIX}」結尾)")
    n_charts = sum(isinstance(seg, ChartSegment) for seg in script.segments)
    if n_charts < MIN_CHARTS:
        errors.append(
            f"結構:圖表段至少 {MIN_CHARTS} 段(目前 {n_charts})——數字是這支片的核心,梗不能擠掉它"
        )
    return errors


def check_variety(script: Script, recent: list[DayRecord]) -> list[str]:
    """S2–S6:跟最近幾天比,別重複骨架、開場、新段型組合、金句名人、kicker、名詞小教室。"""
    errors: list[str] = []
    signature = kind_signature(script)
    for day in recent[:SIGNATURE_LOOKBACK]:
        if kind_signature(day.script) == signature:
            errors.append(
                f"反重複:段型序列跟 {day.date} 一模一樣({' → '.join(signature)});"
                "換個排列或換段型"
            )
            break
    used = new_kinds_used(script)
    if not used:
        errors.append("多變:至少用 1 段新段型(dialogue / split / bignum / recap)")
    if recent:
        yesterday = recent[0]
        first = first_content(script)
        if first is not None and first == first_content(yesterday.script):
            label = ":".join(part for part in first if part)
            errors.append(
                f"反重複:hook 後第一段又是 {label},跟 {yesterday.date} 一樣;換一個開場角度"
            )
        if used and used == new_kinds_used(yesterday.script):
            errors.append(
                f"反重複:新段型組合跟 {yesterday.date} 一樣({'、'.join(sorted(used))});換一種"
            )
        author = quote_author(script)
        if author and author == quote_author(yesterday.script):
            errors.append(f"反重複:金句名人跟 {yesterday.date} 同一位({author});換一位")
        hook, prev_hook = hook_card(script), hook_card(yesterday.script)
        kicker = (hook.tag or "").strip() if hook else ""
        if kicker and prev_hook is not None and kicker == (prev_hook.tag or "").strip():
            errors.append(
                f"反重複:hook 小標(tag)「{kicker}」跟 {yesterday.date} 一樣;"
                "依今天的性質換一個 kicker"
            )
    term = lesson_term(script)
    if term:
        for day in recent[:LESSON_LOOKBACK]:
            if lesson_term(day.script) == term:
                errors.append(
                    f"反重複:名詞小教室「{term}」{day.date} 教過了;換一個術語,或今天不放"
                )
                break
    return errors


def check_gags(script: Script) -> list[str]:
    """S7:至少 2 個梗(不含金句),模型自報在 ``gags``。"""
    if len(script.gags) >= MIN_GAGS:
        return []
    return [
        f"梗:gags 至少 {MIN_GAGS} 個(不含金句),目前 {len(script.gags)};"
        "全片至少 2 個梗、1 個在前 15 秒,並把用了哪些梗寫進 script.gags"
    ]


def _over(errors: list[str], idx: int, field: str, text: str | None, limit: int) -> None:
    if text is None:
        return
    n = len(text.replace("\n", ""))
    if n > limit:
        errors.append(f"字數:第 {idx} 段 {field}「{text}」{n} 字,上限 {limit}")


def check_lengths(script: Script) -> list[str]:
    """L1:各欄位字數上限(超過畫面會擠,renderer 雖會縮字但請照上限寫)。"""
    errors: list[str] = []
    for i, seg in enumerate(script.segments):
        if isinstance(seg, ChartSegment):
            _over(errors, i, "title", seg.title, 10)
            _over(errors, i, "stat", seg.stat, 7)
            _over(errors, i, "stat_label", seg.stat_label, 12)
        elif isinstance(seg, DialogueSegment):
            _over(errors, i, "title", seg.title, 10)
            for k, line in enumerate(seg.lines):
                _over(errors, i, f"lines[{k}].speaker", line.speaker, 6)
                _over(errors, i, f"lines[{k}].text", line.text, 16)
        elif isinstance(seg, SplitSegment):
            _over(errors, i, "title", seg.title, 10)
            for name, panel in (("top", seg.top), ("bottom", seg.bottom)):
                _over(errors, i, f"{name}.label", panel.label, 6)
                _over(errors, i, f"{name}.text", panel.text, 10)
                _over(errors, i, f"{name}.stat", panel.stat, 7)
        elif isinstance(seg, BignumSegment):
            _over(errors, i, "value", seg.value, 8)
            _over(errors, i, "label", seg.label, 12)
            _over(errors, i, "context", seg.context, 16)
        elif isinstance(seg, RecapSegment):
            _over(errors, i, "title", seg.title, 10)
            for k, row in enumerate(seg.rows):
                _over(errors, i, f"rows[{k}].ask", row.ask, 14)
                _over(errors, i, f"rows[{k}].result", row.result, 12)
    return errors


def check_numbers(script: Script) -> list[str]:
    """N1:畫面上的數字(數字核心)必須出現在該段念出來的字裡。"""
    errors: list[str] = []
    for i, seg in enumerate(script.segments):
        spoken = seg.spoken_text.replace(",", "")
        for shown in seg.display_numbers:
            missing = [core for core in numeric_cores(shown) if core not in spoken]
            if missing:
                errors.append(
                    f"數字:第 {i} 段畫面上的「{shown}」沒出現在旁白裡(缺 {'、'.join(missing)});"
                    "畫面與聲音的數字要一致"
                )
    return errors


def soft_script_errors(script: Script, recent: list[DayRecord]) -> list[str]:
    """全部軟規則(S1–S7、L1、N1)。字數預算另在 local_runner.check_vo_budget。"""
    return (
        check_structure(script)
        + check_variety(script, recent)
        + check_gags(script)
        + check_lengths(script)
        + check_numbers(script)
    )


def summarize_recent(recent: list[DayRecord], *, days: int = SUMMARY_DAYS) -> str:
    """給研究 prompt 的「最近幾天」回顧塊;沒有歷史回空字串。"""
    if not recent:
        return ""
    shown = recent[:days]
    lines = [f"\n=== 最近 {len(shown)} 個交易日的影片(別重複骨架、開場與梗;驗證器會擋)==="]
    for day in shown:
        s = day.script
        hook, quote = hook_card(s), quote_card(s)
        hook_txt = (
            f"「{hook.headline.replace(chr(10), ' ')}」(kicker:{hook.tag or '無'})" if hook else "(無)"
        )
        quote_txt = (
            f"{quote_author(s)}「{quote.headline.replace(chr(10), ' / ')}」" if quote else "(無)"
        )
        lines.append(f"- {day.date}|段型:{describe_sequence(s)}")
        lines.append(f"  hook:{hook_txt}|金句:{quote_txt}|名詞小教室:{lesson_term(s) or '無'}")
        lines.append(f"  梗:{';'.join(s.gags) if s.gags else '(未記錄)'}")
    terms: list[str] = []
    for day in recent[:LESSON_LOOKBACK]:
        term = lesson_term(day.script)
        if term and term not in terms:
            terms.append(term)
    if terms:
        lines.append(f"近 {LESSON_LOOKBACK} 個交易日教過的名詞小教室(別重複):{'、'.join(terms)}")
    return "\n".join(lines)
```

- [ ] **Step 4: 跑測試**

Run: `poetry run pytest tests/test_variety.py -q && poetry run ruff check .`
Expected: PASS、ruff 乾淨

- [ ] **Step 5: Commit**

```bash
git add pmb/research/variety.py tests/test_variety.py
git commit -m "feat(research): 反重複與風格軟規則(variety)+ 最近 5 天回顧塊

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: 研究流程接上軟規則、回顧塊與 `pmb validate-research`

**Files:**
- Modify: `pmb/research/local_runner.py`(`validate_research_artifacts`、`check_vo_budget`、`run_local_research`)
- Modify: `pmb/research/runner.py:31-86`(`build_research_prompt` 加 `recent_summary`、files 模式自檢指示)
- Modify: `pmb/cli.py`(新增 `cmd_validate_research` 與 parser)
- Test: `tests/test_local_research.py`、`tests/test_runner.py`、`tests/test_cli.py`

**Interfaces:**
- Consumes: `variety.load_recent_scripts`、`soft_script_errors`、`summarize_recent`、`LESSON_LOOKBACK`;`Segment.spoken_text`。
- Produces:
  - `validate_research_artifacts(artifacts_dir: Path, target: dt.date, *, include_soft: bool = True) -> list[str]`(參數由 `include_budget` 改名)
  - `build_research_prompt(snapshot, thesis, prompt_template, previous_brief=None, *, output_mode="json", recent_summary: str | None = None) -> str`
  - CLI:`pmb validate-research [--date YYYY-MM-DD]`,全過印「全部通過」rc=0,否則逐條 `- 錯誤` rc=1。

- [ ] **Step 1: 更新測試 fixture 讓「合法產物」也符合軟規則**

`tests/test_local_research.py` 的 `_write_valid_artifacts` 內 `script = {...}` 改為:
```python
    script = {
        "segments": [
            {"kind": "card", "vo": "測試開場。", "headline": "測試開場", "tag": "測試日"},
            {"kind": "chart", "vo": "測試句一。", "chart_id": "c0"},
            {"kind": "bignum", "vo": "數字是5.26%。", "value": "5.26%", "label": "殖利率"},
            {"kind": "chart", "vo": "測試句二。", "chart_id": "c1"},
            {"kind": "card", "vo": "金句。", "headline": "金句\n對句",
             "tag": "巴菲特 不知道有沒有說過"},
        ],
        "charts": [{"id": "c0", "module": "index_overnight_grid", "params": {}},
                   {"id": "c1", "module": "rates_trend", "params": {}}],
        "gags": ["測試梗一", "測試梗二"],
    }
```

- [ ] **Step 2: 寫失敗測試**(加到 `tests/test_local_research.py` 檔尾)

```python
def test_validate_includes_soft_variety_errors_and_can_skip_them(tmp_path):
    _write_valid_artifacts(tmp_path)
    script = json.loads((tmp_path / f"script_{_D}.json").read_text())
    script["gags"] = []  # 違反 S7
    (tmp_path / f"script_{_D}.json").write_text(json.dumps(script), encoding="utf-8")
    assert any("gags" in e for e in validate_research_artifacts(tmp_path, _D))
    assert validate_research_artifacts(tmp_path, _D, include_soft=False) == []


def test_validate_compares_against_yesterday_script(tmp_path):
    _write_valid_artifacts(tmp_path)
    yesterday = _D - dt.timedelta(days=1)
    (tmp_path / f"script_{yesterday}.json").write_text(
        (tmp_path / f"script_{_D}.json").read_text(), encoding="utf-8"
    )
    errors = validate_research_artifacts(tmp_path, _D)
    assert any("段型序列" in e for e in errors)


def test_soft_errors_retry_then_ship_anyway(tmp_path):
    settings = _settings(tmp_path)
    calls: list[str] = []

    def no_gags(prompt: str) -> None:
        calls.append(prompt)
        _write_valid_artifacts(settings.artifacts_dir)
        path = settings.artifacts_dir / f"script_{_D}.json"
        script = json.loads(path.read_text())
        script["gags"] = []
        path.write_text(json.dumps(script), encoding="utf-8")

    assert run_local_research(_D, settings, invoke=no_gags, max_attempts=2) is True
    assert len(calls) == 2 and "gags" in calls[1]


def test_prompt_includes_recent_history_block(tmp_path):
    settings = _settings(tmp_path)
    _write_valid_artifacts(settings.artifacts_dir)
    yesterday = _D - dt.timedelta(days=1)
    (settings.artifacts_dir / f"script_{yesterday}.json").write_text(
        (settings.artifacts_dir / f"script_{_D}.json").read_text(), encoding="utf-8"
    )
    (settings.artifacts_dir / f"script_{_D}.json").unlink()
    calls: list[str] = []

    def fake_invoke(prompt: str) -> None:
        calls.append(prompt)
        _write_valid_artifacts(settings.artifacts_dir)

    run_local_research(_D, settings, invoke=fake_invoke)
    assert "最近 1 個交易日的影片" in calls[0]
    assert str(yesterday) in calls[0]
    assert "pmb validate-research" in calls[0]
```

注意:最後一個測試的 `fake_invoke` 產物跟昨天一樣,會觸發反重複軟錯而重試;測試只斷言**第一次 prompt 的內容**,不斷言重試次數。

在 `tests/test_cli.py` 檔尾加:
```python
def test_validate_research_command_reports_errors_and_rc(tmp_path, monkeypatch, capsys):
    import datetime as dt
    import types

    from pmb import cli

    monkeypatch.setattr(cli, "get_settings", lambda: types.SimpleNamespace(artifacts_dir=tmp_path))
    rc = cli.main(["validate-research", "--date", "2026-07-10"])
    out = capsys.readouterr().out
    assert rc == 1 and "缺 brief_2026-07-10.json" in out
```
(`resolve_fetch_target` 對明確指定的日期直接採用、不檢查休市;`main()` 只 parse 參數後呼叫 `args.func`,不讀其他設定。)

- [ ] **Step 3: 跑測試確認失敗**

Run: `poetry run pytest tests/test_local_research.py tests/test_cli.py -q`
Expected: FAIL(`include_soft` 不存在、prompt 無回顧塊、`validate-research` 指令不存在)

- [ ] **Step 4: 實作 local_runner**

`pmb/research/local_runner.py`:
- import 加 `from pmb.research.variety import LESSON_LOOKBACK, load_recent_scripts, soft_script_errors, summarize_recent`。
- `validate_research_artifacts` 參數 `include_budget: bool = True` 改名 `include_soft: bool = True`;docstring 改述「``include_soft=False`` 只回硬錯(缺檔/schema 壞),用來區分『不能出片』與『軟規則沒過但仍可出片』」;原本
  ```python
    if script is not None and include_budget:
        errors.extend(check_vo_budget(script))
  ```
  改為
  ```python
    if script is not None and include_soft:
        errors.extend(check_vo_budget(script))
        recent = load_recent_scripts(artifacts_dir, target, LESSON_LOOKBACK)
        errors.extend(soft_script_errors(script, recent))
  ```
- `check_vo_budget`:`total = sum(len(seg.vo) for seg in script.segments)` 改為 `total = sum(len(seg.spoken_text) for seg in script.segments)`。
- `run_local_research`:`base_prompt = build_research_prompt(...)` 改為
  ```python
    recent = load_recent_scripts(settings.artifacts_dir, target, LESSON_LOOKBACK)
    base_prompt = build_research_prompt(
        snapshot, thesis, template, previous_brief, output_mode="files",
        recent_summary=summarize_recent(recent),
    )
  ```
  檔尾 fallback 改為
  ```python
    # 重試用盡:只剩軟錯(字數超標、反重複、風格)時產物本身合法,寧可照樣出片也不要整天
    # 沒影片;硬錯(缺檔/schema 壞)才真的放棄。
    hard_errors = validate_research_artifacts(settings.artifacts_dir, target, include_soft=False)
    if not hard_errors:
        logger.warning(
            "軟規則仍未全過但產物合法,照樣出片({}):{}(若是字數超標,成片可能超過 {:.0f}s、"
            "失去 Shorts 資格)",
            target,
            "; ".join(last_errors),
            SHORTS_CAP_SEC,
        )
        return True
    return False
  ```

- [ ] **Step 5: 實作 runner.build_research_prompt**

簽名加 `recent_summary: str | None = None`(keyword-only,放在 `output_mode` 之後)。在 `if previous_brief is not None:` 區塊之後加:
```python
    if recent_summary:
        parts.append(recent_summary)
```
files 模式那段的 `"寫完用 pmb/schemas 驗證(載入 Brief / Script 做 model_validate_json),不過就修正重寫。\n"` 改為:
```python
            f"寫完**務必執行** `poetry run pmb validate-research --date {date}`"
            "(schema、字數、反重複、欄位字數、數字一致都會檢查),有任何一條錯誤就修正檔案再跑,"
            "直到印出「全部通過」。\n"
```
若 `tests/test_runner.py` 有斷言舊句子,同步改成斷言 `"pmb validate-research"`。

- [ ] **Step 6: 實作 CLI 指令**(`pmb/cli.py`)

import 區 `from pmb.research.local_runner import SHORTS_CAP_SEC` 改為 `from pmb.research.local_runner import SHORTS_CAP_SEC, validate_research_artifacts`。在 `cmd_research_local` 之前加:
```python
def cmd_validate_research(args: argparse.Namespace) -> int:
    """檢查研究產物(schema + 字數 + 反重複 + 風格);研究 agent 寫完檔後自己跑、有錯就修。"""
    settings = get_settings()
    explicit = dt.date.fromisoformat(args.date) if args.date else None
    target = resolve_fetch_target(today_eastern(), explicit)
    if target is None:
        print("今天非 NYSE 交易日,skip。")
        return 0
    errors = validate_research_artifacts(settings.artifacts_dir, target)
    if not errors:
        print(f"全部通過({target})")
        return 0
    print(f"{target} 研究產物有 {len(errors)} 個問題,請修正後再跑一次:")
    for err in errors:
        print(f"- {err}")
    return 1
```
`build_parser()` 內(`rlocal` 附近)加:
```python
    vres = sub.add_parser(
        "validate-research", help="檢查今日研究產物(schema/字數/反重複/風格),供研究 agent 自修"
    )
    vres.add_argument("--date", help="指定交易日 YYYY-MM-DD")
    vres.set_defaults(func=cmd_validate_research)
```

- [ ] **Step 7: 跑全部測試**

Run: `poetry run pytest -q && poetry run ruff check .`
Expected: 全綠

- [ ] **Step 8: Commit**

```bash
git add pmb/research/local_runner.py pmb/research/runner.py pmb/cli.py tests/
git commit -m "feat(research): 驗證納入反重複軟規則、prompt 附最近 5 天回顧、新增 pmb validate-research 自檢

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: 抽出 `captions.py` / `ass.py`(純搬移,行為不變)

**Files:**
- Create: `pmb/video/captions.py`、`pmb/video/ass.py`
- Modify: `pmb/video/assemble.py`(刪掉搬走的程式,改 import)
- Modify: `tests/test_video.py:5-12` 及檔內各處 import、`tests/test_captions.py:6-12`

**Interfaces:**
- Produces:
  - `pmb.video.captions`:`has_speakable`、`split_sentences`、`build_srt`、`char_units(ch) -> float`、`text_units(text) -> float`、`wrap_lines(text, max_units=MAX_UNITS) -> list[str]`、`wrap_caption`、`CaptionPage`、`build_caption_pages`、常數 `MAX_UNITS=13`、`MAX_LINES=2`
  - `pmb.video.ass`:版面常數(`WIDTH, HEIGHT, BG_HEX, GOLD_HEX, BOTTOM_UI, RIGHT_UI, BADGE_TOP, TITLE_TOP, CHART_BAND_TOP, CHART_BOX_W, CHART_BOX_H, STAT_LABEL_TOP, STAT_TOP, SUB_MARGIN_V, CTA_MARGIN_V, CARD_CENTER_Y, CARD_FONT, CARD_LINE_H, CARD_MAX_UNITS, KICKER_GAP, CTA_SEC`)、`layout_safe_zone()`、`ASS_TEMPLATE`、`POP_IN`、`FADE_TAG`、`ass_time(seconds) -> str`、`full_event(style, seg_duration, text) -> str`、`common_events(seg_duration, *, badge, cta) -> list[str]`、`build_ass(...)`

- [ ] **Step 1: 建 `pmb/video/captions.py`**

模組 docstring:
```python
"""旁白斷句與字幕:逐句切分、依字寬斷行、逐頁卡拉OK對時、SRT。

從 video.assemble 拆出(v4),供 assemble 與各段型 renderer 共用。
"""
```
把 `assemble.py` 的下列定義**原封不動**搬進來(只改名稱如右):`_SENT_RE`、`has_speakable`、`split_sentences`、`_timestamp`、`build_srt`、`_BREAK_AFTER`、`_char_units` → `char_units`、`_is_ascii_alnum`、`_wrap_lines` → `wrap_lines`、`wrap_caption`、`CaptionPage`、`_char_spans_from_words`、`_char_spans_proportional`、`build_caption_pages`;常數 `_MAX_UNITS` → `MAX_UNITS = 13`、`_MAX_LINES` → `MAX_LINES = 2`(保留原註解)。所有內部引用跟著改名。新增:
```python
def text_units(text: str) -> float:
    """整段字寬(中文 1、英數 0.55),版面估寬用。"""
    return sum(char_units(ch) for ch in text)
```
需要的 import:`re`、`NamedTuple`、`from pmb.tts.edge import WordBoundary`。

- [ ] **Step 2: 建 `pmb/video/ass.py`**

模組 docstring:
```python
"""畫面版面常數與 ASS 疊層共用元件(樣式模板、時間格式、角標/CTA)。

版面避開 YouTube Shorts 播放器 UI(見 ``layout_safe_zone``):底部約 400px、右側約 170px
不放文字。從 video.assemble 拆出(v4),供各段型 renderer 共用。
"""
```
把 `assemble.py` 的版面常數(`_WIDTH` 到 `_KICKER_GAP`,以及 `_CTA_SEC`)搬進來並去掉底線(`_WIDTH` → `WIDTH`…,`_CTA_MARGIN_V` → `CTA_MARGIN_V`,`_SUB_MARGIN_V` → `SUB_MARGIN_V`);`layout_safe_zone`、`_STYLE_FORMAT`、`_EVENT_FORMAT`、`_ASS_TEMPLATE` → `ASS_TEMPLATE`、`_POP_IN` → `POP_IN`、`_FADE_TAG` → `FADE_TAG`、`_ass_time` → `ass_time`、`build_ass`、`_full_event` → `full_event`、`_common_events` → `common_events` 原封搬入並跟著改名。`build_ass` 內用 `from pmb.video.captions import wrap_caption`。`_FPS`、`_GAP`、`_TAIL`、`_FADE_IN`、`_FADE_OUT`、`_ZOOM_AMOUNT`、`_SLIDE_PX`、`_SLIDE_SEC`、`_PROGRESS_H`、`_SHORTS_CAP` **留在 assemble.py**。

- [ ] **Step 3: 瘦身 `assemble.py`**

刪掉已搬走的定義,改為 import:
```python
from pmb.video.ass import (
    ASS_TEMPLATE,
    BG_HEX,
    CARD_CENTER_Y,
    CARD_LINE_H,
    CARD_MAX_UNITS,
    CHART_BAND_TOP,
    CHART_BOX_H,
    CHART_BOX_W,
    FADE_TAG,
    GOLD_HEX,
    HEIGHT,
    KICKER_GAP,
    POP_IN,
    WIDTH,
    ass_time,
    common_events,
    full_event,
)
from pmb.video.captions import build_caption_pages, split_sentences
```
(只 import 實際用到的;以 `ruff check` 的 F401/F821 為準增減。)`build_card_ass`、`build_segment_ass`、`_Take`、`segment_timeline`、`_png_size`、`_fit_box`、`_run_ffmpeg`、`_audio_graph`、`_render_segment_clip`、`_measure_loudness`、`finalize_master`、`assemble_video` 留在 assemble.py,內部引用改用新名稱。模組 docstring 最後補一句:「斷句/字幕在 ``video.captions``、版面與 ASS 元件在 ``video.ass``。」

- [ ] **Step 4: 更新測試 import**

`tests/test_video.py` 頂部:
```python
from pmb.video.ass import build_ass
from pmb.video.assemble import segment_timeline
from pmb.video.captions import build_srt, has_speakable, split_sentences, wrap_caption
```
檔內 `from pmb.video.assemble import layout_safe_zone` 改為 `from pmb.video.ass import layout_safe_zone`。
`tests/test_captions.py` 頂部:
```python
from pmb.video.assemble import _audio_graph, _fit_box, _Take, build_segment_ass
from pmb.video.captions import build_caption_pages
```

- [ ] **Step 5: 跑全部測試**

Run: `poetry run pytest -q && poetry run ruff check .`
Expected: 全綠(測試數與 Task 3 結束時相同)

- [ ] **Step 6: Commit**

```bash
git add pmb/video/ tests/test_video.py tests/test_captions.py
git commit -m "refactor(video): 斷句字幕抽成 captions.py、版面與 ASS 元件抽成 ass.py(行為不變)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: 段型註冊 + 雙聲配音 + 「……」停頓(chart/card 遷入 registry)

**Files:**
- Create: `pmb/video/segments/__init__.py`、`base.py`、`registry.py`、`chart.py`、`card.py`
- Modify: `pmb/video/captions.py`(斷句認「……」、`is_beat`、`strip_beat`)
- Modify: `pmb/video/assemble.py`(`SynthFn` 加聲線、Pass A/B 改用 registry、逐句 gap、`_audio_graph` 支援 gaps/lead_in/sfx、`_render_segment_clip` 加 `lead_in`/`sfx`;刪除 `_Take`、`build_card_ass`、`build_segment_ass`、`_GAP`、`_TAIL`)
- Modify: `pmb/config.py`(`tts_voice_a`、`tts_voice_b`)
- Modify: `pmb/cli.py`(`cmd_assemble` 的 synth_fn)
- Test: `tests/test_segments.py`(新)、`tests/test_video.py`、`tests/test_captions.py`

**Interfaces:**
- Consumes: Task 1 段型、Task 4 captions/ass。
- Produces(Task 6–10 依賴):
  - `pmb.video.captions.is_beat(sentence) -> bool`、`strip_beat(text) -> str`
  - `pmb.video.segments.base`:`GAP=0.18`、`BEAT_GAP=0.5`、`TAIL=0.35`、`CANVAS_HEX="#0D1B2A"`;`Utterance(text, voice="narrator", gap_after=GAP, caption=True)` 含 `.tts_text`;`Take(text, audio, duration, words, gap_after=GAP, caption=True)`;`plan_vo(vo, voice="narrator") -> list[Utterance]`;`append_outro(utterances, outro) -> list[Utterance]`;`take_starts(takes, lead_in=0.0) -> list[float]`;`segment_duration(takes, *, lead_in=0.0, min_duration=0.0) -> float`;`caption_events(takes, starts) -> list[str]`;`RenderContext(index, duration, takes, starts, font, work_dir, badge=None, cta=None, chart_paths={})`;`Visual(image, is_card, ass, stem, sfx=None)`;`SegmentRenderer`(ABC:`lead_in=0.0`、`min_duration=0.0`、`utterances(seg)`、`render(seg, ctx) -> Visual`);`canvas_background(work_dir) -> str`
  - `SegmentRenderer.optional: bool = False`(True 的段配音失敗時略過該段而不是讓整支片失敗;Task 10 的 sting 用)
  - `pmb.video.segments.registry.renderer_for(kind: str) -> SegmentRenderer`(新增段型 = 在 `_RENDERERS` 加一行)
  - `pmb.video.segments.chart.build_segment_ass(takes, seg_duration, *, title, font, stat=None, stat_label=None, badge=None, cta=None, starts=None) -> str`、`ChartRenderer`
  - `pmb.video.segments.card.build_card_ass(headline, *, tag, duration, font, badge=None, cta=None) -> str`、`CardRenderer`
  - `assemble.SynthFn = Callable[[str, Path, float, VoiceKey], SynthResult]`
  - `assemble._audio_graph(n_takes, seg_duration, *, gaps=None, lead_in=0.0, sfx_input=None) -> str`

- [ ] **Step 1: 寫失敗測試** `tests/test_segments.py`

```python
"""段型 renderer 共用機制測試:句子計畫、停頓、時間軸、registry(不跑 ffmpeg)。"""

import pytest

from pmb.video.captions import is_beat, split_sentences, strip_beat
from pmb.video.segments.base import (
    BEAT_GAP,
    GAP,
    TAIL,
    Take,
    Utterance,
    append_outro,
    caption_events,
    plan_vo,
    segment_duration,
    take_starts,
)
from pmb.video.segments.registry import renderer_for


def test_ellipsis_ends_a_sentence_and_marks_a_beat():
    out = split_sentences("好消息是Fed說不急……壞消息是債市沒在聽。")
    assert out == ["好消息是Fed說不急……", "壞消息是債市沒在聽。"]
    assert is_beat(out[0]) and not is_beat(out[1])
    assert is_beat("先別急⋯⋯」")
    assert strip_beat("不急……") == "不急"


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
    assert len(events) == 1 and "旁白句" in events[0]
    assert events[0].startswith("Dialogue: 0,0:00:01.18")


def test_append_outro_adds_once():
    utts = [Utterance("金句。")]
    assert append_outro(utts, "以上非投資建議,明天盤前見。")[-1].text == "以上非投資建議,明天盤前見。"
    already = [Utterance("金句。"), Utterance("以上非投資建議,明天盤前見。")]
    assert append_outro(already, "以上非投資建議,明天盤前見。") == already
    assert append_outro(utts, None) == utts


def test_registry_knows_chart_and_card_and_rejects_unknown():
    assert renderer_for("chart") is not None and renderer_for("card") is not None
    with pytest.raises(ValueError):
        renderer_for("hologram")
```

在 `tests/test_captions.py` 檔尾加:
```python
def test_audio_graph_mixed_gaps_lead_in_and_sfx():
    g = _audio_graph(2, 5.0, gaps=[0.5], lead_in=0.15, sfx_input=3)
    assert "d=0.150[lead]" in g and "d=0.500[g0]" in g
    assert "concat=n=4:v=0:a=1" in g  # lead + a0 + g0 + a1
    assert "[3:a]" in g and "amix=inputs=2" in g
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `poetry run pytest tests/test_segments.py tests/test_captions.py -q`
Expected: FAIL(`ModuleNotFoundError: pmb.video.segments`)

- [ ] **Step 3: captions.py 加停頓斷句**

`_SENT_RE` 改為(句末可以是一般標點,或一串刪節號 + 選配標點):
```python
# 句尾標點不含 ASCII 句點「.」,否則 3.8% 這類小數會被誤切。「……」(或「⋯⋯」)也算句末:
# 冷面反差的 punchline 前停一拍(見 is_beat)。
_SENT_RE = re.compile(r"[^。!?！?;;；\n…⋯]+(?:[…⋯]+[。!?！?;;；」』)）]*|[。!?！?;;；])?")
_BEAT_RE = re.compile(r"[…⋯]+[。!?！?;;；」』)）]*$")


def is_beat(sentence: str) -> bool:
    """這句以「……」收尾 → 念完要停一拍(punchline 前的空檔)。"""
    return bool(_BEAT_RE.search(sentence.strip()))


def strip_beat(text: str) -> str:
    """送 TTS 前拿掉刪節號(停頓由合成端的句間空白負責;字幕保留)。"""
    return text.replace("…", "").replace("⋯", "")
```
`split_sentences` 其餘邏輯不變(純符號碎片如「⋯⋯」仍併回前句)。

- [ ] **Step 4: 建 `pmb/video/segments/base.py`**

```python
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

from pmb.charts.cards import render_card_background
from pmb.schemas.script import VoiceKey
from pmb.tts.edge import WordBoundary
from pmb.video.ass import ass_time
from pmb.video.captions import build_caption_pages, is_beat, split_sentences, strip_beat

GAP = 0.18  # 句間呼吸(秒)
BEAT_GAP = 0.5  # 「……」後停一拍:冷面反差的 punchline 前
TAIL = 0.35  # 段尾停頓(秒)
CANVAS_HEX = "#0D1B2A"  # 與 charts.library._CANVAS 一致


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


class Visual(NamedTuple):
    image: str  # work_dir 內底圖檔名
    is_card: bool  # True = 全屏底圖;False = 圖表框(縮排 + 滑入)
    ass: str  # 完整 .ass 內容
    stem: str  # .ass 檔名前綴(seg / card / dialogue …)
    sfx: str | None = None  # 段首疊的音效檔(絕對路徑)


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
    """新段型共用的畫布色底圖(一支片只畫一次)。"""
    name = "canvas_bg.png"
    if not (work_dir / name).exists():
        render_card_background(str(work_dir / name), accent=CANVAS_HEX)
    return name
```

- [ ] **Step 5: 建 `chart.py`、`card.py`、`registry.py`、`__init__.py`**

`pmb/video/segments/__init__.py`:
```python
"""段型 renderer:每種 kind 一個模組,由 registry 對應(見 base.SegmentRenderer)。"""
```

`pmb/video/segments/chart.py`:把 assemble.py 的 `build_segment_ass` 搬來,改為使用 `take_starts`/`caption_events`:
```python
"""圖表段:圖表框 + 頂部標題 + 大數字 callout + 逐頁卡拉OK字幕。"""

from __future__ import annotations

from pmb.schemas.script import ChartSegment
from pmb.video.ass import ASS_TEMPLATE, FADE_TAG, POP_IN, common_events, full_event
from pmb.video.segments.base import (
    RenderContext,
    SegmentRenderer,
    Take,
    Visual,
    caption_events,
    take_starts,
)


def build_segment_ass(
    takes: list[Take],
    seg_duration: float,
    *,
    title: str | None,
    font: str,
    stat: str | None = None,
    stat_label: str | None = None,
    badge: str | None = None,
    cta: str | None = None,
    starts: list[float] | None = None,
) -> str:
    """組圖表段用的 .ass:逐頁卡拉OK字幕(含句間偏移)+ 頂部標題 + 大數字 callout + 角標/CTA。

    callout(``stat``/``stat_label``)疊在圖表下方的留白處;沒給就不畫,舊 script 相容。
    """
    events: list[str] = []
    if title:
        events.append(full_event("title", seg_duration, FADE_TAG + title))
    if stat:
        if stat_label:
            events.append(full_event("statlabel", seg_duration, FADE_TAG + stat_label))
        events.append(full_event("stat", seg_duration, POP_IN + stat))
    events += common_events(seg_duration, badge=badge, cta=cta)
    events += caption_events(takes, starts if starts is not None else take_starts(takes))
    return ASS_TEMPLATE.format(font=font, events="\n".join(events))


class ChartRenderer(SegmentRenderer):
    def render(self, seg: ChartSegment, ctx: RenderContext) -> Visual:
        ass = build_segment_ass(
            ctx.takes, ctx.duration, title=seg.title, font=ctx.font, stat=seg.stat,
            stat_label=seg.stat_label, badge=ctx.badge, cta=ctx.cta, starts=ctx.starts,
        )
        return Visual(ctx.chart_paths[seg.chart_id], False, ass, "seg")
```

`pmb/video/segments/card.py`:把 assemble.py 的 `build_card_ass` 原封搬來(內部常數改用 `pmb.video.ass` 的 `CARD_CENTER_Y`、`CARD_LINE_H`、`CARD_MAX_UNITS`、`KICKER_GAP`、`POP_IN`、`FADE_TAG`、`ASS_TEMPLATE`、`full_event`、`common_events`),並加:
```python
class CardRenderer(SegmentRenderer):
    def render(self, seg: CardSegment, ctx: RenderContext) -> Visual:
        name = f"card{ctx.index}.png"
        render_card_background(str(ctx.work_dir / name), accent=accent_for(ctx.index))
        ass = build_card_ass(
            seg.headline, tag=seg.tag, duration=ctx.duration, font=ctx.font,
            badge=ctx.badge, cta=ctx.cta,
        )
        return Visual(name, True, ass, "card")
```
(import `accent_for, render_card_background` from `pmb.charts.cards`;模組 docstring「字卡:漸層底 + ASS 大標 pop-in + kicker。」)

`pmb/video/segments/registry.py`:
```python
"""kind → renderer 對應表。新增段型:寫一個 SegmentRenderer 子類別,在 _RENDERERS 註冊一行。"""

from __future__ import annotations

from pmb.video.segments.base import SegmentRenderer
from pmb.video.segments.card import CardRenderer
from pmb.video.segments.chart import ChartRenderer

_RENDERERS: dict[str, SegmentRenderer] = {
    "chart": ChartRenderer(),
    "card": CardRenderer(),
}


def renderer_for(kind: str) -> SegmentRenderer:
    try:
        return _RENDERERS[kind]
    except KeyError:
        raise ValueError(f"沒有段型「{kind}」的 renderer") from None
```

- [ ] **Step 6: 改 assemble.py**

1. 刪除 `_Take`、`build_card_ass`、`build_segment_ass`、`_GAP`、`_TAIL`(移到 segments)。import:
```python
from pmb.schemas.script import VoiceKey
from pmb.video.captions import has_speakable
from pmb.video.segments.base import GAP, RenderContext, Take, segment_duration, take_starts
from pmb.video.segments.registry import renderer_for
```
2. `SynthFn`:
```python
# synth_fn(text, out_path, planned_duration, voice) -> SynthResult;voice 是 narrator / a / b
SynthFn = Callable[[str, Path, float, VoiceKey], SynthResult]
_SEC_PER_CHAR = 0.18  # 估長(dry-run 靜音配音長度用;實際段長一律以實測為準)


def _planned_seconds(text: str) -> float:
    return max(0.6, len(text) * _SEC_PER_CHAR)
```
3. `_audio_graph` 換成:
```python
def _audio_graph(
    n_takes: int,
    seg_duration: float,
    *,
    gaps: list[float] | None = None,
    lead_in: float = 0.0,
    sfx_input: int | None = None,
) -> str:
    """句音串接子圖:takes 為輸入 1..n,段首可留 ``lead_in`` 靜音、句間插各自的停頓、
    段尾 pad 到段長;``sfx_input`` 給了就把該輸入的音效從段首疊上。輸出 [a]。"""
    gaps = list(gaps) if gaps is not None else [GAP] * max(n_takes - 1, 0)
    parts: list[str] = []
    for i in range(n_takes):
        parts.append(
            f"[{i + 1}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=mono[a{i}]"
        )
    items: list[str] = []
    if lead_in > 0:
        parts.append(f"anullsrc=r=44100:cl=mono:d={lead_in:.3f}[lead]")
        items.append("[lead]")
    gap_labels: list[str] = []
    if n_takes > 1:
        n_gaps = n_takes - 1
        if len(set(gaps)) == 1:  # 停頓一樣長:一個靜音源 asplit(舊行為)
            gap_labels = [f"[g{i}]" for i in range(n_gaps)]
            if n_gaps == 1:
                parts.append(f"anullsrc=r=44100:cl=mono:d={gaps[0]}[g0]")
            else:
                parts.append(f"anullsrc=r=44100:cl=mono:d={gaps[0]}[gsrc]")
                parts.append(f"[gsrc]asplit={n_gaps}{''.join(gap_labels)}")
        else:
            for i, gap in enumerate(gaps):
                parts.append(f"anullsrc=r=44100:cl=mono:d={gap:.3f}[g{i}]")
                gap_labels.append(f"[g{i}]")
    for i in range(n_takes):
        items.append(f"[a{i}]")
        if i < len(gap_labels):
            items.append(gap_labels[i])
    if len(items) == 1:
        chain = items[0]
    else:
        parts.append(f"{''.join(items)}concat=n={len(items)}:v=0:a=1[acat]")
        chain = "[acat]"
    out = "[a]" if sfx_input is None else "[vo]"
    parts.append(f"{chain}apad=whole_dur={seg_duration:.3f}{out}")
    if sfx_input is not None:
        parts.append(
            f"[{sfx_input}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=mono[sfx]"
        )
        parts.append("[vo][sfx]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
    return ";".join(parts)
```
4. `_render_segment_clip` 簽名加 `lead_in: float = 0.0, sfx: str | None = None`;`takes: list[Take]`。音訊那行改為:
```python
    chain.append(
        _audio_graph(
            len(takes), seg_duration, gaps=[t.gap_after for t in takes[:-1]], lead_in=lead_in,
            sfx_input=len(takes) + 1 if sfx else None,
        )
    )
```
`args` 在 takes 的 `-i` 之後加:`if sfx: args += ["-i", sfx]`。
5. `assemble_video` 的 Pass A/B 換成(保留原本的 chart_paths、`starts, total = segment_timeline(...)`、Shorts 上限警告、badge、concat、母帶):
```python
    # Pass A:各段的句子計畫 → 逐句配音 + 實測長度 → 段長與全片時間軸(進度條/收尾要用)
    units = list(enumerate(script.segments))
    seg_takes: list[list[Take]] = []
    seg_durations: list[float] = []
    usable: list[int] = []  # 有可配音內容的 unit 索引(其餘跳過,不讓一段壞掉整支片)
    for u, (i, seg) in enumerate(units):
        renderer = renderer_for(seg.kind)
        plan = [utt for utt in renderer.utterances(seg) if has_speakable(utt.tts_text)]
        if not plan:
            logger.warning("segment {}({})無可發音內容,跳過", i, seg.kind)
            seg_takes.append([])
            seg_durations.append(0.0)
            continue
        usable.append(u)
        takes: list[Take] = []
        for j, utt in enumerate(plan):
            audio_name = f"s{u}_{j}.mp3"
            result = synth_fn(
                utt.tts_text, work_dir / audio_name, _planned_seconds(utt.tts_text), utt.voice
            )
            measured = probe_duration(work_dir / audio_name)
            takes.append(Take(utt.text, audio_name, measured, result.words, utt.gap_after,
                              utt.caption))
        seg_takes.append(takes)
        seg_durations.append(
            segment_duration(takes, lead_in=renderer.lead_in, min_duration=renderer.min_duration)
        )
```
Pass B:
```python
    d = snapshot.session_date
    badge = f"{channel_name} · {d.month}/{d.day}"
    cta_text = f"明天盤前見 · 追蹤 {channel_name}"
    last_u = usable[-1] if usable else len(units) - 1
    clip_names: list[str] = []
    for u, (i, seg) in enumerate(units):
        takes = seg_takes[u]
        if not takes:
            continue  # Pass A 判定無可配音內容,已跳過
        renderer = renderer_for(seg.kind)
        is_last = u == last_u
        ctx = RenderContext(
            index=i, duration=seg_durations[u], takes=takes,
            starts=take_starts(takes, renderer.lead_in), font=font, work_dir=work_dir,
            badge=badge, cta=cta_text if (is_last and seg.kind == "card") else None,
            chart_paths=chart_paths,
        )
        visual = renderer.render(seg, ctx)
        ass_name = f"{visual.stem}{i}.ass"
        (work_dir / ass_name).write_text(visual.ass, encoding="utf-8")
        clip_name = f"clip{u}.mp4"
        _render_segment_clip(
            image=visual.image, is_card=visual.is_card, takes=takes,
            seg_duration=seg_durations[u], ass_name=ass_name, global_offset=starts[u],
            global_total=total, is_last=is_last, out=clip_name, work_dir=work_dir,
            lead_in=renderer.lead_in, sfx=visual.sfx,
        )
        clip_names.append(clip_name)
        logger.info("segment {}/{}({})完成({:.1f}s)", u + 1, len(units), seg.kind,
                    seg_durations[u])
```
並刪掉 Task 1 加的「段型尚未支援合成」檢查與舊的 card/chart 分支。模組 docstring 補:「段型各自的畫面與句子計畫在 ``video.segments``(registry)。」

6. `pmb/config.py` 在 `tts_pitch` 下加:
```python
    # 對話框的兩個角色聲線(a=男聲、b=女聲);旁白仍是 tts_voice。rate/pitch 三者共用
    tts_voice_a: str = "zh-TW-YunJheNeural"
    tts_voice_b: str = "zh-TW-HsiaoYuNeural"
```
7. `pmb/cli.py` `cmd_assemble` 的 synth_fn 兩支 lambda 換成:
```python
    if args.dry_run:
        logger.info("dry-run:用靜音配音合成,不打 edge-tts;跳過 BGM/響度母帶")
        synth_fn = lambda text, path, planned, voice: silent_synth(  # noqa: E731
            text, path, duration=planned
        )
    else:
        rate, pitch = settings.tts_rate, settings.tts_pitch
        voices = {
            "narrator": settings.tts_voice, "a": settings.tts_voice_a, "b": settings.tts_voice_b,
        }
        synth_fn = lambda text, path, planned, voice: edge_synthesize(  # noqa: E731
            text, path, voice=voices[voice], rate=rate, pitch=pitch
        )
```

- [ ] **Step 7: 更新舊測試**

`tests/test_video.py`:
- `_take` helper 改為:
```python
def _take(text: str, duration: float = 2.0):
    from pmb.video.segments.base import Take

    return Take(text, "x.mp3", duration, [])
```
- `from pmb.video.assemble import build_card_ass` → `from pmb.video.segments.card import build_card_ass`;`from pmb.video.assemble import build_segment_ass` → `from pmb.video.segments.chart import build_segment_ass`。
- `test_assemble_video_wires_card_ass_stat_badge_and_cta` 的 synth lambda 改為 `lambda text, path, planned, voice: silent_synth(text, path, duration=1.0)`。

`tests/test_captions.py` import 改為:
```python
from pmb.video.assemble import _audio_graph, _fit_box
from pmb.video.captions import build_caption_pages
from pmb.video.segments.base import Take as _Take
from pmb.video.segments.chart import build_segment_ass
```

- [ ] **Step 8: 跑全部測試**

Run: `poetry run pytest -q && poetry run ruff check .`
Expected: 全綠

- [ ] **Step 9: dry-run 煙霧(用 fixture 舊檔)確認合成沒退步**

Run:
```bash
poetry run python - <<'EOF'
import datetime as dt, json
from pathlib import Path
from pmb.schemas.script import Script
from pmb.schemas.snapshot import Snapshot
from pmb.tts.edge import silent_synth
from pmb.video.assemble import assemble_video
main = Path("/Users/sweslo17/Documents/code/us-invesment-analysis-video/artifacts")
script = Script.model_validate_json(Path("tests/fixtures/legacy_script_2026-09-29.json").read_text())
snap = Snapshot.model_validate_json((main / "snapshot_2026-09-29.json").read_text())
out = assemble_video(script, snap, Path("/tmp/pmb_t5.mp4"),
    synth_fn=lambda t, p, planned, v: silent_synth(t, p, duration=planned),
    work_dir=Path("/tmp/pmb_t5_work"), font="PingFang TC", master_audio=False)
print(out, out.stat().st_size)
EOF
```
Expected: 印出 mp4 路徑與大小 > 0(`/tmp` 只放暫存,不入庫)。

- [ ] **Step 10: Commit**

```bash
git add pmb/ tests/
git commit -m "refactor(video): 段型 renderer registry、逐句聲線與「……」停頓;chart/card 遷入 segments

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: `dialogue` 對話框(含 ASS 繪圖共用元件)

**Files:**
- Modify: `pmb/video/ass.py`(新增 `free` 樣式與繪圖/文字事件 helper)
- Create: `pmb/video/segments/dialogue.py`
- Modify: `pmb/video/segments/registry.py`(註冊 `dialogue`)
- Test: `tests/test_segments.py`

**Interfaces:**
- Consumes: Task 5 base/registry;`captions.wrap_lines`、`text_units`、`is_beat`、`has_speakable`、`strip_beat`。
- Produces(Task 7–10 依賴):
  - `ass.ass_color(hex_rgb: str) -> str`(`"#185FA5"` → `"&HA55F18&"`)
  - `ass.rounded_rect(w: int, h: int, r: int) -> str`(ASS 繪圖路徑)
  - `ass.polygon(points: list[tuple[float, float]], size: float) -> str`
  - `ass.shape_event(start, end, x, y, path, color, *, move_px=24) -> str`(layer 0)
  - `ass.text_event(start, end, x, y, text, *, size, color, align=7, move_px=24) -> str`(layer 1)
  - `ASS_TEMPLATE` 新增 `free` 樣式(字型 {font}、60px、白、無邊框、Alignment 7)
  - `dialogue.speakable_lines(seg) -> list[DialogueLine]`、`dialogue.bubble_layout(text) -> tuple[list[str], int]`、`DialogueRenderer`

- [ ] **Step 1: 寫失敗測試**(加到 `tests/test_segments.py`)

```python
from pathlib import Path

from pmb.schemas.script import DialogueSegment
from pmb.video.ass import ass_color, rounded_rect
from pmb.video.segments.base import RenderContext
from pmb.video.segments.dialogue import bubble_layout, speakable_lines


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
    lines, fs = bubble_layout("短句")
    assert lines == ["短句"] and fs == 60
    lines, fs = bubble_layout("這一句真的超級超級超級超級超級超級長,長到兩行都裝不下喔")
    assert fs == 48 and len(lines) == 2
    lines, fs = bubble_layout("字" * 60)
    assert len(lines) == 2 and lines[1].endswith("…")
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `poetry run pytest tests/test_segments.py -q`
Expected: FAIL(`ImportError: ass_color`)

- [ ] **Step 3: `ass.py` 加共用元件**

在 `ASS_TEMPLATE` 的 cta 樣式之後、`""` 之前加一行(注意這是一般字串,不是 f-string):
```python
        # 自由定位:新段型的色塊/圖示/文字都用它,位置與字級由事件的 override 決定
        "Style: free,{font},60,&H00FFFFFF,&H00FFFFFF,&H00201810,&H00000000,1,1,0,0,7,0,0,0",
```
檔尾加:
```python
def ass_color(hex_rgb: str) -> str:
    """``#RRGGBB`` → ASS 的 ``&HBBGGRR&``。"""
    h = hex_rgb.lstrip("#").upper()
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&"


def rounded_rect(w: int, h: int, r: int) -> str:
    """圓角矩形的 ASS 繪圖路徑(左上為原點)。"""
    r = max(0, min(r, w // 2, h // 2))
    return (
        f"m {r} 0 l {w - r} 0 b {w} 0 {w} 0 {w} {r} l {w} {h - r} b {w} {h} {w} {h} {w - r} {h} "
        f"l {r} {h} b 0 {h} 0 {h} 0 {h - r} l 0 {r} b 0 0 0 0 {r} 0"
    )


def polygon(points: list[tuple[float, float]], size: float) -> str:
    """0–1 正規化座標的多邊形 → 邊長 ``size`` 的 ASS 繪圖路徑(✓/✗ 圖示用)。"""
    pts = [(round(x * size), round(y * size)) for x, y in points]
    (x0, y0), rest = pts[0], pts[1:]
    return f"m {x0} {y0} l " + " ".join(f"{x} {y}" for x, y in rest)


def _slide_in(x: int, y: int, move_px: int) -> str:
    return f"\\move({x},{y + move_px},{x},{y},0,160)\\fad(120,0)"


def shape_event(
    start: float, end: float, x: int, y: int, path: str, color: str, *, move_px: int = 24
) -> str:
    """色塊/圖示事件(layer 0,在文字下面):從下方滑入 + 淡入。"""
    tags = f"{{\\an7{_slide_in(x, y, move_px)}\\bord0\\shad0\\1c{color}\\p1}}"
    return f"Dialogue: 0,{ass_time(start)},{ass_time(end)},free,,0,0,0,,{tags}{path}{{\\p0}}"


def text_event(
    start: float,
    end: float,
    x: int,
    y: int,
    text: str,
    *,
    size: int,
    color: str,
    align: int = 7,
    move_px: int = 24,
) -> str:
    """文字事件(layer 1,蓋在色塊上):``align`` 是 ASS 數字鍵盤對齊(7 左上、9 右上、5 置中)。"""
    tags = f"{{\\an{align}{_slide_in(x, y, move_px)}\\fs{size}\\1c{color}\\bord0\\shad0}}"
    return f"Dialogue: 1,{ass_time(start)},{ass_time(end)},free,,0,0,0,,{tags}{text}"
```

- [ ] **Step 4: 建 `pmb/video/segments/dialogue.py`**

```python
"""對話框:2–4 句,泡泡隨各自配音逐句彈出(A 角靠左藍、B 角靠右琥珀)。

泡泡句不跑底部字幕(泡泡本身就是字);``vo`` 旁白部分照常卡拉OK字幕。
沒有可發音內容的句子(如「……?」)在句子計畫與畫面兩邊**同一套規則**剔除,泡泡與配音不錯位。
"""

from __future__ import annotations

from loguru import logger

from pmb.schemas.script import DialogueLine, DialogueSegment
from pmb.video.ass import (
    ASS_TEMPLATE,
    FADE_TAG,
    ass_color,
    common_events,
    full_event,
    rounded_rect,
    shape_event,
    text_event,
)
from pmb.video.captions import has_speakable, is_beat, strip_beat, text_units, wrap_lines
from pmb.video.segments.base import (
    BEAT_GAP,
    GAP,
    RenderContext,
    SegmentRenderer,
    Utterance,
    Visual,
    canvas_background,
    caption_events,
    plan_vo,
)

_SLOT_TOPS = (300, 530, 760, 990)  # 4 個固定槽位的頂緣(每槽約 230px)
_LABEL_FS = 40
_LABEL_GAP = 52  # 角色名頂緣到泡泡頂緣
_BUBBLE_LAYOUTS = ((60, 12), (48, 15))  # (字級, 每行字寬):先大字,超過 2 行改小字
_PAD = 22
_RADIUS = 26
_LEFT_X = 70
_RIGHT_EDGE = 870  # B 角泡泡右緣(右側 170px 是按讚欄)
_COLORS = {"a": ("#185FA5", "#85B7EB"), "b": ("#854F0B", "#FAC775")}  # (泡泡, 角色名)
_TEXT_HEX = "#FFFFFF"


def speakable_lines(seg: DialogueSegment) -> list[DialogueLine]:
    return [line for line in seg.lines if has_speakable(strip_beat(line.text))]


def bubble_layout(text: str) -> tuple[list[str], int]:
    """泡泡內文斷行 + 字級:60px 每行 12 字寬;超過 2 行改 48px 每行 15 字寬;仍超過截成 2 行。"""
    for size, units in _BUBBLE_LAYOUTS:
        lines = wrap_lines(text, units)
        if len(lines) <= 2:
            return lines, size
    size, units = _BUBBLE_LAYOUTS[-1]
    lines = wrap_lines(text, units)
    logger.warning("對話泡泡過長,截成兩行:{}", text)
    return [lines[0], lines[1].rstrip() + "…"], size


def build_dialogue_ass(seg: DialogueSegment, ctx: RenderContext) -> str:
    events: list[str] = []
    if seg.title:
        events.append(full_event("title", ctx.duration, FADE_TAG + seg.title))
    events += common_events(ctx.duration, badge=ctx.badge, cta=ctx.cta)
    for k, line in enumerate(speakable_lines(seg)[: len(_SLOT_TOPS)]):
        start = ctx.starts[k]
        top = _SLOT_TOPS[k]
        lines, size = bubble_layout(line.text)
        w = int(max(text_units(t) for t in lines) * size) + 2 * _PAD
        h = len(lines) * int(size * 1.2) + 2 * _PAD
        x = _LEFT_X if line.voice == "a" else _RIGHT_EDGE - w
        bubble_hex, label_hex = _COLORS[line.voice]
        label_x, label_align = (x, 7) if line.voice == "a" else (x + w, 9)
        events.append(
            text_event(start, ctx.duration, label_x, top, line.speaker, size=_LABEL_FS,
                       color=ass_color(label_hex), align=label_align)
        )
        events.append(
            shape_event(start, ctx.duration, x, top + _LABEL_GAP, rounded_rect(w, h, _RADIUS),
                        ass_color(bubble_hex))
        )
        events.append(
            text_event(start, ctx.duration, x + _PAD, top + _LABEL_GAP + _PAD, "\\N".join(lines),
                       size=size, color=ass_color(_TEXT_HEX))
        )
    events += caption_events(ctx.takes, ctx.starts)
    return ASS_TEMPLATE.format(font=ctx.font, events="\n".join(events))


class DialogueRenderer(SegmentRenderer):
    def utterances(self, seg: DialogueSegment) -> list[Utterance]:
        lines = [
            Utterance(line.text, line.voice, BEAT_GAP if is_beat(line.text) else GAP, False)
            for line in speakable_lines(seg)
        ]
        return lines + plan_vo(seg.vo)

    def render(self, seg: DialogueSegment, ctx: RenderContext) -> Visual:
        return Visual(canvas_background(ctx.work_dir), True, build_dialogue_ass(seg, ctx),
                      "dialogue")
```

注意:右側角色名以 `\an9` 對齊在 `x + w`(= 870)——`test_dialogue_bubbles_pop_at_their_take_start` 的 x ≤ 910 斷言涵蓋它。

- [ ] **Step 5: 註冊**

`registry.py` import `from pmb.video.segments.dialogue import DialogueRenderer`,`_RENDERERS` 加 `"dialogue": DialogueRenderer(),`。

- [ ] **Step 6: 跑全部測試**

Run: `poetry run pytest -q && poetry run ruff check .`
Expected: 全綠

- [ ] **Step 7: Commit**

```bash
git add pmb/video/ tests/test_segments.py
git commit -m "feat(video): 對話框段型——雙聲泡泡隨配音逐句彈出(ASS 繪圖圓角框)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: `split` 好壞消息

**Files:**
- Create: `pmb/video/segments/split.py`
- Modify: `pmb/video/segments/registry.py`
- Test: `tests/test_segments.py`

**Interfaces:**
- Consumes: Task 6 的 `ass_color`、`rounded_rect`、`shape_event`、`text_event`;Task 5 base。
- Produces:`split.reveal_times(ctx) -> tuple[float, float]`、`split.panel_text_layout(text, *, has_stat) -> tuple[list[str], int]`、`SplitRenderer`

- [ ] **Step 1: 寫失敗測試**(加到 `tests/test_segments.py`)

```python
from pmb.schemas.script import SplitSegment
from pmb.video.segments.split import panel_text_layout, reveal_times


def _split(vo="好消息是Fed說不急。壞消息是債市沒在聽。", **kw):
    return SplitSegment(vo=vo, top={"label": "好消息", "text": kw.get("top", "Fed說不急"),
                                    "tone": "good"},
                        bottom={"label": "壞消息", "text": "債市沒在聽", "stat": "5.26%",
                                "tone": "bad"})


def test_split_bottom_panel_appears_at_second_sentence(tmp_path):
    takes = [Take("好消息是Fed說不急。", "a.mp3", 2.0, []), Take("壞消息是債市沒在聽。", "b.mp3", 2.0, [])]
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
    lines, size = panel_text_layout("字" * 40, has_stat=True)
    assert len(lines) <= 2
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `poetry run pytest tests/test_segments.py -q`
Expected: FAIL(`ModuleNotFoundError: pmb.video.segments.split`)

- [ ] **Step 3: 實作 `pmb/video/segments/split.py`**

```python
"""好壞消息:上下兩格色塊。上格段首出現,下格在旁白第 2 句開始時出現(冷面反差的主場)。"""

from __future__ import annotations

from loguru import logger

from pmb.schemas.script import Panel, SplitSegment
from pmb.video.ass import (
    ASS_TEMPLATE,
    FADE_TAG,
    GOLD_HEX,
    ass_color,
    common_events,
    full_event,
    rounded_rect,
    shape_event,
    text_event,
)
from pmb.video.captions import wrap_lines
from pmb.video.segments.base import (
    RenderContext,
    SegmentRenderer,
    Visual,
    canvas_background,
    caption_events,
)

_X = 60
_W = 830  # 右緣 890,避開右側按讚欄
_TOPS = (290, 800)
_H = 470
_RADIUS = 28
_INSET = 40
_LABEL_FS = 48
_STAT_FS = 100
# (字級, 最多行數):有 stat 時字要讓位給數字
_LAYOUTS_WITH_STAT = ((96, 1), (80, 2))
_LAYOUTS_NO_STAT = ((96, 2), (80, 2))
_TONES = {  # (底色, 標籤色)
    "good": ("#173404", "#97C459"),
    "bad": ("#501313", "#F09595"),
    "neutral": ("#0C447C", "#85B7EB"),
}
_TEXT_HEX = "#FFFFFF"


def panel_text_layout(text: str, *, has_stat: bool) -> tuple[list[str], int]:
    """格子內文斷行 + 字級;都放不下就用最小字級截成允許的行數。"""
    layouts = _LAYOUTS_WITH_STAT if has_stat else _LAYOUTS_NO_STAT
    for size, max_lines in layouts:
        lines = wrap_lines(text, int((_W - 2 * _INSET) / size))
        if len(lines) <= max_lines:
            return lines, size
    size, max_lines = layouts[-1]
    logger.warning("好壞消息格子文字過長,截斷:{}", text)
    return wrap_lines(text, int((_W - 2 * _INSET) / size))[:max_lines], size


def reveal_times(ctx: RenderContext) -> tuple[float, float]:
    """上格段首;下格在第 2 句起點,只有 1 句就在段長一半。"""
    bottom = ctx.starts[1] if len(ctx.starts) >= 2 else ctx.duration * 0.5
    return 0.0, bottom


def _panel_events(panel: Panel, top: int, start: float, end: float) -> list[str]:
    bg_hex, label_hex = _TONES[panel.tone]
    events = [
        shape_event(start, end, _X, top, rounded_rect(_W, _H, _RADIUS), ass_color(bg_hex)),
        text_event(start, end, _X + _INSET, top + 36, panel.label, size=_LABEL_FS,
                   color=ass_color(label_hex)),
    ]
    lines, size = panel_text_layout(panel.text, has_stat=bool(panel.stat))
    events.append(text_event(start, end, _X + _INSET, top + 110, "\\N".join(lines), size=size,
                             color=ass_color(_TEXT_HEX)))
    if panel.stat:
        events.append(text_event(start, end, _X + _INSET, top + _H - 24, panel.stat,
                                 size=_STAT_FS, color=ass_color(GOLD_HEX), align=1))
    return events


class SplitRenderer(SegmentRenderer):
    def render(self, seg: SplitSegment, ctx: RenderContext) -> Visual:
        events: list[str] = []
        if seg.title:
            events.append(full_event("title", ctx.duration, FADE_TAG + seg.title))
        events += common_events(ctx.duration, badge=ctx.badge, cta=ctx.cta)
        top_at, bottom_at = reveal_times(ctx)
        events += _panel_events(seg.top, _TOPS[0], top_at, ctx.duration)
        events += _panel_events(seg.bottom, _TOPS[1], bottom_at, ctx.duration)
        events += caption_events(ctx.takes, ctx.starts)
        ass = ASS_TEMPLATE.format(font=ctx.font, events="\n".join(events))
        return Visual(canvas_background(ctx.work_dir), True, ass, "split")
```
(`GOLD_HEX` 在 ass.py 是 `"FFD166"`,`ass_color` 會處理沒有 `#` 的情況。)

- [ ] **Step 4: 註冊** `"split": SplitRenderer(),`(import `from pmb.video.segments.split import SplitRenderer`)

- [ ] **Step 5: 跑全部測試**

Run: `poetry run pytest -q && poetry run ruff check .`
Expected: 全綠

- [ ] **Step 6: Commit**

```bash
git add pmb/video/segments/ tests/test_segments.py
git commit -m "feat(video): 好壞消息段型——上下兩格,下格跟著第二句出現

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: `bignum` 全屏大數字(數字跳動)

**Files:**
- Create: `pmb/video/segments/bignum.py`
- Modify: `pmb/video/segments/registry.py`
- Test: `tests/test_segments.py`

**Interfaces:**
- Consumes: Task 6 `ass_color`、`text_event`;`captions.text_units`、`wrap_lines`。
- Produces:`ParsedNumber`、`parse_number(value) -> ParsedNumber | None`、`count_up_frames(value, seg_end, *, start=0.2, dur=0.6, fps=25) -> list[tuple[float, float, str]]`、`value_font_size(value) -> int`、`BignumRenderer`

- [ ] **Step 1: 寫失敗測試**

```python
from pmb.schemas.script import BignumSegment
from pmb.video.segments.bignum import count_up_frames, parse_number, value_font_size


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
    assert frames[-1] == (pytest.approx(0.5), 0.5, "5.26%") or frames[-1][2] == "5.26%"
    assert all(t0 < t1 for t0, t1, _ in frames)


def test_value_font_size_shrinks_for_wide_values():
    assert value_font_size("5.26%") == 260
    assert value_font_size("+16.2萬億美元") < 260


def test_bignum_render_has_label_context_and_frames(tmp_path):
    seg = BignumSegment(vo="十年期5.26%。", value="5.26%", label="10年期殖利率",
                        context="2007年以來最高")
    takes = [Take("十年期5.26%。", "a.mp3", 2.0, [])]
    visual = renderer_for("bignum").render(seg, _ctx(takes, duration=3.0, work_dir=tmp_path))
    assert visual.stem == "bignum"
    assert "10年期殖利率" in visual.ass and "2007年以來最高" in visual.ass
    assert visual.ass.count("5.26%") >= 2 and ",sub," in visual.ass
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `poetry run pytest tests/test_segments.py -q`
Expected: FAIL

- [ ] **Step 3: 實作 `pmb/video/segments/bignum.py`**

```python
"""全屏大數字:label → 大數字(0.2s 起、0.6s 內從 0 跳到定值)→ 一行脈絡;字幕照跑。

數字格式(正負號、千分位、小數位、單位)全程保留;解析不了就靜態顯示並記 WARNING。
"""

from __future__ import annotations

import re
from typing import NamedTuple

from loguru import logger

from pmb.schemas.script import BignumSegment
from pmb.video.ass import (
    ASS_TEMPLATE,
    GOLD_HEX,
    ass_color,
    ass_time,
    common_events,
    text_event,
)
from pmb.video.captions import text_units, wrap_lines
from pmb.video.segments.base import (
    RenderContext,
    SegmentRenderer,
    Visual,
    canvas_background,
    caption_events,
)

_CENTER_X = 540
_LABEL_Y = 560
_VALUE_Y = 820
_CONTEXT_Y = 1060
_LABEL_FS = 52
_VALUE_FS = 260
_VALUE_MAX_W = 740  # 置中 540 ± 370,右緣不碰按讚欄
_CONTEXT_FS = 60
_CONTEXT_UNITS = 12
_COUNT_START = 0.2
_COUNT_DUR = 0.6
_FPS = 25
_LABEL_HEX = "#8FA3B8"
_TEXT_HEX = "#FFFFFF"
_NUM_RE = re.compile(r"^(?P<prefix>\D*?)(?P<num>\d[\d,]*(?:\.\d+)?)(?P<suffix>.*)$")


class ParsedNumber(NamedTuple):
    prefix: str
    number: float
    suffix: str
    decimals: int
    commas: bool


def parse_number(value: str) -> ParsedNumber | None:
    match = _NUM_RE.match(value.strip())
    if match is None:
        return None
    raw = match.group("num")
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    return ParsedNumber(match.group("prefix"), float(raw.replace(",", "")), match.group("suffix"),
                        decimals, "," in raw)


def _format(p: ParsedNumber, x: float) -> str:
    body = f"{x:,.{p.decimals}f}" if p.commas else f"{x:.{p.decimals}f}"
    return f"{p.prefix}{body}{p.suffix}"


def count_up_frames(
    value: str,
    seg_end: float,
    *,
    start: float = _COUNT_START,
    dur: float = _COUNT_DUR,
    fps: int = _FPS,
) -> list[tuple[float, float, str]]:
    """逐幀 (起, 迄, 文字):0 → 目標值(ease-out),最後一幀停到段尾顯示原字串。"""
    parsed = parse_number(value)
    if parsed is None:
        logger.warning("大數字「{}」解析不了,改靜態顯示", value)
        return [(0.0, seg_end, value)]
    n = max(1, round(dur * fps))
    frames: list[tuple[float, float, str]] = [(0.0, start, _format(parsed, 0.0))]
    for k in range(n):
        eased = 1 - (1 - k / n) ** 3
        t0 = start + k / fps
        frames.append((t0, t0 + 1 / fps, _format(parsed, parsed.number * eased)))
    frames.append((start + n / fps, seg_end, value))
    # 段比動畫短:裁掉段尾之後的幀,最後一幀確保顯示定值
    kept = [(t0, min(t1, seg_end), text) for t0, t1, text in frames[:-1] if t0 < seg_end]
    final_start = min(start + n / fps, kept[-1][1] if kept else 0.0)
    if final_start < seg_end:
        kept.append((final_start, seg_end, value))
    else:
        kept[-1] = (kept[-1][0], seg_end, value)
    return [(t0, t1, text) for t0, t1, text in kept if t0 < t1]


def value_font_size(value: str) -> int:
    return min(_VALUE_FS, int(_VALUE_MAX_W / max(text_units(value), 0.1)))


class BignumRenderer(SegmentRenderer):
    def render(self, seg: BignumSegment, ctx: RenderContext) -> Visual:
        end = ctx.duration
        events = common_events(end, badge=ctx.badge, cta=ctx.cta)
        events.append(text_event(0.0, end, _CENTER_X, _LABEL_Y, seg.label, size=_LABEL_FS,
                                 color=ass_color(_LABEL_HEX), align=5))
        size, gold = value_font_size(seg.value), ass_color(GOLD_HEX)
        for t0, t1, text in count_up_frames(seg.value, end):
            events.append(
                f"Dialogue: 1,{ass_time(t0)},{ass_time(t1)},free,,0,0,0,,"
                f"{{\\an5\\pos({_CENTER_X},{_VALUE_Y})\\fs{size}\\1c{gold}\\bord0\\shad0}}{text}"
            )
        if seg.context:
            context = "\\N".join(wrap_lines(seg.context, _CONTEXT_UNITS))
            events.append(text_event(0.0, end, _CENTER_X, _CONTEXT_Y, context, size=_CONTEXT_FS,
                                     color=ass_color(_TEXT_HEX), align=5))
        events += caption_events(ctx.takes, ctx.starts)
        ass = ASS_TEMPLATE.format(font=ctx.font, events="\n".join(events))
        return Visual(canvas_background(ctx.work_dir), True, ass, "bignum")
```

實作者注意:`count_up_frames` 的段尾裁切邏輯以測試為準;若寫法可更簡潔且測試全過,可簡化(保持「最後一幀一定是原字串、所有幀 t0 < t1、不超過段尾」三個性質)。

- [ ] **Step 4: 註冊** `"bignum": BignumRenderer(),`

- [ ] **Step 5: 跑全部測試**

Run: `poetry run pytest -q && poetry run ruff check .`
Expected: 全綠

- [ ] **Step 6: Commit**

```bash
git add pmb/video/segments/ tests/test_segments.py
git commit -m "feat(video): 全屏大數字段型——數字從 0 跳到定值,格式全程保留

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: `recap` 對帳

**Files:**
- Create: `pmb/video/segments/recap.py`
- Modify: `pmb/video/segments/registry.py`
- Test: `tests/test_segments.py`

**Interfaces:**
- Consumes: Task 6 `ass_color`、`polygon`、`rounded_rect`、`shape_event`、`text_event`。
- Produces:`recap.row_times(n_rows, starts, duration) -> list[float]`、`recap.result_layout(text) -> tuple[list[str], int]`、`RecapRenderer`

- [ ] **Step 1: 寫失敗測試**

```python
from pmb.schemas.script import RecapSegment
from pmb.video.segments.recap import result_layout, row_times


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
    assert ass.count("\\p1") >= 3 + 2  # 三個 mark + 兩條分隔線
    # 2 句 < 3 列 → 三列平均分布在 6 秒段內:0 / 2 / 4 秒
    assert "Dialogue: 1,0:00:02.00" in ass and "Dialogue: 1,0:00:04.00" in ass


def test_recap_rows_follow_sentence_starts_when_enough_sentences(tmp_path):
    seg = RecapSegment(vo="一。二。", rows=[
        {"ask": "甲", "result": "乙", "mark": "yes"}, {"ask": "丙", "result": "丁", "mark": "no"}])
    takes = [Take("一。", "a.mp3", 2.0, []), Take("二。", "b.mp3", 1.0, [])]
    ass = renderer_for("recap").render(seg, _ctx(takes, duration=4.0, work_dir=tmp_path)).ass
    assert "Dialogue: 1,0:00:02.18" in ass  # 第二列在第二句起點


def test_result_layout_shrinks_long_results():
    assert result_layout("十月不急") == (["十月不急"], 72)
    lines, size = result_layout("這個結果寫得太長太長太長了吧")
    assert size == 60 and len(lines) <= 2
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `poetry run pytest tests/test_segments.py -q`
Expected: FAIL

- [ ] **Step 3: 實作 `pmb/video/segments/recap.py`**

```python
"""對帳:1–3 列「昨天說要看的 → 結果」,逐列跟著旁白出現;✓/✗/〰 用繪圖畫,不賭字型。"""

from __future__ import annotations

from pmb.schemas.script import RecapRow, RecapSegment
from pmb.video.ass import (
    ASS_TEMPLATE,
    FADE_TAG,
    ass_color,
    common_events,
    full_event,
    polygon,
    rounded_rect,
    shape_event,
    text_event,
)
from pmb.video.captions import text_units, wrap_lines
from pmb.video.segments.base import (
    RenderContext,
    SegmentRenderer,
    Visual,
    canvas_background,
    caption_events,
)

_DEFAULT_TITLE = "昨天說要看的"
_ROW_TOPS = (330, 580, 830)
_X = 70
_RESULT_X = 160
_MARK = 64
_ASK_FS = 44
_RESULT_LAYOUTS = ((72, 10), (60, 12))  # (字級, 每行字寬)
_SEP_W = 770
_ASK_HEX = "#8FA3B8"
_TEXT_HEX = "#FFFFFF"
_SEP_HEX = "#2A4058"
_CHECK = [(0.0, 0.55), (0.38, 0.92), (1.0, 0.18), (0.86, 0.05), (0.38, 0.66), (0.13, 0.42)]
_CROSS = [(0.15, 0.0), (0.5, 0.35), (0.85, 0.0), (1.0, 0.15), (0.65, 0.5), (1.0, 0.85),
          (0.85, 1.0), (0.5, 0.65), (0.15, 1.0), (0.0, 0.85), (0.35, 0.5), (0.0, 0.15)]
_MARK_HEX = {"yes": "#97C459", "no": "#F09595", "mixed": "#FAC775"}


def row_times(n_rows: int, starts: list[float], duration: float) -> list[float]:
    """第 k 列在第 k 句起點;句數不夠就所有列平均分布在段內。"""
    if len(starts) >= n_rows:
        return list(starts[:n_rows])
    return [duration * k / n_rows for k in range(n_rows)]


def result_layout(text: str) -> tuple[list[str], int]:
    size, units = _RESULT_LAYOUTS[0]
    if text_units(text) <= units:
        return [text], size
    size, units = _RESULT_LAYOUTS[1]
    return wrap_lines(text, units)[:2], size


def _mark_event(mark: str, start: float, end: float, x: int, y: int) -> str:
    color = ass_color(_MARK_HEX[mark])
    if mark == "yes":
        path = polygon(_CHECK, _MARK)
    elif mark == "no":
        path = polygon(_CROSS, _MARK)
    else:  # mixed:一條圓角橫槓
        path = rounded_rect(_MARK, 14, 7)
        y += (_MARK - 14) // 2
    return shape_event(start, end, x, y, path, color)


def _row_events(row: RecapRow, top: int, start: float, end: float, last: bool) -> list[str]:
    events = [
        text_event(start, end, _X, top, row.ask, size=_ASK_FS, color=ass_color(_ASK_HEX)),
        _mark_event(row.mark, start, end, _X, top + 62),
    ]
    lines, size = result_layout(row.result)
    events.append(text_event(start, end, _RESULT_X, top + 56, "\\N".join(lines), size=size,
                             color=ass_color(_TEXT_HEX)))
    if not last:
        events.append(shape_event(start, end, _X, top + 210, rounded_rect(_SEP_W, 2, 1),
                                  ass_color(_SEP_HEX)))
    return events


class RecapRenderer(SegmentRenderer):
    def render(self, seg: RecapSegment, ctx: RenderContext) -> Visual:
        events = [full_event("title", ctx.duration, FADE_TAG + (seg.title or _DEFAULT_TITLE))]
        events += common_events(ctx.duration, badge=ctx.badge, cta=ctx.cta)
        times = row_times(len(seg.rows), ctx.starts, ctx.duration)
        for k, (row, start) in enumerate(zip(seg.rows, times, strict=True)):
            events += _row_events(row, _ROW_TOPS[k], start, ctx.duration, k == len(seg.rows) - 1)
        events += caption_events(ctx.takes, ctx.starts)
        ass = ASS_TEMPLATE.format(font=ctx.font, events="\n".join(events))
        return Visual(canvas_background(ctx.work_dir), True, ass, "recap")
```

- [ ] **Step 4: 註冊** `"recap": RecapRenderer(),`

- [ ] **Step 5: 跑全部測試**

Run: `poetry run pytest -q && poetry run ruff check .`
Expected: 全綠

- [ ] **Step 6: Commit**

```bash
git add pmb/video/segments/ tests/test_segments.py
git commit -m "feat(video): 對帳段型——昨天說要看的逐列打勾

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: 開場口號轉場(音效)+ 收尾口號

**Files:**
- Create: `pmb/audio/sfx.py`、`pmb/video/segments/sting.py`
- Modify: `pmb/video/segments/registry.py`(註冊 `sting`)
- Modify: `pmb/video/assemble.py`(`assemble_video` 加 `slogan_intro`/`slogan_outro`/`sting_sfx`)
- Modify: `pmb/config.py`(`slogan_intro`/`slogan_outro` 新預設、`sting_enable`、`sfx_dir`)
- Modify: `pmb/cli.py`(`cmd_assemble` 傳入)
- Test: `tests/test_sfx.py`(新)、`tests/test_segments.py`、`tests/test_video.py`

**Interfaces:**
- Consumes: Task 5 `append_outro`、`Utterance`、registry;Task 6 `text_event`、`ass_color`。
- Produces:
  - `sfx.generate_sting(out_path) -> Path`、`sfx.resolve_sting_sfx(sfx_dir: Path, work_dir: Path) -> Path | None`
  - `sting.StingSegment(kind="sting", text, channel, sfx=None)`、`StingRenderer(lead_in=0.15, min_duration=1.2)`
  - `assemble_video(..., slogan_intro: str | None = None, slogan_outro: str | None = None, sting_sfx: str | Path | None = None)`

- [ ] **Step 1: 寫失敗測試**

`tests/test_sfx.py`:
```python
"""程序化轉場音效測試。"""

import wave

from pmb.audio.sfx import generate_sting, resolve_sting_sfx


def test_generate_sting_writes_short_mono_wav(tmp_path):
    out = generate_sting(tmp_path / "s.wav")
    with wave.open(str(out)) as fh:
        assert fh.getnchannels() == 1 and fh.getframerate() == 44100
        assert 0.4 < fh.getnframes() / 44100 < 0.7


def test_user_sfx_file_takes_priority(tmp_path):
    sfx_dir = tmp_path / "sfx"
    sfx_dir.mkdir()
    (sfx_dir / "sting.mp3").write_bytes(b"fake")
    assert resolve_sting_sfx(sfx_dir, tmp_path).name == "sting.mp3"
    assert resolve_sting_sfx(tmp_path / "none", tmp_path).name == "sting_sfx.wav"
```

`tests/test_segments.py` 加:
```python
from pmb.video.segments.sting import StingSegment


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
```

`tests/test_video.py` 加:
```python
def test_assemble_inserts_sting_after_hook_and_appends_outro(tmp_path):
    import datetime as dt

    from pmb.schemas.script import Script
    from pmb.schemas.snapshot import LeverageMath, Snapshot
    from pmb.tts.edge import silent_synth
    from pmb.video.assemble import assemble_video

    snap = Snapshot(
        session_date=dt.date(2026, 9, 30),
        generated_at=dt.datetime(2026, 9, 30, 12, 0, tzinfo=dt.UTC),
        leverage_math=[LeverageMath(market="S&P 500", realized_vol=0.165, vol_target_leverage=0.91,
                                    drag_1x=0.0136, drag_2x=0.0545, drag_3x=0.1226)],
    )
    script = Script.model_validate({
        "segments": [
            {"vo": "開場。", "headline": "債市暴走", "tag": "債市日"},
            {"vo": "圖表。", "chart_id": "lev", "stat": "1", "stat_label": "x"},
            {"vo": "金句。", "headline": "金句\n對句", "tag": "巴菲特 不知道有沒有說過"},
        ],
        "charts": [{"id": "lev", "module": "leverage_decay", "params": {}}],
    })
    spoken: list[tuple[str, str]] = []

    def synth(text, path, planned, voice):
        spoken.append((text, voice))
        return silent_synth(text, path, duration=0.5)

    work = tmp_path / "work"
    out = assemble_video(script, snap, tmp_path / "o.mp4", synth_fn=synth, work_dir=work,
                         font="PingFang TC", master_audio=False,
                         slogan_intro="美股早發車,發車!", slogan_outro="以上非投資建議,明天盤前見。")
    assert out.exists()
    texts = [t for t, _ in spoken]
    assert texts.index("美股早發車,發車!") == 1  # hook 之後
    assert texts[-1] == "以上非投資建議,明天盤前見。"
    assert (work / "sting0.ass").exists()
    clips = (work / "clips.txt").read_text().splitlines()
    assert len(clips) == 4
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `poetry run pytest tests/test_sfx.py tests/test_segments.py tests/test_video.py -q`
Expected: FAIL

- [ ] **Step 3: 實作 `pmb/audio/sfx.py`**

```python
"""程序化音效:開場口號轉場的「咻 + 叭叭」,呼應頻道名「早發車」。

``assets/sfx/`` 放了自備的 ``sting.*`` 就用自備的;否則純 numpy 合成,零版權疑慮。
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
from loguru import logger

_SR = 44100
_TOTAL_SEC = 0.55
_USER_NAMES = ("sting.wav", "sting.mp3", "sting.m4a")


def _horn(duration: float, freqs: tuple[float, ...] = (370.0, 466.16)) -> np.ndarray:
    """短喇叭:兩音和聲、帶點方波的粗糙感,快起音快收。"""
    t = np.arange(int(duration * _SR)) / _SR
    tone = sum(0.65 * np.sin(2 * np.pi * f * t) + 0.35 * np.sign(np.sin(2 * np.pi * f * t))
               for f in freqs) / len(freqs)
    env = np.clip(np.minimum(t / 0.01, (duration - t) / 0.03), 0.0, 1.0)
    return tone * env


def _whoosh(duration: float, rng: np.random.Generator) -> np.ndarray:
    """咻:白噪音過一階低通,截止頻率由低往高掃(聲音由悶變亮),包絡先升後降。"""
    n = int(duration * _SR)
    noise = rng.standard_normal(n)
    alphas = np.linspace(0.02, 0.35, n)
    out = np.empty(n)
    acc = 0.0
    for i in range(n):
        acc += alphas[i] * (noise[i] - acc)
        out[i] = acc
    return out * np.sin(np.pi * np.linspace(0.0, 1.0, n)) ** 2


def generate_sting(out_path: str | Path) -> Path:
    """合成約 0.55 秒的轉場音效(咻 + 兩聲短喇叭)寫成 mono WAV;已存在就沿用。"""
    out_path = Path(out_path)
    if out_path.exists():
        return out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    total = np.zeros(int(_TOTAL_SEC * _SR))
    whoosh = _whoosh(0.30, rng)
    total[: len(whoosh)] += 0.6 * whoosh / (np.abs(whoosh).max() or 1.0)
    for start in (0.10, 0.30):
        horn = _horn(0.14)
        i = int(start * _SR)
        total[i : i + len(horn)] += 0.5 * horn
    pcm = (total / (np.abs(total).max() or 1.0) * 0.7 * 32767).astype("<i2")
    with wave.open(str(out_path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(_SR)
        fh.writeframes(pcm.tobytes())
    logger.info("程序化轉場音效 → {}", out_path)
    return out_path


def resolve_sting_sfx(sfx_dir: Path, work_dir: Path) -> Path | None:
    """挑轉場音效:自備檔優先,否則程序化合成;失敗就略過音效(口號照播)。"""
    for name in _USER_NAMES:
        candidate = Path(sfx_dir) / name
        if candidate.exists():
            return candidate.resolve()
    try:
        return generate_sting(Path(work_dir) / "sting_sfx.wav").resolve()
    except Exception as exc:  # noqa: BLE001
        logger.warning("轉場音效生成失敗,略過音效:{}", exc)
        return None
```

- [ ] **Step 4: 實作 `pmb/video/segments/sting.py`**

```python
"""開場口號轉場:hook 之後約 1 秒的品牌時刻(頻道字樣 + 口號 + 音效)。系統插入,不在 Script 裡。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from pmb.video.ass import (
    ASS_TEMPLATE,
    GOLD_HEX,
    POP_IN,
    ass_color,
    ass_time,
    common_events,
    text_event,
)
from pmb.video.segments.base import (
    RenderContext,
    SegmentRenderer,
    Utterance,
    Visual,
    canvas_background,
)

_WORDMARK_Y = 760
_SLOGAN_Y = 920
_WORDMARK_FS = 120
_SLOGAN_FS = 84


class StingSegment(BaseModel):
    kind: Literal["sting"] = "sting"
    text: str  # 口號(settings.slogan_intro)
    channel: str
    sfx: str | None = None  # 音效檔絕對路徑


class StingRenderer(SegmentRenderer):
    lead_in = 0.15  # 音效先響,口號晚一拍進
    min_duration = 1.2
    optional = True  # 口號配音失敗就整段略過,影片照出

    def utterances(self, seg: StingSegment) -> list[Utterance]:
        return [Utterance(seg.text, caption=False)]

    def render(self, seg: StingSegment, ctx: RenderContext) -> Visual:
        wordmark = (
            f"Dialogue: 1,0:00:00.00,{ass_time(ctx.duration)},free,,0,0,0,,"
            f"{{\\an5\\pos(540,{_WORDMARK_Y})\\fs{_WORDMARK_FS}\\1c{ass_color(GOLD_HEX)}"
            f"\\bord0\\shad0}}{POP_IN}{seg.channel}"
        )
        events = [
            wordmark,
            text_event(ctx.starts[0], ctx.duration, 540, _SLOGAN_Y, seg.text, size=_SLOGAN_FS,
                       color=ass_color("#FFFFFF"), align=5),
        ]
        events += common_events(ctx.duration, badge=ctx.badge, cta=None)
        ass = ASS_TEMPLATE.format(font=ctx.font, events="\n".join(events))
        return Visual(canvas_background(ctx.work_dir), True, ass, "sting", sfx=seg.sfx)
```

註冊:`registry.py` 加 `"sting": StingRenderer(),`(import `from pmb.video.segments.sting import StingRenderer`)。

- [ ] **Step 5: assemble_video 插入 sting 與收尾口號**

簽名(`master_audio` 之後)加:
```python
    slogan_intro: str | None = None,
    slogan_outro: str | None = None,
    sting_sfx: str | Path | None = None,
```
docstring 補一句:「``slogan_intro`` 給了就在 hook 後插口號轉場(``sting_sfx`` 為其音效);``slogan_outro`` 接在最後一段(模型已寫同義句就不重複)。」

Pass A 的 `units = list(enumerate(script.segments))` 之後加:
```python
    if slogan_intro and units:
        sting = StingSegment(text=slogan_intro, channel=channel_name,
                             sfx=str(sting_sfx) if sting_sfx else None)
        units.insert(1, (0, sting))  # hook 之後;index 0 只用於 sting0.ass 檔名
```
把 Pass A 迴圈拆成兩步——先算所有 unit 的 plan,再把收尾口號接到「最後一個有 plan 的 script 段」,再逐句配音:
```python
    plans: list[list[Utterance]] = []
    for i, seg in units:
        plan = [utt for utt in renderer_for(seg.kind).utterances(seg) if has_speakable(utt.tts_text)]
        plans.append(plan)
    last_script_u = next(
        (u for u in range(len(units) - 1, -1, -1) if plans[u] and units[u][1].kind != "sting"), None
    )
    if last_script_u is not None:
        plans[last_script_u] = append_outro(plans[last_script_u], slogan_outro)
```
接著原本的逐 unit 迴圈改用 `plan = plans[u]`(不再在迴圈內呼叫 `renderer.utterances`),並把逐句配音包成 optional 段可失敗:
```python
        try:
            takes = []
            for j, utt in enumerate(plan):
                audio_name = f"s{u}_{j}.mp3"
                result = synth_fn(
                    utt.tts_text, work_dir / audio_name, _planned_seconds(utt.tts_text), utt.voice
                )
                measured = probe_duration(work_dir / audio_name)
                takes.append(Take(utt.text, audio_name, measured, result.words, utt.gap_after,
                                  utt.caption))
        except Exception as exc:  # noqa: BLE001
            if not renderer.optional:
                raise
            logger.warning("{} 配音失敗,略過該段(影片照出):{}", seg.kind, exc)
            seg_takes.append([])
            seg_durations.append(0.0)
            continue
        usable.append(u)
```
(`usable.append(u)` 移到配音成功之後。)import 加 `from pmb.video.segments.base import Utterance, append_outro` 與 `from pmb.video.segments.sting import StingSegment`。

在 `tests/test_video.py` 再加一個測試:
```python
def test_sting_tts_failure_is_skipped_not_fatal(tmp_path):
    import datetime as dt

    from pmb.schemas.script import Script
    from pmb.schemas.snapshot import LeverageMath, Snapshot
    from pmb.tts.edge import silent_synth
    from pmb.video.assemble import assemble_video

    snap = Snapshot(
        session_date=dt.date(2026, 9, 30),
        generated_at=dt.datetime(2026, 9, 30, 12, 0, tzinfo=dt.UTC),
        leverage_math=[LeverageMath(market="S&P 500", realized_vol=0.165, vol_target_leverage=0.91,
                                    drag_1x=0.0136, drag_2x=0.0545, drag_3x=0.1226)],
    )
    script = Script.model_validate({
        "segments": [{"vo": "開場。", "headline": "標題", "tag": "k"},
                     {"vo": "圖表。", "chart_id": "lev"}],
        "charts": [{"id": "lev", "module": "leverage_decay", "params": {}}],
    })

    def synth(text, path, planned, voice):
        if text.startswith("美股早發車"):
            raise RuntimeError("edge-tts 掛了")
        return silent_synth(text, path, duration=0.5)

    work = tmp_path / "work"
    out = assemble_video(script, snap, tmp_path / "o.mp4", synth_fn=synth, work_dir=work,
                         font="PingFang TC", master_audio=False, slogan_intro="美股早發車,發車!")
    assert out.exists()
    assert not (work / "sting0.ass").exists()
    assert len((work / "clips.txt").read_text().splitlines()) == 2
```

- [ ] **Step 6: config 與 CLI**

`pmb/config.py`:
```python
    # 短影片開頭 / 結尾 slogan(v4:開場口號轉場 + 收尾口號,由合成端自動插入)
    slogan_intro: str = "美股早發車,發車!"
    slogan_outro: str = "以上非投資建議,明天盤前見。"
    sting_enable: bool = True  # 關掉就不插開場口號轉場
    sfx_dir: Path = Path("assets/sfx")  # 放 sting.wav/mp3/m4a 可蓋過程序化音效
```
`pmb/cli.py` `cmd_assemble`:在 `bgm_path = ...` 之後加
```python
    slogan_intro = settings.slogan_intro if settings.sting_enable else None
    sting_sfx = None
    if slogan_intro and not args.dry_run:
        from pmb.audio.sfx import resolve_sting_sfx

        sting_sfx = resolve_sting_sfx(settings.sfx_dir, work_dir)
```
並在 `assemble_video(...)` 呼叫加 `slogan_intro=slogan_intro, slogan_outro=settings.slogan_outro, sting_sfx=sting_sfx,`。

- [ ] **Step 7: 跑全部測試**

Run: `poetry run pytest -q && poetry run ruff check .`
Expected: 全綠

- [ ] **Step 8: Commit**

```bash
git add pmb/ tests/
git commit -m "feat(video): 開場口號轉場(程序化咻+叭叭音效)與系統自動收尾口號

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: 研究 prompt 改寫 + 文件

**Files:**
- Modify: `prompts/daily_research.md`(【產出】的 `- script:` 整條,到 `- report.md:` 之前)
- Modify: `README.md`、`.env.example`
- Test: `tests/test_runner.py`(prompt 關鍵字)

**Interfaces:**
- Consumes: 全部段型欄位名稱、`pmb validate-research`、settings 名稱。
- Produces: 無程式介面。

- [ ] **Step 1: 寫失敗測試**(`tests/test_runner.py` 檔尾)

```python
def test_research_prompt_describes_v4_kinds_persona_and_guardrails():
    from pathlib import Path

    text = Path("prompts/daily_research.md").read_text(encoding="utf-8")
    for kw in ("`dialogue`", "`split`", "`bignum`", "`recap`", "script.gags", "頻道人設",
               "梗的護欄", "不可以是真實人物", "上車", "……", "pmb validate-research",
               "不知道有沒有說過"):
        assert kw in text, kw
    assert "6–7 段:開場 hook 卡 → 3–4 個圖表段" not in text  # 寫死的骨架已拿掉
    assert "片尾對句卡的旁白以「以上非投資建議,明天盤前見」收尾" not in text  # 改由系統接
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `poetry run pytest tests/test_runner.py -q`
Expected: FAIL

- [ ] **Step 3: 改寫 `prompts/daily_research.md` 的 `- script:` 條目**

把從 `- script:**直式短影片(YouTube Shorts,成片 65–80 秒)**講稿` 開始、到 `- report.md:` 之前的全部內容,換成下面這段(圖表模組清單沿用原文不變):

````markdown
- script:**直式短影片(YouTube Shorts,成片 65–80 秒)**講稿,**用盤前時序鋪陳**:昨收回顧 →(隔夜期貨/盤前)今天的局勢 → 今日催化劑 → 今天可能怎麼走、該看什麼。**影片是鉤子,不是全文**:完整研究在 report.md,影片只挑當天最值得看的 3–4 個點講透,其餘留給報告。

  **【段型積木】** 每段有 `kind`,從下面六種挑。**排列組合依當天新聞決定,不要套固定骨架**——最近 5 天的影片附在本 prompt 最後,驗證器會擋重複。
  - `chart` 圖表段:綁一個 `chart_id`(模組只能從固定清單挑,各圖用途如下):
    - `index_overnight_grid`:四大指數隔夜期貨漲跌(今日領先訊號)
    - `overnight_vs_close`:昨收(現貨)vs 今日盤前(期貨)並列對照
    - `global_equity_overnight`:海外/亞歐股隔夜對照(KOSPI / 日經 / 台股 / 歐股…),用來指出今日盤前外溢的 **contagion 源頭**
    - `yield_curve`:美債殖利率曲線(到期結構/倒掛)
    - `vix_regime`:VIX 走勢與恐慌區間帶
    - `rates_trend`:10 年期公債殖利率走勢
    - `stock_bond_corr`:股債滾動相關(分散是否失效)
    - `breadth`:各類股當日報酬(輪動/市場廣度)
    - `concentration`:漲幅集中度(前 N 大權值股對指數的貢獻)
    - `econ_print`:單一總經序列走勢(失業率等)
    - `leverage_decay`:各市場波動耗損曲線(槓桿教育)
    - `catalyst_timeline`:本週催化劑時間軸(財報/數據/Fed);每個 event 的 `label` **控制在 20 字內**寫重點(版面每行約 19 字、最多兩行,太長會被截斷),細節放 `vo` 講
    - `fed_path`:**市場隱含 Fed 政策路徑/升息機率**(期貨優先、Treasury 曲線保底;升息環境用來視覺化政策利率往哪走)
    `index_overnight_grid` 顯示的是隔夜期貨(今日領先訊號),不是昨日現貨。`vo` 是**完整但精簡的解說**(每段 60–90 字)——講清楚這張圖的內容(引用快照真實數字)+ 它代表什麼意義,讓人**不看畫面、只聽聲音也能聽懂**,不要只把圖表標題唸一遍。`title` 是頂部主題短語(**≤10 字、單行**,如「戰爭升溫,VIX卻淡定」)。**每個圖表段務必填 `stat` + `stat_label`**:`stat` 是這段最關鍵的**一個數字**(含符號/單位,≤7 字元,例:`+1.06%`、`56%`、`95美元`),`stat_label` 是它的短說明(≤12 字)。
  - `card` 字卡:`headline`(短、像新聞標題)+ `tag`(kicker)+ `vo`。用途:開場 hook、名詞小教室、片尾金句,也可以當節奏切換的快閃卡。
  - `dialogue` 對話框:`lines` 2–4 句,每句 `{speaker, voice, text}`——`speaker` ≤6 字、`voice` 是 `a`(男聲)或 `b`(女聲)、`text` ≤16 字;可選 `title`(≤10 字)與 `vo`(泡泡講完後旁白用一句白話解釋)。泡泡跟著各自的配音逐句彈出,**鄉民對話體梗的主場**。角色**只能是機構或市場擬人**(Fed、債市、油價、VIX、散戶、華爾街、美元…),**不可以是真實人物**(川普、鮑爾、各國領袖、執行長都不行);轉述機構立場要忠實。同一角色全段用同一個 voice,至少兩個角色。
  - `split` 好壞消息:`top` / `bottom` 兩格,各有 `label`(≤6 字)、`text`(≤10 字)、選填 `stat`(≤7 字元)、`tone`(`good` 綠 / `bad` 紅 / `neutral` 藍);`vo` 至少 2 句——第 1 句講上格,第 2 句開始時下格才出現。標籤可以自由換:「好消息/壞消息」「Fed 說/市場做」「美股/亞股」「昨天/今天」。**冷面反差梗的主場**。
  - `bignum` 全屏大數字:`value`(≤8 字元,如 `5.26%`)、`label`(≤12 字)、選填 `context`(≤16 字,如「2007年以來最高」);數字會從 0 跳到定值。今天有一個數字本身就是新聞時用。
  - `recap` 對帳:`rows` 1–3 列,每列 `{ask, result, mark}`——`ask` ≤14 字(昨天說要看的事,取自附的昨日 brief `catalysts`)、`result` ≤12 字、`mark` 是 `yes`(發生/符合預期)、`no`(沒發生/不如預期)或 `mixed`(好壞參半/未定);`vo` 一句講一列。**只在昨天真的有明確「今天要看」的事時用**。
  畫面上的數字(`stat`、`value`、格子的 `stat`、`result` 裡的數字)**必須也出現在該段旁白**,且一律來自快照(或 catalysts 的排程事實)。

  **【結構底線】**(其餘自由,驗證器會檢查)
  - **第一段是 hook 字卡(前 2 秒定生死)**:`headline` 與旁白**第一句**就要是今天最強的一句(懸念/衝突/反差/梗,**≤12 字、可用 `\n` 切成兩行、每行 ≤6 字最好看**),**別用日期或「美股盤前」開場**。`tag` 是 ≤6 字的 kicker(不放日期,系統會在角落烤上「頻道 · M/D」),**別每天都寫「今日盤前」**,依當天性質寫(「非農日」「Fed 週」「對決日」「債市暴走」…)。開場卡旁白 ≤25 字、約 4 秒。系統會自動在 hook 後插一段約 1 秒的品牌口號轉場,你不用寫。
  - **最後一段是片尾金句卡**:改編自某位投資名人的名言(巴菲特、蒙格、彼得·林區、葛拉漢、柏格、科斯托蘭尼、霍華·馬克斯…),改寫成兩句順口、有點好笑的對句(像「退潮的時候/才知道誰沒穿褲子」),`tag` 標成「○○○ 不知道有沒有說過」(自嘲式、避免假托真名言),**名人別跟昨天同一位**。**旁白只唸金句本身**——「以上非投資建議,明天盤前見」由系統自動接在最後,也會自動疊「追蹤」CTA,別自己寫。
  - 至少 2 段 `chart`(數字是這支片的核心,梗不能把數字擠掉);至少 1 段新段型(`dialogue` / `split` / `bignum` / `recap`),而且**新段型組合別跟昨天一樣**。
  - 段型序列別跟前 3 天任一天一樣;hook 後的第一段(kind + 模組)別跟昨天一樣——`overnight_vs_close` 不是每天都要當第一張。
  - **名詞小教室改成「有合適術語才放」**:當天講稿真的用到一個新手可能卡住的術語時,在它首次出現後插一張字卡(`headline` 寫名詞、`tag` 寫「名詞小教室」),旁白用**一句白話(≤20 字)**講懂它。近 20 天教過的別再教(清單附在最後)。

  **【格式靈感】**(不強制,挑適合今天的或自己組):
  - **對決日**:整支圍繞兩方對立(Fed vs 債市、美股 vs 亞股),`dialogue` / `split` 當主力。
  - **一個數字**:整支圍繞一個驚人數字,`bignum` 開場後用圖表講為什麼、再講影響。
  - **今晚大考**:催化劑日,`catalyst_timeline` 早點出場,講清楚今晚看什麼、各種結果代表什麼。
  - **對帳日**:昨天說要看的事有了結果,`recap` 放前面。
  - **平常日**:昨收 → 盤前 → 催化劑的標準時序,但用一種新段型換掉其中一張圖。

  **【頻道人設與梗】**
  - 人設:一個嘴有點壞、但很懂市場的老朋友——用鄉民語感講總經,擅長一本正經講幹話。觀眾笑完要學到東西。
  - **鄉民梗**:對話體(「Fed:十月不急。債市:你不急,我急。」)、長青流行語(已讀不回、先別急、這很合理?、我就爛…)、推文體。**優先用長青梗**——太新的流行語你未必熟,用錯比不用還尷尬。
  - **冷面反差**:好消息/壞消息(「好消息:Fed 說不急。壞消息:債市沒在聽。」)、一本正經的冷知識對照(「十年期 5.26%,上次這麼高,iPhone 才剛出第一代」——對照的事實要查證)、先鋪陳再用一句短句打臉。**punchline 前一句用「……」結尾**,合成時會在那裡停一拍(0.5 秒),反差才好笑。
  - **配額**:全片至少 2 個梗,其中 1 個在前 15 秒(hook 本身可以就是梗);金句不算。寫完把用了哪些梗寫進 `script.gags`(每個一句話描述,如「Fed 說不急 vs 債市我急的對話體」)。最近幾天的梗附在最後,**別重複最近用過的梗**,但可以 callback(「上週說的已讀不回,今天又來」)。
  - `title_hook` 也可以帶人設口吻,但仍要具體名詞/數字、不 clickbait。

  **【梗的護欄】(違反任何一條都比沒梗更糟)**
  1. 不拿傷亡、災難、戰爭受害者開玩笑;戰爭/攻擊類新聞只吐槽市場的反應與數字,不吐槽事件本身。
  2. 不人身攻擊、不選邊站政治;吐槽對象是市場、指標、機構的「行為」,不是人。
  3. 不用暗示進出場的梗:梭哈、歐印、抄底、all in、上車(頻道叫「早發車」,特別容易順口說出「上車」——別)。「住套房」「韭菜」只能自嘲,不嘲笑觀眾。
  4. 梗要扣著當天的數字或機制;拿掉梗之後資訊量不能變少。
  5. 反 AI 腔鐵則照舊:不用「不是…而是」「值得注意的是」這類套話。

  - **至少一個具體比喻**:把當天最抽象的數字/機制翻成有畫面的比喻(例:「指數平盤是兩檔權值股縫出來的」「VIX 睡著時數學叫你加最多槓桿,這是陷阱」),讓人聽一次就記得;比喻要準確、不誇大。
  - **長度硬預算(最容易犯的錯,務必自檢):全片「實際念出來的字」(各段 `vo` + 對話框每句 `text`)加總 ≤ 520 字,最佳 380–450 字。** 成片長度 ≈ 總字數 × 0.18 秒(391 字 → 72 秒)。**為什麼這麼短**:2.5 分鐘的 Shorts 觀眾滑走、演算法就不推(2026 年 8 月觀看數因此掉四倍);65–80 秒是能講完一條主軸、又留得住人的長度。超了就**整段砍掉次要段落**再交件——不是刪句尾了事;砍掉的內容寫進 report.md。
  - **寫完 script 務必執行 `poetry run pmb validate-research --date <今天日期>`**:它會檢查 schema、字數預算、反重複、各欄位字數上限、畫面數字與旁白是否一致、`gags` 數量;有任何一條錯誤就修正檔案再跑,直到印出「全部通過」。
  全片要有 **insight**:把當天的點連成線、給出「所以呢」的判斷(例如某個訊號疊加另一個訊號代表什麼、表象底下的真正風險或轉折),最好有一條貫穿全片的主軸,而不是逐張圖報數字。**配比:盤前以短期為主(今天怎麼開、怎麼走),但收尾務必拉遠一點、涵蓋至少一條中長期/結構性的判斷(連到 thesis)**——除非當天真的沒有任何中長期角度,否則別讓整支都是今天的短線雜訊。語氣口語、有個性,保持教育而非建議、數字精準。合成時系統會把 `vo` 自動斷句、字幕一句一句跟著語音播,所以 `vo` 請寫成順口的短句串接(用句號分句)。依 lead_horizon 安排順序(regime 日把中長期項目當開場 hook)。
  - **選題方法**:(1) 先用新聞與快照數字確定當前盤勢與時事;(2) 站在一般投資人的角度,想這個局勢下大眾「最關心、最想知道」的投資議題是什麼,據此挑面向與段型。**不必每天都換主題**,但要切中當下最多人關心的點(例如升息環境就聚焦利率與估值、波動高就聚焦風險與槓桿)。
  - **圖表庫缺口**:若有想講的重點而固定模組清單沒有合適的圖,**不要硬湊不相干的圖**;把「需要什麼圖、為什麼」寫進 `script.coverage_gaps`(描述即可),並暫時用最接近的現有圖頂著。人工 gate 會把缺口當 alert,補上模組後隔天就能用。
````

改完後通讀一次整份 prompt,確認其餘段落(鐵則、流程、brief、report、thesis)一字未動。

- [ ] **Step 4: README 與 .env.example**

`.env.example` 在 `TTS_PITCH` 那行之後加:
```bash
# TTS_VOICE_A=zh-TW-YunJheNeural     # 對話框 A 角(男聲)
# TTS_VOICE_B=zh-TW-HsiaoYuNeural    # 對話框 B 角(女聲)
# SLOGAN_INTRO=美股早發車,發車!      # hook 後的開場口號轉場
# SLOGAN_OUTRO=以上非投資建議,明天盤前見。
# STING_ENABLE=true                  # false 就不插開場口號轉場
# SFX_DIR=assets/sfx                 # 放 sting.wav/mp3/m4a 可蓋過程序化音效
```
`README.md`:在描述影片結構/講稿的章節(搜尋「字卡」或「stat」附近)加一小節「段型(v4)」,列六種 kind 各一句用途、`script.gags`、開場口號轉場與收尾口號由系統自動插入、`pmb validate-research` 用法,並連到規格檔路徑。控制在 20 行內。

- [ ] **Step 5: 跑全部測試**

Run: `poetry run pytest -q && poetry run ruff check .`
Expected: 全綠

- [ ] **Step 6: Commit**

```bash
git add prompts/daily_research.md README.md .env.example tests/test_runner.py
git commit -m "docs(prompt): v4 研究 prompt——段型積木、反重複底線、鄉民梗+冷面反差人設與護欄

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: 全段型煙霧測試 + 抽幀檢查

**Files:**
- Create: `tests/fixtures/script_all_kinds.json`
- Test: `tests/test_video.py`

**Interfaces:**
- Consumes: 全部前面任務。

- [ ] **Step 1: 建 fixture** `tests/fixtures/script_all_kinds.json`

```json
{
  "segments": [
    {"kind": "card", "vo": "殖利率又創新高,Fed卻說不急。", "headline": "Fed說不急\n債市說我急", "tag": "對決日"},
    {"kind": "dialogue", "title": "Fed vs 債市", "lines": [
      {"speaker": "Fed", "voice": "a", "text": "十月升息,不急。"},
      {"speaker": "債市", "voice": "b", "text": "你不急,我急。"},
      {"speaker": "Fed", "voice": "a", "text": "……蛤?"}
    ], "vo": "意思是長天期利率自己往上衝。"},
    {"kind": "chart", "vo": "10年期公債殖利率今天來到5.26%,續創2007年以來新高。", "chart_id": "rates", "title": "殖利率照樣衝", "stat": "5.26%", "stat_label": "10年期殖利率"},
    {"kind": "split", "vo": "好消息是Fed說十月不急……壞消息是債市完全沒在聽,5.26%。", "top": {"label": "好消息", "text": "Fed說不急", "tone": "good"}, "bottom": {"label": "壞消息", "text": "債市沒在聽", "stat": "5.26%", "tone": "bad"}},
    {"kind": "bignum", "vo": "十年期5.26%,上次這麼高,iPhone才剛出第一代。", "value": "5.26%", "label": "10年期殖利率", "context": "2007年以來最高"},
    {"kind": "recap", "vo": "昨天說看威廉斯,他說十月不急。十年期沒守住5.2%,來到5.26%。消費者信心12年新低。", "rows": [
      {"ask": "威廉斯怎麼說", "result": "十月不急", "mark": "yes"},
      {"ask": "10年期守不守5.2%", "result": "沒守住5.26%", "mark": "no"},
      {"ask": "消費者信心", "result": "12年新低", "mark": "mixed"}
    ]},
    {"kind": "chart", "vo": "標普上一交易日跌0.17%,期貨續小跌。", "chart_id": "lev", "title": "槓桿更貴了", "stat": "-0.17%", "stat_label": "標普昨收"},
    {"kind": "card", "vo": "官員嘴巴放鴿,長天期公債利率卻硬得很。", "headline": "官員嘴巴放鴿\n公債硬得很", "tag": "蒙格 不知道有沒有說過"}
  ],
  "charts": [
    {"id": "rates", "module": "leverage_decay", "params": {}},
    {"id": "lev", "module": "leverage_decay", "params": {}}
  ],
  "gags": ["Fed 不急 vs 債市我急的對話體", "上次這麼高 iPhone 才剛出第一代"]
}
```
(兩張圖都用 `leverage_decay`,因為測試快照只有 `leverage_math`;真實模組在 Task 12 Step 4 的真片彩排驗。)

- [ ] **Step 2: 寫測試**(`tests/test_video.py` 檔尾)

```python
def test_assemble_all_kinds_smoke(tmp_path):
    """整合(靜音 TTS + ffmpeg):六種段型 + 口號轉場 + 收尾口號一起合成不炸,產物齊全。"""
    import datetime as dt
    from pathlib import Path

    from pmb.research.variety import soft_script_errors
    from pmb.schemas.script import Script
    from pmb.schemas.snapshot import LeverageMath, Snapshot
    from pmb.tts.edge import silent_synth
    from pmb.video.assemble import assemble_video

    fixture = Path(__file__).parent / "fixtures" / "script_all_kinds.json"
    script = Script.model_validate_json(fixture.read_text(encoding="utf-8"))
    assert soft_script_errors(script, []) == []  # fixture 本身就是合規範例
    snap = Snapshot(
        session_date=dt.date(2026, 9, 30),
        generated_at=dt.datetime(2026, 9, 30, 12, 0, tzinfo=dt.UTC),
        leverage_math=[LeverageMath(market="S&P 500", realized_vol=0.165, vol_target_leverage=0.91,
                                    drag_1x=0.0136, drag_2x=0.0545, drag_3x=0.1226)],
    )
    voices: list[str] = []

    def synth(text, path, planned, voice):
        voices.append(voice)
        return silent_synth(text, path, duration=0.6)

    work = tmp_path / "work"
    out = assemble_video(script, snap, tmp_path / "all.mp4", synth_fn=synth, work_dir=work,
                         font="PingFang TC", master_audio=False,
                         slogan_intro="美股早發車,發車!", slogan_outro="以上非投資建議,明天盤前見。")
    assert out.exists() and out.stat().st_size > 0
    for name in ("card0.ass", "sting0.ass", "dialogue1.ass", "seg2.ass", "split3.ass",
                 "bignum4.ass", "recap5.ass", "seg6.ass", "card7.ass"):
        assert (work / name).exists(), name
    assert {"a", "b", "narrator"} <= set(voices)
```

- [ ] **Step 3: 跑測試**

Run: `poetry run pytest -q && poetry run ruff check .`
Expected: 全綠

- [ ] **Step 4: 抽幀人工檢查(controller 執行,不入庫)**

Run:
```bash
poetry run python - <<'EOF'
import datetime as dt
from pathlib import Path
from pmb.schemas.script import Script
from pmb.schemas.snapshot import Snapshot
from pmb.tts.edge import silent_synth
from pmb.video.assemble import assemble_video
main = Path("/Users/sweslo17/Documents/code/us-invesment-analysis-video/artifacts")
script = Script.model_validate_json(Path("tests/fixtures/script_all_kinds.json").read_text())
script.charts[0].module = "rates_trend"
script.charts[1].module = "overnight_vs_close"
snap = Snapshot.model_validate_json((main / "snapshot_2026-09-30.json").read_text())
assemble_video(script, snap, Path("/tmp/pmb_all.mp4"),
    synth_fn=lambda t, p, planned, v: silent_synth(t, p, duration=planned),
    work_dir=Path("/tmp/pmb_all_work"), font="PingFang TC", master_audio=False,
    slogan_intro="美股早發車,發車!", slogan_outro="以上非投資建議,明天盤前見。")
EOF
```
再用 ffmpeg 每種段型抽 1–2 張(泡泡全部彈出後、好壞消息下格出現後、大數字跳完後、對帳三列都出現後、口號轉場中),拼成對照圖,人工確認:文字不進底部 400px / 右側 170px、泡泡不重疊、色塊與文字對齊、數字格式正確。發現版面問題就回頭調對應 renderer 的常數並補測試,另開 commit。

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/script_all_kinds.json tests/test_video.py
git commit -m "test(video): 六種段型 + 口號轉場的整合煙霧測試

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## 收尾(controller,非 subagent 任務)

1. 全分支 review(最強模型,對照規格逐節)。
2. 真片彩排:worktree 內複製主 checkout 的 `.env`(不入庫)→ 挑一個已有 snapshot 的交易日,`poetry run pmb research-local --date <d> --no-push`(真實研究、用新 prompt)→ `poetry run pmb assemble --date <d>`(真實 TTS)→ 抽幀 + 聽音檢查;避開 19:00–21:30。
3. 把成片與 review 結論交給使用者,**等使用者點頭才合併 main**(合併避開 19:00–21:30)。
