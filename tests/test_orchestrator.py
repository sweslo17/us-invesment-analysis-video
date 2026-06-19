"""orchestrator 測試:artifact 盤點 + 人工 gate review 摘要(不對外發布)。"""

import datetime as dt

from pmb.orchestrator import build_review_manifest, collect_artifacts, review_summary


def test_collect_artifacts_detects_present_and_missing(tmp_path):
    (tmp_path / "brief_2026-06-18.json").write_text("{}", encoding="utf-8")
    (tmp_path / "report_2026-06-18.md").write_text("# r", encoding="utf-8")
    arts = collect_artifacts(dt.date(2026, 6, 18), tmp_path)
    assert arts["brief"] is not None
    assert arts["report"] is not None
    assert arts["video"] is None  # 還沒合成


def test_review_summary_flags_manual_gate(tmp_path):
    summary = review_summary(dt.date(2026, 6, 18), tmp_path)
    assert "人工" in summary or "放行" in summary
    assert "非投資建議" in summary


def test_build_review_manifest_marks_not_published(tmp_path):
    manifest = build_review_manifest(dt.date(2026, 6, 18), tmp_path)
    assert manifest["published"] is False
    assert manifest["approved"] is False
    assert (tmp_path / "review_2026-06-18.json").exists()
