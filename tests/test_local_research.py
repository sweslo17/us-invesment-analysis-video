"""本機研究 runner 測試:驗證/重試迴圈與產物檢查(注入假 invoke,不跑 claude CLI)。"""

import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace

from pmb.research.local_runner import run_local_research, validate_research_artifacts
from pmb.research.sample import sample_brief_json
from pmb.schemas.brief import Brief
from pmb.schemas.snapshot import Snapshot

_D = dt.date(2026, 7, 10)


def _settings(tmp_path: Path) -> SimpleNamespace:
    arts = tmp_path / "artifacts"
    state = tmp_path / "state"
    arts.mkdir()
    state.mkdir()
    snap = Snapshot(session_date=_D, generated_at=dt.datetime.now(tz=dt.UTC))
    (arts / f"snapshot_{_D}.json").write_text(snap.model_dump_json(), encoding="utf-8")
    prompt = tmp_path / "prompt.md"
    prompt.write_text("研究任務模板", encoding="utf-8")
    return SimpleNamespace(artifacts_dir=arts, state_dir=state, prompt_path=prompt)


def _write_valid_artifacts(arts: Path) -> None:
    brief = Brief.model_validate_json(sample_brief_json(_D))
    (arts / f"brief_{_D}.json").write_text(brief.model_dump_json(), encoding="utf-8")
    script = {
        "segments": [
            {"vo": "測試句。", "chart_id": "c0", "t_start": 0.0, "duration": 5.0},
        ],
        "charts": [{"id": "c0", "module": "index_overnight_grid", "params": {}}],
    }
    (arts / f"script_{_D}.json").write_text(json.dumps(script), encoding="utf-8")
    (arts / f"report_{_D}.md").write_text("# 報告\n" + "內容 " * 200, encoding="utf-8")


def test_validate_reports_missing_and_invalid_artifacts(tmp_path):
    errors = validate_research_artifacts(tmp_path, _D)
    assert len(errors) == 3  # brief/script/report 全缺
    (tmp_path / f"brief_{_D}.json").write_text("{not json")
    errors = validate_research_artifacts(tmp_path, _D)
    assert any("schema" in e for e in errors)


def test_run_local_research_succeeds_when_agent_writes_valid_files(tmp_path):
    settings = _settings(tmp_path)
    calls: list[str] = []

    def fake_invoke(prompt: str) -> None:
        calls.append(prompt)
        _write_valid_artifacts(settings.artifacts_dir)

    assert run_local_research(_D, settings, invoke=fake_invoke) is True
    assert len(calls) == 1
    assert "快照" in calls[0] and "artifacts/brief_" in calls[0]  # files 模式 prompt


def test_run_local_research_retries_with_error_feedback_then_succeeds(tmp_path):
    settings = _settings(tmp_path)
    calls: list[str] = []

    def flaky_invoke(prompt: str) -> None:
        calls.append(prompt)
        if len(calls) == 1:
            (settings.artifacts_dir / f"brief_{_D}.json").write_text("{broken")
        else:
            _write_valid_artifacts(settings.artifacts_dir)

    assert run_local_research(_D, settings, invoke=flaky_invoke) is True
    assert len(calls) == 2
    assert "未通過驗證" in calls[1]  # 第二次帶錯誤回饋

    # 用盡重試 → False(不拋例外)
    always_bad = lambda p: (settings.artifacts_dir / f"script_{_D}.json").write_text("x")  # noqa: E731
    for f in settings.artifacts_dir.glob(f"*_{_D}.json"):
        if "snapshot" not in f.name:
            f.unlink()
    assert run_local_research(_D, settings, invoke=always_bad, max_attempts=2) is False
