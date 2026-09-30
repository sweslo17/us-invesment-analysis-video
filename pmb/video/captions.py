"""旁白斷句與字幕:逐句切分、依字寬斷行、逐頁卡拉OK對時、SRT。

從 video.assemble 拆出(v4),供 assemble 與各段型 renderer 共用。
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import NamedTuple

from pmb.tts.edge import WordBoundary

MAX_UNITS = 13  # 字幕每行寬度上限(中文 1、英數 0.55);13×64px 塞得進左右邊界內
MAX_LINES = 2  # 字幕每頁最多行數(保證不蓋圖)


# 句尾標點不含 ASCII 句點「.」,否則 3.8% 這類小數會被誤切。「……」(或「⋯⋯」)也算句末:
# 冷面反差的 punchline 前停一拍(見 is_beat)。
_SENT_RE = re.compile(r"[^。!?！?;;；\n…⋯]+(?:[…⋯]+[。!?！?;;；」』)）]*|[。!?！?;;；])?")
_BEAT_RE = re.compile(r"[…⋯]+[。!?！?;;；」』)）]*$")


def has_speakable(text: str) -> bool:
    """這段文字是否有「唸得出來」的內容(中日韓字、字母或數字)。

    純標點/符號的碎片(如收尾的 ``』``)送進 edge-tts 會回 NoAudioReceived,
    2026-07-30 就因此讓整支影片合成失敗,故一律先過濾。
    """
    return any(ch.isalnum() for ch in text)


def is_beat(sentence: str) -> bool:
    """這句以「……」收尾 → 念完要停一拍(punchline 前的空檔)。"""
    return bool(_BEAT_RE.search(sentence.strip()))


def strip_beat(text: str) -> str:
    """送 TTS 前拿掉刪節號(停頓由合成端的句間空白負責;字幕保留)。"""
    return text.replace("…", "").replace("⋯", "")


def _fragments(text: str) -> Iterator[str]:
    """依原文順序吐出 ``_SENT_RE`` 的比對結果與比對之間沒被吃掉的空隙(不丟任何字元)。

    空隙只會是句首字元類別排除掉的符號(連續的句尾標點、「……」、換行),不含可發音內容。
    """
    cursor = 0
    for m in _SENT_RE.finditer(text):
        yield text[cursor : m.start()]
        yield m.group()
        cursor = m.end()
    yield text[cursor:]


def split_sentences(text: str) -> list[str]:
    """把旁白切成句子(保留句尾標點),供逐句配音與逐頁字幕。沒有標點則整段為一句。

    刻意不把 ASCII 句點當句尾,避免 3.8%、0.53 這類小數被切斷。沒有可發音內容的
    碎片(句尾標點後的右引號、破折號、緊接在句末後的「……」…)併回前一句,避免送空文字給
    TTS;開頭沒有前句可併的符號碎片(如開場的「……」)黏在第一句前面。保留原文,不丟字。
    """
    sentences: list[str] = []
    lead = ""  # 開頭尚無前句可併的符號碎片
    for frag in (f.strip() for f in _fragments(text)):
        if not frag:
            continue
        if not has_speakable(frag):
            if sentences:
                sentences[-1] += frag
            else:
                lead += frag
            continue
        sentences.append(lead + frag)
        lead = ""
    return sentences


def _timestamp(seconds: float) -> str:
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    millis = int(round((secs - int(secs)) * 1000))
    return f"{int(hours):02d}:{int(minutes):02d}:{int(secs):02d},{millis:03d}"


def build_srt(cues: list[tuple[str, float, float]]) -> str:
    """把 (文字, 起點秒, 長度秒) 列表組成 SRT 字幕。"""
    blocks = []
    for i, (text, start, duration) in enumerate(cues, start=1):
        blocks.append(f"{i}\n{_timestamp(start)} --> {_timestamp(start + duration)}\n{text}\n")
    return "\n".join(blocks)


BREAK_AFTER = "，、,。!?!?;；:：…)）」』】"


def char_units(ch: str) -> float:
    return 1.0 if not ch.isascii() else 0.55


def text_units(text: str) -> float:
    """整段字寬(中文 1、英數 0.55),版面估寬用。"""
    return sum(char_units(ch) for ch in text)


def _is_ascii_alnum(ch: str) -> bool:
    return ch.isascii() and ch.isalnum()


def wrap_lines(text: str, max_units: int = MAX_UNITS) -> list[str]:
    """依寬度切行(中文算 1、英數算 0.55),優先在標點後斷行。行串接 == 原文。

    數字/英文的連續串(7747、1.06%、VIX)不從中間切:寬度到了但下一個字仍是同一串,
    就多塞幾個字把串講完再斷(略超寬,總比「收7 / 747點」好讀)。
    """
    lines: list[str] = []
    cur: list[str] = []
    width = 0.0
    for i, ch in enumerate(text):
        cur.append(ch)
        width += char_units(ch)
        nxt = text[i + 1] if i + 1 < len(text) else ""
        in_run = _is_ascii_alnum(ch) and (_is_ascii_alnum(nxt) or nxt in ".%")
        if (ch in BREAK_AFTER and width >= max_units * 0.55) or (
            width >= max_units and not in_run
        ):
            lines.append("".join(cur))
            cur = []
            width = 0.0
    if cur:
        lines.append("".join(cur))
    return lines


def wrap_caption(text: str, max_units: int = MAX_UNITS) -> str:
    """把一行字幕依寬度切成多行,回傳以 ASS 換行符 ``\\N`` 連接的多行。"""
    return "\\N".join(wrap_lines(text, max_units))


class CaptionPage(NamedTuple):
    """一頁字幕:``text`` 已含 ``\\N`` 斷行;時間相對句首;karaoke 為 (顯示塊, centisec)。"""

    text: str
    start: float
    end: float
    karaoke: list[tuple[str, int]]


def _char_spans_from_words(
    sentence: str, words: list[WordBoundary]
) -> list[tuple[float, float]] | None:
    """用 word boundary 對齊出每個字的 (起,迄) 秒。對不上(TTS 正規化)回 None。"""
    n = len(sentence)
    spans: list[tuple[float, float] | None] = [None] * n
    cursor = 0
    for w in words:
        token = w.text.strip()
        if not token:
            continue
        idx = sentence.find(token, cursor)
        if idx < 0:
            return None
        for i in range(idx, min(idx + len(token), n)):
            spans[i] = (w.start, w.start + w.duration)
        cursor = idx + len(token)
    # 沒被 boundary 覆蓋的字(標點/空白):併入前一個字的時間;開頭的併入後一個
    last: tuple[float, float] | None = None
    for i in range(n):
        if spans[i] is not None:
            last = spans[i]
        elif last is not None:
            spans[i] = (last[1], last[1])
    first = next((s for s in spans if s is not None), None)
    if first is None:
        return None
    for i in range(n):
        if spans[i] is None:
            spans[i] = (first[0], first[0])
        else:
            break
    return [s if s is not None else (first[0], first[0]) for s in spans]


def _char_spans_proportional(sentence: str, duration: float) -> list[tuple[float, float]]:
    """按字寬比例把句長攤給每個字(拿不到 word boundary 時的後備)。"""
    weights = [char_units(ch) for ch in sentence]
    total_w = sum(weights) or 1.0
    spans: list[tuple[float, float]] = []
    acc = 0.0
    for w in weights:
        start = duration * acc / total_w
        acc += w
        spans.append((start, duration * acc / total_w))
    return spans


def build_caption_pages(
    sentence: str,
    words: list[WordBoundary],
    duration: float,
    *,
    max_units: int = MAX_UNITS,
    max_lines: int = MAX_LINES,
) -> list[CaptionPage]:
    """把一句切成逐頁字幕(每頁 ≤ ``max_lines`` 行),附逐字卡拉OK時間。

    頁的起訖時間來自 word boundary(拿不到就按字寬比例),頁與頁相接不留黑洞;
    最後一頁停留到句尾。
    """
    if not sentence:
        return []
    spans = (_char_spans_from_words(sentence, words) if words else None) or (
        _char_spans_proportional(sentence, duration)
    )
    lines = wrap_lines(sentence, max_units)
    page_line_groups = [lines[i : i + max_lines] for i in range(0, len(lines), max_lines)]

    pages: list[CaptionPage] = []
    char_pos = 0
    boundaries: list[tuple[int, int, set[int]]] = []  # (起字, 迄字, 行斷點集合)
    for group in page_line_groups:
        start_pos = char_pos
        breaks: set[int] = set()
        for j, line in enumerate(group):
            char_pos += len(line)
            if j < len(group) - 1:
                breaks.add(char_pos - 1)  # 此字之後插入 \N
        boundaries.append((start_pos, char_pos, breaks))

    for k, (lo, hi, breaks) in enumerate(boundaries):
        page_start = spans[lo][0]
        page_end = duration if k == len(boundaries) - 1 else spans[boundaries[k + 1][0]][0]
        # 卡拉OK塊:同時間片的連續字合成一塊,塊長順延到下一塊起點(吞掉字間空隙)
        chunks: list[tuple[str, float, float]] = []  # (text, start, end)
        for i in range(lo, hi):
            ch, (s, e) = sentence[i], spans[i]
            if chunks and chunks[-1][1] == s and chunks[-1][2] == e:
                chunks[-1] = (chunks[-1][0] + ch, s, e)
            else:
                chunks.append((ch, s, e))
            if i in breaks:
                text, s0, e0 = chunks[-1]
                chunks[-1] = (text + "\\N", s0, e0)
        karaoke: list[tuple[str, int]] = []
        for j, (text, s, e) in enumerate(chunks):
            until = chunks[j + 1][1] if j < len(chunks) - 1 else page_end
            cs = max(1, round((max(until, e) - s) * 100))
            karaoke.append((text, cs))
        page_text = "".join(t for t, _, _ in chunks)
        pages.append(CaptionPage(page_text, page_start, page_end, karaoke))
    return pages
