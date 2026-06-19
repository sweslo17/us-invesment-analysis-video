"""thesis.json 讀寫測試:round-trip、缺檔回 seed、自動建父目錄。"""

import datetime as dt

from pmb.research.thesis import Thesis, ThesisPillar, load_thesis, save_thesis


def test_save_and_load_thesis_round_trips(tmp_path):
    path = tmp_path / "thesis.json"
    thesis = Thesis(
        as_of=dt.date(2026, 6, 18),
        summary="基準:溫和擴張、Fed 觀望",
        pillars=[
            ThesisPillar(
                topic="Fed 政策",
                stance="higher-for-longer",
                horizon="LT",
                confidence="confirmed",
                updated=dt.date(2026, 6, 1),
            )
        ],
        open_threads=["AI capex 是否出現拐點"],
    )
    save_thesis(thesis, path)
    assert load_thesis(path) == thesis


def test_load_thesis_missing_file_returns_seed(tmp_path):
    thesis = load_thesis(tmp_path / "nope.json")
    assert thesis.as_of is None
    assert thesis.pillars == []
    assert thesis.open_threads == []


def test_save_thesis_creates_parent_dirs(tmp_path):
    path = tmp_path / "state" / "thesis.json"
    save_thesis(Thesis(summary="x"), path)
    assert path.exists()
