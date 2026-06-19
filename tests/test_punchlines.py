"""每日金句測試:依日期確定性、會輪替。"""

import datetime as dt

from pmb.research.punchlines import punchline_for


def test_punchline_is_deterministic_per_date():
    assert punchline_for(dt.date(2026, 6, 18)) == punchline_for(dt.date(2026, 6, 18))
    line1, line2, source = punchline_for(dt.date(2026, 6, 18))
    assert line1 and line2 and source


def test_punchline_rotates_across_days():
    picks = {punchline_for(dt.date(2026, 6, 18) + dt.timedelta(days=i)) for i in range(8)}
    assert len(picks) >= 2
