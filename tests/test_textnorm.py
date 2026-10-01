"""中文標點正規化測試：半形 ``,:;!?()`` 在中文語境轉全形，數字、網址、程式碼與英文維持原樣。

最後一組是對真實 9 月產物（``artifacts/script_*`` / ``brief_*`` / ``report_*``，唯讀）的性質檢查：
正規化後千分位、時間與網址不變，且受保護範圍之外不再有貼著中文的半形標點。
"""

import json
import random
import re
from collections import Counter
from pathlib import Path

import pytest

from pmb.schemas.script import Script
from pmb.textnorm import zh_punct, zh_punct_model, zh_punct_obj

# --- 基本轉換 ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("收紅,標普領漲", "收紅，標普領漲"),
        ("說明:內容", "說明：內容"),
        ("第一;第二", "第一；第二"),
        ("漲翻了!", "漲翻了！"),
        ("會漲嗎?", "會漲嗎？"),
        ("先漲,再跌;然後呢?結論:觀望!", "先漲，再跌；然後呢？結論：觀望！"),
        ("真的假的?!", "真的假的？！"),
        ("", ""),
        ("純英文 no marks", "純英文 no marks"),
    ],
)
def test_basic_conversions(raw, expected):
    assert zh_punct(raw) == expected


# --- 數字：千分位逗號、時間冒號、小數點、百分號維持半形 ----------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("標普收 7,670 點", "標普收 7,670 點"),
        ("美東 8:30 公布", "美東 8:30 公布"),
        ("20:30:00 開盤", "20:30:00 開盤"),
        ("比例 1:1", "比例 1:1"),
        ("殖利率 5.26%", "殖利率 5.26%"),
        ("市值 1,234,567,890 美元", "市值 1,234,567,890 美元"),
        ("收7,670.84點,跌0.17%", "收7,670.84點，跌0.17%"),
        ("目標 5,000,到時候再說", "目標 5,000，到時候再說"),
        ("早上8:30公布,盤前7,670點:觀望", "早上8:30公布，盤前7,670點：觀望"),
    ],
)
def test_digits_keep_half_width(raw, expected):
    assert zh_punct(raw) == expected


# --- 英文語境：不是中文就不動 -------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Fed, ECB",
        "Fed, ECB; BoJ: hold!",
        "Is it priced in?",
        "Lowe's",
        "S&P 500 (SPX)",
        "Fed (Federal Reserve)",
        "Hello: world",
    ],
)
def test_english_only_clauses_untouched(text):
    assert zh_punct(text) == text


# --- 中英混排 ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("PCE 3.4%,低於預期", "PCE 3.4%，低於預期"),
        ("Fed, 聯準會", "Fed，聯準會"),
        ("聯準會, Fed", "聯準會，Fed"),
        ("Q3: 營收創高", "Q3：營收創高"),
        ("U.S.,中國", "U.S.，中國"),
        ("Conference Board信心重挫,JOLTS也轉弱", "Conference Board信心重挫，JOLTS也轉弱"),
    ],
)
def test_mixed_context_converts_when_either_side_is_cjk(raw, expected):
    assert zh_punct(raw) == expected


# --- 括號：成對才轉，碰到中文才轉 ----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("資料(FRED / yfinance)", "資料（FRED / yfinance）"),
        ("殖利率 (%)", "殖利率（%）"),
        ("(輝達)", "（輝達）"),  # 括號內首尾是中文
        ("(NVDA) 輝達", "（NVDA）輝達"),  # 括號右側緊鄰中文
        ("輝達 (NVDA)", "輝達（NVDA）"),  # 括號左側緊鄰中文
        ("(a) text (b) 中", "(a) text（b）中"),  # 各自判斷，不連坐
        ("標普(S&P 500(SPX))", "標普（S&P 500（SPX））"),  # 巢狀：兩輪收斂
    ],
)
def test_parens_pair_converts_only_when_touching_cjk(raw, expected):
    assert zh_punct(raw) == expected


@pytest.mark.parametrize("text", ["1) 第一點", "(未完", "完)", "標普(S&P 500", "中文)(中文"])
def test_unmatched_parens_untouched(text):
    assert zh_punct(text) == text


def test_parens_pairing_does_not_cross_newlines():
    text = "標普(\n)收紅"  # 跨行的括號不配對
    assert zh_punct(text) == text


# --- 空白：只清掉緊鄰「被轉換標點」的半形空格 -----------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("收紅, 標普", "收紅，標普"),
        ("說明 : 內容", "說明：內容"),
        ("好 ,  壞", "好，壞"),
        ("殖利率 (%) 走高", "殖利率（%）走高"),
        ("10Y 殖利率 走高", "10Y 殖利率 走高"),
        ("Fed vs 債市", "Fed vs 債市"),
        ("Fed , ECB", "Fed , ECB"),  # 沒轉換就不動空白
        ("收紅，  標普", "收紅，  標普"),  # 本來就是全形：不碰
    ],
)
def test_space_removed_only_next_to_converted_marks(raw, expected):
    assert zh_punct(raw) == expected


# --- 受保護範圍：網址、Markdown 連結目標、行內碼、程式碼區塊 ----------------------------


def test_urls_are_untouched():
    text = "詳見 https://x.com/a,b?c=1:2;d 這裡"
    assert zh_punct(text) == text


def test_url_trailing_punctuation_belongs_to_the_sentence_not_the_url():
    assert zh_punct("來源https://x.com/a,然後再說") == "來源https://x.com/a，然後再說"


def test_markdown_link_target_untouched_but_surroundings_converted():
    raw = "[標題](https://x.com/a,b) 其他,內容"
    assert zh_punct(raw) == "[標題](https://x.com/a,b) 其他，內容"


def test_inline_code_untouched():
    raw = "執行 `pmb run, --dry-run` 後,檢查"
    assert zh_punct(raw) == "執行 `pmb run, --dry-run` 後，檢查"


def test_fenced_code_block_untouched():
    raw = "說明:\n```\nfoo, 中文: bar!\n```\n結束,完"
    assert zh_punct(raw) == "說明：\n```\nfoo, 中文: bar!\n```\n結束，完"


def test_parens_inside_protected_spans_are_not_paired():
    raw = "(見 `f(x)` 與 [連結](https://x.com/a_(b)) 說明)"
    assert zh_punct(raw) == "（見 `f(x)` 與 [連結](https://x.com/a_(b)) 說明）"


# --- 不該動的字元 ------------------------------------------------------------------


def test_ass_line_break_and_corner_brackets_untouched():
    raw = "第一行\\N第二行,結尾"
    assert zh_punct(raw) == "第一行\\N第二行，結尾"
    assert zh_punct("他說:「好,壞」") == "他說：「好，壞」"
    assert zh_punct("Fed,「鷹派」") == "Fed，「鷹派」"
    assert zh_punct("『差』,不是『好』") == "『差』，不是『好』"


def test_other_punctuation_and_newlines_untouched():
    raw = 'He said "ok." 3.5% isn\'t 好,吧\n第二行,\n'
    assert zh_punct(raw) == 'He said "ok." 3.5% isn\'t 好，吧\n第二行，\n'


def test_already_fullwidth_text_is_unchanged():
    text = "收紅，標普。（含）「引」：好！嗎？；還有……"
    assert zh_punct(text) == text


# --- 冪等 -------------------------------------------------------------------------

_IDEMPOTENCE_SAMPLES = [
    "收紅,標普領漲;VIX 回落:恐慌降溫!會續嗎?",
    "標普(S&P 500(SPX))收紅 (含期貨)",
    "A ,, 中",
    "((中))",
    "資料(FRED / yfinance), 與 CPI (3.4%)",
    "`a,b` 中,文 [x](https://x.com/a,b) 後,面",
    "第一行\\N第二行,結尾\n```\nx, 中: y\n```\n完,",
    "7,670 點,8:30 公布(美東)",
    "Fed, ECB (歐洲央行) : 觀望 ? 不一定 !",
]


@pytest.mark.parametrize("text", _IDEMPOTENCE_SAMPLES)
def test_zh_punct_is_idempotent(text):
    once = zh_punct(text)
    assert zh_punct(once) == once


def test_random_mixed_text_is_idempotent_and_only_marks_and_spaces_change():
    rng = random.Random(7)
    pieces = [*"中文標普,:;!?()  .%79:`[]\\N「」，。abcFed\n\t（）…"]
    pieces += ["https://x.com/a,b", "```", "]("]
    marks_and_spaces = set(" ,:;!?()，：；！？（）")
    for _ in range(3000):
        text = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 25)))
        once = zh_punct(text)
        assert zh_punct(once) == once, repr(text)
        keep = lambda s: [c for c in s if c not in marks_and_spaces]  # noqa: E731
        assert keep(once) == keep(text), repr(text)


# --- zh_punct_obj / zh_punct_model ------------------------------------------------


def test_obj_converts_string_values_recursively_but_not_keys():
    obj = {
        "key,中": "值,中",
        "list": ["a,中", {"nested": "b:中"}, 3, None, True, 1.5],
        "n": 7,
    }
    assert zh_punct_obj(obj) == {
        "key,中": "值，中",
        "list": ["a，中", {"nested": "b：中"}, 3, None, True, 1.5],
        "n": 7,
    }


def test_obj_returns_other_types_unchanged():
    assert zh_punct_obj(None) is None
    assert zh_punct_obj(42) == 42
    assert zh_punct_obj(2.5) == 2.5
    pair = ("a,中", "b")
    assert zh_punct_obj(pair) is pair  # tuple 不遞迴（規格只處理 dict/list/str）
    assert zh_punct_obj("a,中") == "a，中"


def test_obj_does_not_mutate_its_input():
    obj = {"a": ["x,中"]}
    zh_punct_obj(obj)
    assert obj == {"a": ["x,中"]}


def test_model_roundtrips_through_validation():
    script = Script.model_validate({
        "segments": [
            {"kind": "card", "vo": "開場,先看重點!", "headline": "債市暴走,Fed不急",
             "tag": "今日盤前:速報"},
            {"kind": "bignum", "vo": "數字是7,670點。", "value": "7,670", "label": "標普(昨收)"},
        ],
        "charts": [],
        "gags": ["梗,一"],
    })
    out = zh_punct_model(script)
    assert isinstance(out, Script)
    assert out.segments[0].vo == "開場，先看重點！"
    assert out.segments[0].headline == "債市暴走，Fed不急"
    assert out.segments[0].tag == "今日盤前：速報"
    assert out.segments[1].value == "7,670" and out.segments[1].label == "標普（昨收）"
    assert out.gags == ["梗，一"]
    assert script.segments[0].vo == "開場,先看重點!"  # 原物件不變


# --- 性質檢查：真實 9 月產物（唯讀）--------------------------------------------------

_ARTIFACTS = Path(__file__).resolve().parent.parent / "artifacts"
_SEPT_FILES = sorted(
    [
        *_ARTIFACTS.glob("script_2026-09-*.json"),
        *_ARTIFACTS.glob("brief_2026-09-*.json"),
        *_ARTIFACTS.glob("report_2026-09-*.md"),
    ]
)

_CJK_RE = re.compile("[\u3400-\u9fff\u3001-\u303f\uff00-\uffef\u2026\u22ef]")
_URL_RE = re.compile(r"https?://\S+")
_THOUSANDS_RE = re.compile(r"\d,\d{3}")
_CLOCK_RE = re.compile(r"\d:\d\d")
_PAIR_RE = re.compile(r"\(([^()\n]*)\)")  # 最內層、同一行的括號對


def _is_cjk(ch: str) -> bool:
    return bool(ch) and _CJK_RE.match(ch) is not None


def _nearest(text: str, i: int, step: int) -> str:
    """往 ``step`` 方向找第一個非空白字元（不跨行）；沒有回空字串。"""
    j = i + step
    while 0 <= j < len(text) and text[j] in " \t":
        j += step
    return text[j] if 0 <= j < len(text) else ""


def half_width_violations(text: str) -> Counter:
    """受保護範圍（網址）之外，仍貼著中文的半形 ``,:;!?`` 與成對 ``()``，依標點計數。"""
    text = _URL_RE.sub("\x00", text)
    found: Counter = Counter()
    for m in re.finditer(r"[,:;!?]", text):
        i, ch = m.start(), m.group()
        if ch in ",:" and text[i - 1 : i].isdigit() and text[i + 1 : i + 2].isdigit():
            continue
        if _is_cjk(_nearest(text, i, -1)) or _is_cjk(_nearest(text, i, 1)):
            found[ch] += 1
    for m in _PAIR_RE.finditer(text):
        inner = m.group(1).strip()
        edges = (
            _nearest(text, m.start(), -1),
            _nearest(text, m.end() - 1, 1),
            inner[:1],
            inner[-1:],
        )
        if any(_is_cjk(e) for e in edges):
            found["()"] += 1
    return found


def _string_values(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _string_values(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _string_values(v)


def _before_after(path: Path) -> list[tuple[str, str]]:
    """（正規化前，正規化後）的文字配對；JSON 逐字串值處理，Markdown 整份處理。"""
    if path.suffix == ".json":
        return [(s, zh_punct(s)) for s in _string_values(json.loads(path.read_text("utf-8")))]
    text = path.read_text("utf-8")
    return [(text, zh_punct(text))]


@pytest.mark.skipif(not _SEPT_FILES, reason="找不到 9 月歷史產物")
def test_property_check_over_september_artifacts():
    before_total: Counter = Counter()
    after_total: Counter = Counter()
    for path in _SEPT_FILES:
        for raw, norm in _before_after(path):
            assert Counter(_THOUSANDS_RE.findall(norm)) == Counter(_THOUSANDS_RE.findall(raw)), path
            assert Counter(_CLOCK_RE.findall(norm)) == Counter(_CLOCK_RE.findall(raw)), path
            assert [u.rstrip(",.;:!?)") for u in _URL_RE.findall(norm)] == [
                u.rstrip(",.;:!?)") for u in _URL_RE.findall(raw)
            ], path
            before_total += half_width_violations(raw)
            after_total += half_width_violations(norm)
            assert zh_punct(norm) == norm, f"{path.name} 不冪等"
    assert sum(before_total.values()) > 0, "9 月產物本來就該有半形標點,檢查才有意義"
    assert sum(after_total.values()) == 0, f"正規化後仍有半形標點貼著中文:{dict(after_total)}"
