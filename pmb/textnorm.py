"""中文標點正規化：公開文字裡，中文語境的半形 ``,:;!?()`` 一律改成全形。

句號早就是全形 ``。``，其餘標點卻是半形，畫面與文章看起來不一致。模型模仿 prompt 的
寫法，所以在研究產物的源頭與所有對外出口各套一次同一支 ``zh_punct``，規則只有這一份。

規則：

- ``,`` ``:`` ``;`` ``!`` ``?``：緊鄰（略過空白）的前一個或後一個字元屬於中文語境才轉；
  緊鄰的是英數 token（``66%``、``FOMC``、``**``…）就穿透這一個 token（連同空白）再看下一個
  字元，是中文也算，所以 ``66%,10年期`` 與 ``對 Fed, ECB 與 BoJ`` 都會轉，``S&P 500, Nasdaq``
  不會。數字之間的 ``,`` ``:``（``7,670``、``8:30``）維持半形。
- ``(`` ``)``：先配對，成對的括號碰到中文（外側左右、內側首尾）才整對轉，否則整對不動；
  沒配到對的不動。巢狀括號反覆套用到不再變化為止。
- 被轉成全形的標點，緊鄰的半形空格一併清掉；其他空白不動。
- 網址、Markdown 連結目標、行內碼、程式碼區塊不碰。
- 其他字元（``.`` ``%`` 引號、換行、``\\N``、本來就是全形的標點）一律不動。

``zh_punct`` 是冪等的：已正規化的文字再套一次不會變。
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

_MARKS = {",": "，", ":": "：", ";": "；", "!": "！", "?": "？"}
_CANDIDATES = re.compile(r"[,:;!?()]")
_SPACES = " \t"
_TOKEN_PUNCT = ".%$+-/&'*_"

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


def _is_token_char(text: str, j: int) -> bool:
    """英數 token 的字元：ASCII 英數、``%.$+-/&'``、Markdown 強調的 ``*`` ``_``，
    以及夾在數字之間的 ``,`` ``:``（``7,670``、``9:05`` 是同一個 token）。"""
    ch = text[j]
    if ch.isascii() and ch.isalnum() or ch in _TOKEN_PUNCT:
        return True
    return ch in ",:" and _between_digits(text, j)


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
    if text[i] in ",:" and _between_digits(text, i):
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
            j = i + step
            while 0 <= j < len(text) and text[j] == " " and not protected[j]:
                dropped.add(j)
                j += step
    return "".join(converted.get(i, ch) for i, ch in enumerate(text) if i not in dropped)


def zh_punct(text: str) -> str:
    """把中文語境裡的半形標點轉成全形，規則見模組說明。重複套用到穩定，所以冪等。"""
    while True:
        converted = _convert_once(text)
        if converted == text:
            return text
        text = converted


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
    """回傳字串欄位都已正規化的新 pydantic 物件（過一次 schema 驗證，原物件不變）。"""
    return type(model).model_validate(zh_punct_obj(model.model_dump()))
