"""YouTube 上傳(Data API v3)——**預設 dry-run / 需人工放行**(鐵則 #6)。

``upload_video(..., approve=False)``(預設)只寫 publish manifest、絕不上傳、不需任何憑證;
``approve=True`` 才真正上傳(需 OAuth refresh token)。開發期一律不對外公開。
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from pmb.schemas.brief import Brief

_DISCLAIMER = (
    "本影片為市場資訊與風險教育,非投資建議。數字來自公開資料(FRED / yfinance),"
    "不構成任何買賣建議。槓桿說明為全市場最適槓桿教育,與任何 ETF 商品無關。"
)


def build_youtube_metadata(brief: Brief) -> tuple[str, str]:
    """由 brief 組 YouTube 標題與描述(描述固定帶免責)。"""
    items = sorted(brief.items, key=lambda it: it.materiality, reverse=True)
    lead = items[0] if items else None
    title = f"盤前市場觀察 · {brief.date}"
    if lead:
        title = f"{title}|{lead.headline}"
    body = lead.audience_value if lead else "今日盤前市場觀察。"
    headline = lead.headline if lead else ""
    description = f"{headline}\n\n{body}\n\n— — —\n{_DISCLAIMER}"
    return title[:100], description  # YouTube 標題上限 100 字


def upload_video(
    video_path: str | Path,
    *,
    title: str,
    description: str,
    privacy: str = "private",
    approve: bool = False,
    manifest_path: str | Path | None = None,
    settings=None,
) -> dict:
    """上傳影片。``approve=False``(預設)只寫 manifest 不上傳。"""
    video_path = Path(video_path)
    record = {
        "video": str(video_path),
        "title": title,
        "description": description,
        "privacy": privacy,
        "approved": approve,
        "published": False,
    }

    if not approve:
        logger.info("dry-run:未上傳 YouTube(需 --approve 放行)。標題:{}", title)
        if manifest_path is not None:
            manifest_path = Path(manifest_path)
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf-8")
        return record

    video_id = _do_upload(video_path, title, description, privacy, settings)
    record["published"] = True
    record["video_id"] = video_id
    logger.info("已上傳 YouTube:{}", video_id)
    return record


def _do_upload(video_path: Path, title: str, description: str, privacy: str, settings) -> str:
    """實際上傳(僅 approve=True 時呼叫)。需 OAuth refresh token。"""
    if settings is None or not settings.youtube_refresh_token:
        raise RuntimeError("缺少 YouTube OAuth 憑證(youtube_client_id/secret/refresh_token)")

    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = Credentials(
        token=None,
        refresh_token=settings.youtube_refresh_token,
        client_id=settings.youtube_client_id,
        client_secret=settings.youtube_client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    youtube = build("youtube", "v3", credentials=creds)
    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {"title": title, "description": description, "categoryId": "25"},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
        },
        media_body=MediaFileUpload(str(video_path), resumable=True),
    )
    response = request.execute()
    return response["id"]
