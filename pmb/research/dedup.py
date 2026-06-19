"""horizon-aware 去重——規格 §5.5。

主要去重由研究 LLM 在 prompt 中對昨日 brief 完成;此處為確定性後備:
短期(ST)項目若與昨日 ST 標題重複則丟棄;中長期(MT/LT)一律保留,當作持續
追蹤的 open thread,不因「昨天提過」而蓋掉長期訊號。
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from loguru import logger

from pmb.schemas.brief import Brief, BriefItem


def _norm(headline: str) -> str:
    """標題正規化:casefold + 去除所有空白,供寬鬆比對。"""
    return "".join(headline.split()).casefold()


def dedup_items(today: list[BriefItem], yesterday: list[BriefItem]) -> list[BriefItem]:
    """回傳去重後的今日項目。"""
    prev_short_term = {_norm(i.headline) for i in yesterday if i.horizon == "ST"}
    kept: list[BriefItem] = []
    for item in today:
        if item.horizon == "ST" and _norm(item.headline) in prev_short_term:
            logger.debug("去重:丟棄重複的短期項目「{}」", item.headline)
            continue
        kept.append(item)
    return kept


def load_previous_brief(artifacts_dir: str | Path, before_date: dt.date) -> Brief | None:
    """讀取 ``before_date`` 之前(不含)最近一份 ``brief_<date>.json``;沒有則回 None。"""
    artifacts_dir = Path(artifacts_dir)
    best: Brief | None = None
    for path in artifacts_dir.glob("brief_*.json"):
        try:
            brief = Brief.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("略過無法解析的 brief {}:{}", path, exc)
            continue
        if brief.date < before_date and (best is None or brief.date > best.date):
            best = brief
    return best
