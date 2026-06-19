"""brief schema(pydantic v2,規格 §5.7)行為測試:必填/列舉/範圍驗證 + round-trip。"""

import datetime as dt

import pytest
from pydantic import ValidationError

from pmb.schemas.brief import Brief


def _valid_brief_dict() -> dict:
    return {
        "date": "2026-06-18",
        "indices": [
            {"name": "S&P 500", "level": 7492.58, "overnight_pct": 0.95, "drivers": ["科技股領漲"]}
        ],
        "leverage_context": [
            {"ticker": "UPRO", "overnight_pct": 0.95, "edu_note": "波動放大下耗損加劇"}
        ],
        "regime": {
            "vol": "normal",
            "rates": "stable",
            "stock_bond_corr": "positive",
            "breadth": "mixed",
        },
        "items": [
            {
                "headline": "費半隔夜走強",
                "horizon": "ST",
                "vs_thesis": "confirms",
                "materiality": 3,
                "confidence": "developing",
                "audience_value": "對科技持股者代表短期動能延續",
                "sources": [{"url": "https://example.com/a", "ts": "2026-06-18T03:12:00Z"}],
            }
        ],
        "thesis_delta": {"changed": False, "summary": None, "horizon": None},
        "lead_horizon": "ST",
    }


def test_valid_brief_parses_and_exposes_fields():
    brief = Brief.model_validate(_valid_brief_dict())
    assert brief.date == dt.date(2026, 6, 18)
    assert brief.items[0].horizon == "ST"
    assert brief.items[0].materiality == 3
    assert brief.lead_horizon == "ST"
    assert brief.regime.stock_bond_corr == "positive"


def test_materiality_out_of_range_is_rejected():
    data = _valid_brief_dict()
    data["items"][0]["materiality"] = 6
    with pytest.raises(ValidationError):
        Brief.model_validate(data)


def test_unknown_horizon_is_rejected():
    data = _valid_brief_dict()
    data["items"][0]["horizon"] = "XL"
    with pytest.raises(ValidationError):
        Brief.model_validate(data)


def test_unknown_confidence_is_rejected():
    data = _valid_brief_dict()
    data["items"][0]["confidence"] = "verified"
    with pytest.raises(ValidationError):
        Brief.model_validate(data)


def test_unknown_regime_label_is_rejected():
    data = _valid_brief_dict()
    data["regime"]["vol"] = "spicy"
    with pytest.raises(ValidationError):
        Brief.model_validate(data)


def test_brief_round_trips_through_json():
    brief = Brief.model_validate(_valid_brief_dict())
    restored = Brief.model_validate_json(brief.model_dump_json())
    assert restored == brief
