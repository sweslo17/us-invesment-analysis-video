"""中文標點正規化：公開文字裡，中文語境的半形 ``,:;!?()`` 一律改成全形。

句號早就是全形 ``。``，其餘標點卻是半形，畫面與文章看起來不一致。模型模仿 prompt 的
寫法，所以在研究產物的源頭與所有對外出口各套一次同一支 ``zh_punct``，規則只有這一份。

規則：

- ``,`` ``:`` ``;`` ``!`` ``?``：緊鄰（略過空白）的前一個或後一個字元屬於中文語境才轉；
  緊鄰的是英數 token（``66%``、``FOMC``、``**``…）就穿透這一個 token（連同空白）再看下一個
  字元，是中文也算，所以 ``66%,10年期`` 與 ``對 Fed, ECB 與 BoJ`` 都會轉，``S&P 500, Nasdaq``
  不會。
- 夾在數字之間的 ``,`` ``:`` 只有這三種維持半形：千分位（``7,670``）、時間（``8:30``、
  ``20:30:00``）、比例（``1:1``；右邊的數字緊接漢字就是標籤冒號，如 ``3:8月``）。
  其餘（``8:30:8月PCE``、``16.10,10年期``）照上面的一般規則判斷。
- ``(`` ``)``：先配對，成對的括號碰到中文（外側左右、內側首尾）才整對轉，否則整對不動；
  沒配到對的不動。巢狀括號反覆套用到不再變化為止。
- 被轉成全形的標點，緊鄰的半形空格一併清掉；其他空白不動。Markdown 的區塊標記（``- ``、
  ``1. ``、``## ``、``> ``）後面的空格與行首縮排不清，行尾的空格（含硬換行的兩個空格）也不清。
- 網址、Markdown 連結目標、行內碼、程式碼區塊不碰。
- 其他字元（``.`` ``%`` 引號、換行、``\\N``、本來就是全形的標點）一律不動。

連鎖轉換：``對 Fed, ECB, BoJ 與日銀`` 最後一個逗號貼著中文先轉，前面的逗號隨後貼著全形
逗號，一個接一個跟著轉（中文排版本來就如此）。每輪只往外多推一格，所以最多套用
``_MAX_PASSES`` 輪：真實文字 2–3 輪就收斂，輪數上限只是替病態輸入（上千個逗號串成一條）
擋住計算量暴增；超過上限的連鎖不會轉完，此時再套一次才會繼續（不再冪等）。

``zh_punct`` 不會丟例外：任何內部錯誤都記 WARNING 並原樣回傳輸入，所以對外出口不會因為
標點正規化讓一天的流程中斷。
"""

from __future__ import annotations

import re
from typing import Any

from loguru import logger
from pydantic import BaseModel

_MARKS = {",": "，", ":": "：", ";": "；", "!": "！", "?": "？"}
_CANDIDATES = re.compile(r"[,:;!?()]")
_SPACES = " \t"
_TOKEN_PUNCT = ".%$+-/&'*_"
_THOUSANDS = re.compile(r"[0-9]{3}(?![0-9])")  # 逗號後剛好三位數
_CLOCK = re.compile(r"[0-9]{2}(?![0-9])")  # 冒號後剛好兩位數
_DIGITS = re.compile(r"[0-9]+")
_MAX_PASSES = 6  # 連鎖轉換最多套用幾輪，見模組說明
# 行首的 Markdown 區塊標記（可疊：``> - ``）：清單、編號、引用、標題
_BLOCK_MARKER = re.compile(
    r"[ \t]*(?:(?:[-*+>]|[0-9]+[.)])[ \t]*)*(?:[-*+>]|[0-9]+[.)])|[ \t]*#{1,6}"
)

# 受保護範圍：依序為程式碼區塊、行內碼、Markdown 連結目標、網址。
# 網址到空白、中日文字元或角括號為止；結尾的標點屬於句子，不算網址的一部分。
_URL_CHAR = r"[^\s<>()\u3000-\u303f\u3400-\u9fff\uff00-\uffef]"
_PROTECTED = re.compile(
    r"```.*?```"
    r"|`[^`\n]+`"
    r"|\]\((?:[^()\n]|\([^()\n]*\))*\)"
    rf"|https?://(?:{_URL_CHAR}|\({_URL_CHAR}*\))*(?<![.,;:!?'\"])",
    re.DOTALL,
)


def _is_cjk(ch: str) -> bool:
    """中文語境字元：漢字，以及 CJK／全形標點（``「」『』。、，…`` 等）。"""
    if not ch:
        return False
    cp = ord(ch)
    return (
        0x3400 <= cp <= 0x9FFF
        or 0x3001 <= cp <= 0x303F
        or 0xFF00 <= cp <= 0xFFEF
        or ch in "…⋯"
    )


def _skip_spaces(text: str, j: int, step: int) -> int:
    while 0 <= j < len(text) and text[j] in _SPACES:
        j += step
    return j


def _nearest(text: str, i: int, step: int) -> str:
    """從 ``i`` 往 ``step`` 方向找第一個非空白字元（不跨行）；沒有就回空字串。"""
    j = _skip_spaces(text, i + step, step)
    return text[j] if 0 <= j < len(text) else ""


def _between_digits(text: str, i: int) -> bool:
    before, after = text[i - 1 : i], text[i + 1 : i + 2]
    return before.isascii() and before.isdigit() and after.isascii() and after.isdigit()


def _keeps_half_width(text: str, i: int) -> bool:
    """``i`` 處夾在數字之間的 ``,`` ``:`` 是否屬於維持半形的三種：千分位、時間、比例。"""
    if not _between_digits(text, i):
        return False
    if text[i] == ",":
        return _THOUSANDS.match(text, i + 1) is not None
    if _CLOCK.match(text, i + 1):
        return True
    ratio = _DIGITS.match(text, i + 1)
    after = text[ratio.end() : ratio.end() + 1] if ratio else ""
    return not ("\u3400" <= after <= "\u9fff")  # 右邊的數字緊接漢字：標籤冒號，不是比例


def _is_token_char(text: str, j: int) -> bool:
    """英數 token 的字元：ASCII 英數、``%.$+-/&'``、Markdown 強調的 ``*`` ``_``，
    以及維持半形的千分位、時間、比例標點（``7,670``、``9:05`` 是同一個 token）。"""
    ch = text[j]
    if ch.isascii() and ch.isalnum() or ch in _TOKEN_PUNCT:
        return True
    return ch in ",:" and _keeps_half_width(text, j)


def _side_is_chinese(text: str, i: int, step: int) -> bool:
    """``i`` 處標點的某一側是否屬中文語境：最近的非空白字元是中文，或它是英數 token 的一部分，
    且穿透這整個 token（再略過空白）之後的下一個字元是中文。每側只穿透一個 token。"""
    j = _skip_spaces(text, i + step, step)
    if not 0 <= j < len(text):
        return False
    if _is_cjk(text[j]):
        return True
    if not _is_token_char(text, j):
        return False
    while 0 <= j < len(text) and _is_token_char(text, j):
        j += step
    j = _skip_spaces(text, j, step)
    return 0 <= j < len(text) and _is_cjk(text[j])


def _mark_in_chinese_context(text: str, i: int) -> bool:
    if text[i] in ",:" and _keeps_half_width(text, i):
        return False
    return _side_is_chinese(text, i, -1) or _side_is_chinese(text, i, 1)


def _pair_touches_cjk(text: str, opening: int, closing: int) -> bool:
    return any(
        _is_cjk(ch)
        for ch in (
            _nearest(text, opening, -1),
            _nearest(text, closing, 1),
            _nearest(text, opening, 1),
            _nearest(text, closing, -1),
        )
    )


def _convert_once(text: str) -> str:
    """套用一輪規則；括號的外圍在內層轉完之後才看得出來，所以外層要反覆套用。"""
    if not _CANDIDATES.search(text):
        return text
    protected = bytearray(len(text))
    for m in _PROTECTED.finditer(text):
        protected[m.start() : m.end()] = b"\x01" * (m.end() - m.start())

    converted: dict[int, str] = {}
    open_stack: list[int] = []
    for i, ch in enumerate(text):
        if protected[i]:
            continue
        if ch == "\n":
            open_stack.clear()  # 括號不跨行配對
        elif ch in _MARKS:
            if _mark_in_chinese_context(text, i):
                converted[i] = _MARKS[ch]
        elif ch == "(":
            open_stack.append(i)
        elif ch == ")" and open_stack:
            opening = open_stack.pop()
            if _pair_touches_cjk(text, opening, i):
                converted[opening], converted[i] = "（", "）"

    if not converted:
        return text
    dropped: set[int] = set()
    for i in converted:
        for step in (-1, 1):
            dropped.update(_spaces_to_drop(text, protected, i, step))
    return "".join(converted.get(i, ch) for i, ch in enumerate(text) if i not in dropped)


def _spaces_to_drop(text: str, protected: bytearray, i: int, step: int) -> list[int]:
    """被轉換的標點（``i``）某一側緊鄰的半形空格位置。

    不清的兩種：行首縮排或 Markdown 區塊標記後面的空格（``- (輝達)``），以及行尾的空格
    （Markdown 硬換行要靠行尾兩個空格）。
    """
    run: list[int] = []
    j = i + step
    while 0 <= j < len(text) and text[j] == " " and not protected[j]:
        run.append(j)
        j += step
    if not run:
        return []
    if step < 0:
        line_start = text.rfind("\n", 0, run[-1]) + 1
        before = text[line_start : run[-1]].rstrip(" \t")
        if not before.strip() or _BLOCK_MARKER.fullmatch(before):
            return []
    elif j >= len(text) or text[j] in "\r\n":
        return []
    return run


def zh_punct(text: str) -> str:
    """把中文語境裡的半形標點轉成全形，規則見模組說明。

    重複套用到穩定（最多 ``_MAX_PASSES`` 輪），所以一般文字冪等。任何內部錯誤都記 WARNING
    並原樣回傳輸入。
    """
    try:
        current = text
        for _ in range(_MAX_PASSES):
            converted = _convert_once(current)
            if converted == current:
                break
            current = converted
        return current
    except Exception as exc:  # noqa: BLE001 — 標點正規化絕不能讓一天的流程中斷
        logger.warning("zh_punct 內部錯誤，原文照出：{}：{}", type(exc).__name__, exc)
        return text


def zh_punct_obj(obj: Any) -> Any:
    """遞迴處理 dict／list 內的字串值（dict 的鍵不動）；其他型別原樣回傳。"""
    if isinstance(obj, str):
        return zh_punct(obj)
    if isinstance(obj, dict):
        return {key: zh_punct_obj(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [zh_punct_obj(value) for value in obj]
    return obj


def zh_punct_model[T: BaseModel](model: T) -> T:
    """回傳字串欄位都已正規化的新 pydantic 物件（過一次 schema 驗證，原物件不變）。

    重新驗證失敗等任何錯誤都記 WARNING 並回傳原物件。
    """
    try:
        return type(model).model_validate(zh_punct_obj(model.model_dump()))
    except Exception as exc:  # noqa: BLE001 — 同 zh_punct：對外出口不能因此中斷
        logger.warning("zh_punct_model 內部錯誤，原物件照出：{}：{}", type(exc).__name__, exc)
        return model
