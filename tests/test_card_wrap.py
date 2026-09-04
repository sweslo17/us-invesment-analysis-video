"""字卡大標題斷行測試:避免標點落單、平衡斷行、保留對句換行。"""

from pmb.charts.cards import wrap_card_text


def test_short_title_stays_one_line():
    assert len(wrap_card_text("美股全面開高", max_units=9)) == 1


def test_trailing_question_mark_not_orphaned():
    lines = wrap_card_text("今天該追多還是觀望?", max_units=9)
    assert len(lines) == 2
    assert lines[-1] != "?" and lines[-1] != "?"  # 標點不獨佔一行
    assert lines[-1].endswith("?")  # 跟著內容


def test_breaks_after_punctuation_when_present():
    lines = wrap_card_text("今天最大變數,聯準會轉鷹了", max_units=8)
    assert lines[0].endswith(",")


def test_preserves_couplet_newline():
    lines = wrap_card_text("退潮的時候\n才知道誰沒穿褲子", max_units=9)
    assert "退潮的時候" in lines[0]
    assert any("沒穿褲子" in line for line in lines)
