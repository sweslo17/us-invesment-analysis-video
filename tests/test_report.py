"""報告 markdown 渲染測試(規格 §7.1):結構、免責、槓桿數字注入。"""

import datetime as dt

from pmb.publish.report import render_report
from pmb.schemas.brief import Brief
from pmb.schemas.snapshot import LeverageMath, Snapshot


def _brief() -> Brief:
    return Brief.model_validate(
        {
            "date": "2026-06-18",
            "indices": [
                {
                    "name": "S&P 500",
                    "level": 7500.58,
                    "overnight_pct": 1.08,
                    "drivers": ["科技領漲"],
                }
            ],
            "leverage_context": [
                {"market": "Nasdaq Composite", "edu_note": "波動高,合理曝險反而更低。"}
            ],
            "regime": {
                "vol": "low",
                "rates": "rising",
                "stock_bond_corr": "positive",
                "breadth": "mixed",
            },
            "items": [
                {
                    "headline": "Fed 轉鷹,點陣圖暗示 2026 升息",
                    "horizon": "LT",
                    "vs_thesis": "new",
                    "materiality": 5,
                    "confidence": "confirmed",
                    "audience_value": "利率往哪走牽動所有資產定價。",
                    "sources": [{"url": "https://example.com/fed"}],
                }
            ],
            "thesis_delta": {"changed": True, "summary": "基準轉為升息風險浮現", "horizon": "LT"},
            "lead_horizon": "LT",
        }
    )


def _snapshot() -> Snapshot:
    return Snapshot(
        session_date=dt.date(2026, 6, 18),
        generated_at=dt.datetime(2026, 6, 18, 12, 0, tzinfo=dt.UTC),
        leverage_math=[
            LeverageMath(
                market="Nasdaq Composite",
                realized_vol=0.256,
                vol_target_leverage=0.59,
                drag_1x=0.0328,
                drag_2x=0.1311,
                drag_3x=0.2950,
            )
        ],
    )


def test_report_has_date_lead_item_and_disclaimer():
    md = render_report(_brief(), _snapshot())
    assert "2026-06-18" in md
    assert "Fed 轉鷹" in md
    assert "非投資建議" in md
    assert "S&P 500" in md


def test_report_injects_leverage_numbers_from_snapshot():
    md = render_report(_brief(), _snapshot())
    # 槓桿數字來自 snapshot.leverage_math,不是 brief 文字
    assert "0.59" in md  # vol_target_leverage
    assert "波動高,合理曝險反而更低" in md  # brief 的文字說明


def test_report_works_without_snapshot():
    md = render_report(_brief())
    assert "Fed 轉鷹" in md and "非投資建議" in md
