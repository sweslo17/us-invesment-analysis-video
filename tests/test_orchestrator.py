"""orchestrator 測試:artifact 盤點 + 人工 gate review 摘要(不對外發布)。"""

import datetime as dt

from pmb.orchestrator import (
    build_review_manifest,
    collect_artifacts,
    review_summary,
    script_coverage_gaps,
)
from pmb.schemas.chart import ChartSpec
from pmb.schemas.script import Script, Segment


def _write_script_with_gap(artifacts_dir, target):
    script = Script(
        segments=[Segment(vo="x", chart_id="c0", t_start=0, duration=10)],
        charts=[ChartSpec(id="c0", module="index_overnight_grid")],
        coverage_gaps=["想講『信用利差』但沒有對應圖表模組"],
    )
    (artifacts_dir / f"script_{target}.json").write_text(
        script.model_dump_json(), encoding="utf-8"
    )


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


def test_script_coverage_gaps_read_from_script(tmp_path):
    _write_script_with_gap(tmp_path, dt.date(2026, 6, 18))
    gaps = script_coverage_gaps(dt.date(2026, 6, 18), tmp_path)
    assert gaps and "信用利差" in gaps[0]


def test_review_summary_alerts_on_chart_gaps(tmp_path):
    _write_script_with_gap(tmp_path, dt.date(2026, 6, 18))
    summary = review_summary(dt.date(2026, 6, 18), tmp_path)
    assert "信用利差" in summary
    assert "圖表庫缺口" in summary  # 以 alert 形式呈現


def test_build_review_manifest_includes_coverage_gaps(tmp_path):
    _write_script_with_gap(tmp_path, dt.date(2026, 6, 18))
    manifest = build_review_manifest(dt.date(2026, 6, 18), tmp_path)
    assert manifest["coverage_gaps"]
