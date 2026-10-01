"""YouTube 上傳測試:metadata 帶免責、dry-run 只寫 manifest 不上傳(人工 gate)。"""

import json
import re

from pmb.publish import youtube
from pmb.publish.youtube import build_youtube_metadata, upload_video
from pmb.schemas.brief import Brief
from pmb.textnorm import zh_punct


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
    title, description, tags = build_youtube_metadata(_brief(), channel_name="美股早發車")
    assert "6/18" in title  # 標題走「M/D 美股盤前」公式
    assert "美股盤前" in title and "#shorts" in title
    assert "Fed 轉鷹" in description
    assert "非投資建議" in description
    assert "美股早發車" in description  # 追蹤 CTA 帶頻道名
    assert "#美股" in description  # SEO hashtag


def test_title_uses_title_hook_when_present():
    # 有 title_hook 時,標題用研究端寫的前瞻鉤子(而非最高 materiality 的回顧型 headline)
    brief = _brief()
    brief.title_hook = "今晚 Micron 財報，AI 多頭要當場交卷"
    title, description, _tags = build_youtube_metadata(brief, channel_name="美股早發車")
    assert title.startswith("今晚 Micron 財報，AI 多頭要當場交卷｜")
    assert "6/18 美股盤前 #shorts" in title  # 日期 / 後綴仍自動接上
    assert "Fed 轉鷹" in description  # 描述仍以最高 materiality 的 item 為主


def test_metadata_normalizes_halfwidth_punctuation_in_title_and_description():
    """標題與描述是公開文字:研究端寫了半形標點也要在出口轉成全形;後綴與數字維持原樣。"""
    brief = _brief()
    brief.title_hook = "今晚 Micron 財報,AI 多頭要當場交卷!"
    brief.items[0].headline = "Fed 轉鷹,殖利率 (10Y) 創高"
    brief.items[0].audience_value = "利率往哪走:牽動所有資產定價;影響每個人。"
    brief.catalysts = ["20:30 公布 CPI(核心)", "盤後 NVIDIA 財報, 市場關注指引"]
    title, description, _tags = build_youtube_metadata(brief, channel_name="美股早發車")
    assert title == "今晚 Micron 財報，AI 多頭要當場交卷！｜6/18 美股盤前 #shorts"
    assert "Fed 轉鷹，殖利率（10Y）創高。利率往哪走：牽動所有資產定價；影響每個人。" in description
    assert "・20:30 公布 CPI（核心）" in description  # 時間的冒號維持半形
    assert "・盤後 NVIDIA 財報，市場關注指引" in description
    assert "數字來自公開資料（FRED / yfinance）" in description
    assert "每天盤前更新，訂閱不錯過 —— 美股早發車" in description
    assert not re.search(r"[\u3400-\u9fff][,;!?]|[,;!?][\u3400-\u9fff]", description)


def test_fixed_description_strings_are_fullwidth_at_the_source(monkeypatch):
    """免責與追蹤 CTA 的固定文字本身就用全形(不靠出口的正規化兜底)。"""
    monkeypatch.setattr(youtube, "zh_punct", lambda text: text)
    _title, description, _tags = build_youtube_metadata(_brief(), channel_name="美股早發車")
    assert "本影片為市場資訊與風險教育，非投資建議。" in description
    assert "數字來自公開資料（FRED / yfinance），不構成任何買賣建議。" in description
    assert "🔔 每天盤前更新，訂閱不錯過 —— 美股早發車" in description
    assert zh_punct(youtube._DISCLAIMER) == youtube._DISCLAIMER


def test_title_falls_back_to_materiality_lead_without_hook():
    # 無 title_hook(或空字串)時,退回原本「最高 materiality 的 headline」行為
    for hook in (None, "", "   "):
        brief = _brief()
        brief.title_hook = hook
        title, _desc, _tags = build_youtube_metadata(brief, channel_name="美股早發車")
        assert title.startswith("Fed 轉鷹｜")


def test_metadata_tags_field_populated():
    _title, _desc, tags = build_youtube_metadata(_brief(), channel_name="美股早發車")
    assert "美股盤前" in tags  # YouTube 專屬 tags 欄位有填
    assert "美股早發車" in tags  # 含頻道名
    assert len(tags) == len(set(tags))  # 不重複
    assert sum(len(t) + 1 for t in tags) <= 500  # YouTube tags 總長上限


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


def test_upload_privacy_is_recorded_and_never_public_by_default(tmp_path):
    # 可見度可設(private/unlisted),且預設不是 public(絕不自動公開)
    result = upload_video(
        tmp_path / "v.mp4", title="t", description="d", privacy="unlisted", approve=False
    )
    assert result["privacy"] == "unlisted"
    default = upload_video(tmp_path / "v.mp4", title="t", description="d", approve=False)
    assert default["privacy"] != "public"


def test_upload_records_synthetic_disclosure_and_playlist(tmp_path):
    # 合成內容揭露預設開;播放清單設定與結果都落 manifest(dry-run 不觸網)
    result = upload_video(
        tmp_path / "v.mp4",
        title="t",
        description="d",
        approve=False,
        playlist_id="PL123",
    )
    assert result["contains_synthetic_media"] is True
    assert result["playlist_id"] == "PL123"
    assert result["playlist_added"] is False  # 未上傳自然未加入
