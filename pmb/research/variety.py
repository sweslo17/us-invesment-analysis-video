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


def load_recent_scripts(artifacts_dir: str | Path, before: dt.date,
                        n: int) -> list[DayRecord]:
    """讀 ``before`` 之前(不含)最近 ``n`` 份可解析的 script,新到舊;壞檔跳過並記
    WARNING。"""
    root = Path(artifacts_dir)
    if not root.is_dir():
        return []
    dated: list[tuple[dt.date, Path]] = []
    for path in root.glob("script_*.json"):
        match = _SCRIPT_RE.match(path.name)
        if match is None:
            continue
        try:
            day = dt.date.fromisoformat(match.group(1))
        except ValueError:
            logger.warning("略過檔名日期不合法的歷史 script {}", path.name)
            continue
        if day < before:
            dated.append((day, path))
    out: list[DayRecord] = []
    for day, path in sorted(dated, reverse=True):
        if len(out) >= n:
            break
        try:
            out.append(
                DayRecord(day,
                          Script.model_validate_json(path.read_text(encoding="utf-8"))))
        except (ValidationError, ValueError, OSError) as exc:
            logger.warning("略過無法解析的歷史 script {}:{}", path.name,
                           str(exc)[:200])
    return out


def _module_of(seg, script: Script) -> str | None:
    if isinstance(seg, ChartSegment):
        return next((c.module for c in script.charts if c.id == seg.chart_id),
                    None)
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
    """hook 之後第一段的 (kind, 模組);系統插入的口號轉場不在 script 裡,所以就是
    index 1。"""
    if len(script.segments) < 2:
        return None
    seg = script.segments[1]
    return seg.kind, _module_of(seg, script)


def hook_card(script: Script) -> CardSegment | None:
    first = script.segments[0] if script.segments else None
    return first if isinstance(first, CardSegment) else None


def quote_card(script: Script) -> CardSegment | None:
    last = script.segments[-1] if script.segments else None
    if isinstance(last, CardSegment) and (last.tag or "").strip().endswith(
        QUOTE_SUFFIX):
        return last
    return None


def quote_author(script: Script) -> str | None:
    """金句卡 tag「彼得·林區 不知道有沒有說過」→「彼得林區」(去空白與間隔號,同一人才比得
    出來)。"""
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
        errors.append(
            f"結構:最後一段必須是金句字卡(kind=card,tag 以「{QUOTE_SUFFIX}」結尾)"
        )
    n_charts = sum(isinstance(seg, ChartSegment) for seg in script.segments)
    if n_charts < MIN_CHARTS:
        errors.append(
            f"結構:圖表段至少 {MIN_CHARTS} 段(目前 {n_charts})——數字是這支片的核心,"
            "梗不能擠掉它"
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
                f"反重複:hook 後第一段又是 {label},跟 {yesterday.date} 一樣;"
                "換一個開場角度"
            )
        if used and used == new_kinds_used(yesterday.script):
            errors.append(
                f"反重複:新段型組合跟 {yesterday.date} 一樣({'、'.join(sorted(used))});"
                "換一種"
            )
        author = quote_author(script)
        if author and author == quote_author(yesterday.script):
            errors.append(f"反重複:金句名人跟 {yesterday.date} 同一位({author});換一位")
        hook, prev_hook = hook_card(script), hook_card(yesterday.script)
        kicker = (hook.tag or "").strip() if hook else ""
        if kicker and prev_hook is not None and kicker == (
            prev_hook.tag or "").strip():
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


def _over(errors: list[str], idx: int, field: str, text: str | None,
          limit: int) -> None:
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
            missing = [
                core for core in numeric_cores(shown) if core not in spoken
            ]
            if missing:
                errors.append(
                    f"數字:第 {i} 段畫面上的「{shown}」沒出現在旁白裡"
                    f"(缺 {'、'.join(missing)});畫面與聲音的數字要一致"
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
    lines = [f"\n=== 最近 {len(shown)} 個交易日的影片"
             "(別重複骨架、開場與梗;驗證器會擋)==="]
    for day in shown:
        s = day.script
        hook, quote = hook_card(s), quote_card(s)
        hook_txt = (
            f"「{hook.headline.replace(chr(10), ' ')}」(kicker:{hook.tag or '無'})"
            if hook else "(無)"
        )
        quote_txt = (
            f"{quote_author(s)}「{quote.headline.replace(chr(10), ' / ')}」"
            if quote else "(無)"
        )
        lines.append(f"- {day.date}|段型:{describe_sequence(s)}")
        lines.append(
            f"  hook:{hook_txt}|金句:{quote_txt}|名詞小教室:{lesson_term(s) or '無'}"
        )
        lines.append(f"  梗:{';'.join(s.gags) if s.gags else '(未記錄)'}")
    terms: list[str] = []
    for day in recent[:LESSON_LOOKBACK]:
        term = lesson_term(day.script)
        if term and term not in terms:
            terms.append(term)
    if terms:
        lines.append(
            f"近 {LESSON_LOOKBACK} 個交易日教過的名詞小教室(別重複):"
            f"{'、'.join(terms)}"
        )
    return "\n".join(lines)
