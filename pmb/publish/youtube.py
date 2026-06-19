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
    "不構成任何買賣建議。槓桿說明為一般性的槓桿倍數風險教育,不針對任何特定商品。"
)

# YouTube 專屬 tags 欄位(與描述裡的 hashtag 不同):SEO 關鍵字
_BASE_TAGS = [
    "美股", "美股盤前", "盤前快報", "美股新聞", "美股懶人包",
    "投資", "投資理財", "理財", "財經", "股市",
    "S&P 500", "那斯達克", "道瓊", "Fed", "聯準會", "shorts",
]


def build_youtube_metadata(
    brief: Brief, channel_name: str = "美股早發車"
) -> tuple[str, str, list[str]]:
    """由 brief 組 YouTube 標題、描述、tags。

    標題走頻道公式「〔主軸〕｜M/D 美股盤前 #shorts」;描述帶今日重點 + 催化劑 +
    免責 + 追蹤 CTA + hashtag(SEO);tags 為 YouTube 專屬關鍵字欄位。
    """
    items = sorted(brief.items, key=lambda it: it.materiality, reverse=True)
    lead = items[0] if items else None
    headline = lead.headline if lead else "今日美股盤前"
    body = lead.audience_value if lead else "今日盤前市場觀察。"
    d = brief.date
    title = f"{headline}｜{d.month}/{d.day} 美股盤前 #shorts"

    parts = [f"{headline}。{body}"]
    if items:
        parts.append("\n▍今天重點\n" + "\n".join(f"・{it.headline}" for it in items[:3]))
    if brief.catalysts:
        parts.append("\n▍今天盤中要看\n" + "\n".join(f"・{c}" for c in brief.catalysts[:3]))
    parts.append(f"⚠️ {_DISCLAIMER}")
    parts.append(f"🔔 每天盤前更新,訂閱不錯過 —— {channel_name}")
    parts.append("#美股 #美股盤前 #投資理財 #理財 #財經 #shorts")
    description = "\n\n".join(parts)

    # tags:頻道名 + 基礎關鍵字,去重 + 控總長(YouTube tags 上限約 500 字元)
    tags: list[str] = []
    total = 0
    for tag in [channel_name, *_BASE_TAGS]:
        if tag in tags or total + len(tag) + 1 > 480:
            continue
        tags.append(tag)
        total += len(tag) + 1
    return title[:100], description, tags  # YouTube 標題上限 100 字


def upload_video(
    video_path: str | Path,
    *,
    title: str,
    description: str,
    tags: list[str] | None = None,
    thumbnail: str | Path | None = None,
    privacy: str = "private",
    approve: bool = False,
    manifest_path: str | Path | None = None,
    settings=None,
) -> dict:
    """上傳影片。``approve=False``(預設)只寫 manifest 不上傳。"""
    video_path = Path(video_path)
    tags = tags or []
    record = {
        "video": str(video_path),
        "title": title,
        "description": description,
        "tags": tags,
        "thumbnail": str(thumbnail) if thumbnail else None,
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

    uploaded = _do_upload(video_path, title, description, tags, privacy, settings, thumbnail)
    record["published"] = True
    record["video_id"] = uploaded["id"]
    record["channel_id"] = uploaded.get("channel_id")
    record["channel_title"] = uploaded.get("channel_title")
    logger.info(
        "已上傳 YouTube:{}(頻道 {})", uploaded["id"], uploaded.get("channel_title") or "?"
    )
    if manifest_path is not None:
        manifest_path = Path(manifest_path)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf-8")
    return record


def _do_upload(
    video_path: Path,
    title: str,
    description: str,
    tags: list[str],
    privacy: str,
    settings,
    thumbnail: str | Path | None = None,
) -> dict:
    """實際上傳(僅 approve=True 時呼叫)。需 OAuth refresh token。

    回傳 {id, channel_id, channel_title} —— 含上傳到哪個頻道,供確認目的地。
    """
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
        # youtube.upload 同時涵蓋影片上傳與 thumbnails.set(自訂封面)
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    youtube = build("youtube", "v3", credentials=creds)
    snippet = {
        "title": title,
        "description": description,
        "categoryId": getattr(settings, "youtube_category_id", "27"),  # 預設 27=教育
        "defaultLanguage": "zh-TW",  # 影片語言:繁中
        "defaultAudioLanguage": "zh-TW",  # 旁白語言(edge-tts zh-TW)
    }
    if tags:
        snippet["tags"] = tags
    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": snippet,
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
        },
        media_body=MediaFileUpload(str(video_path), resumable=True),
    )
    response = request.execute()
    video_id = response["id"]
    snip = response.get("snippet", {})

    # 自訂封面:best-effort(Shorts / 頻道資格可能拒絕,失敗不擋上傳)
    if thumbnail and Path(thumbnail).exists():
        try:
            youtube.thumbnails().set(
                videoId=video_id, media_body=MediaFileUpload(str(thumbnail))
            ).execute()
            logger.info("已設定自訂封面:{}", thumbnail)
        except Exception as exc:  # noqa: BLE001 — 封面失敗不應讓整支上傳失敗
            logger.warning("自訂封面設定失敗(略過):{}", exc)
    return {
        "id": video_id,
        "channel_id": snip.get("channelId"),
        "channel_title": snip.get("channelTitle"),
    }
