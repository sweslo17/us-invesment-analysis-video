"""YouTube 上傳測試:metadata 帶免責、dry-run 只寫 manifest 不上傳(人工 gate)。"""

import json

from pmb.publish.youtube import build_youtube_metadata, upload_video
from pmb.schemas.brief import Brief


def _brief() -> Brief:
    return Brief.model_validate(
        {
            "date": "2026-06-18",
            "regime": {
                "vol": "low",
                "rates": "rising",
                "stock_bond_corr": "positive",
                "breadth": "mixed",
            },
            "items": [
                {
                    "headline": "Fed 轉鷹",
                    "horizon": "LT",
                    "vs_thesis": "new",
                    "materiality": 5,
                    "confidence": "confirmed",
                    "audience_value": "利率牽動一切。",
                }
            ],
            "thesis_delta": {"changed": False},
            "lead_horizon": "LT",
        }
    )


def test_metadata_has_date_lead_and_disclaimer():
    title, description = build_youtube_metadata(_brief())
    assert "2026-06-18" in title
    assert "Fed 轉鷹" in description
    assert "非投資建議" in description


def test_upload_dry_run_writes_manifest_and_does_not_publish(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    manifest = tmp_path / "publish.json"
    result = upload_video(
        video, title="t", description="d", approve=False, manifest_path=manifest
    )
    assert result["approved"] is False
    assert result["published"] is False
    assert manifest.exists()
    data = json.loads(manifest.read_text())
    assert data["title"] == "t"


def test_upload_without_approve_never_calls_network(tmp_path):
    # approve=False 路徑不得需要任何憑證/網路:沒給 settings 也能跑
    result = upload_video(tmp_path / "v.mp4", title="t", description="d", approve=False)
    assert result["published"] is False
