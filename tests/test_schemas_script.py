"""script schema(規格 §6.3)測試:segment↔chart 交叉驗證、時長。"""

import pytest
from pydantic import ValidationError

from pmb.schemas.script import Script


def _valid_script() -> dict:
    return {
        "segments": [
            {"vo": "隔夜四大指數收紅,費半領漲", "chart_id": "idx", "t_start": 0, "duration": 12},
            {"vo": "Fed 轉鷹,點陣圖暗示升息", "chart_id": "lev", "t_start": 12, "duration": 18},
        ],
        "charts": [
            {"id": "idx", "module": "index_overnight_grid", "params": {}},
            {"id": "lev", "module": "leverage_decay", "params": {}},
        ],
    }


def test_valid_script_parses_and_reports_total_duration():
    script = Script.model_validate(_valid_script())
    assert len(script.segments) == 2
    assert script.total_duration == pytest.approx(30.0)


def test_segment_chart_id_must_reference_a_chart():
    data = _valid_script()
    data["segments"][0]["chart_id"] = "nope"
    with pytest.raises(ValidationError):
        Script.model_validate(data)


def test_duplicate_chart_ids_are_rejected():
    data = _valid_script()
    data["charts"][1]["id"] = "idx"  # 與第一張重複
    with pytest.raises(ValidationError):
        Script.model_validate(data)


def test_unknown_chart_module_is_rejected():
    data = _valid_script()
    data["charts"][0]["module"] = "hologram"
    with pytest.raises(ValidationError):
        Script.model_validate(data)
