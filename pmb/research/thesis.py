"""滾動 thesis(市場 regime 基準情境)的 schema 與讀寫——規格 §5.2。

每日:讀 thesis → 研究 → 評估 delta → 重大且夠確認才更新。thesis 以市場狀態為主,
非個人部位。更新要保守。
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from loguru import logger
from pydantic import BaseModel

from pmb.schemas.brief import Confidence, Horizon


class ThesisPillar(BaseModel):
    """thesis 的一根支柱(一個中長期判斷)。"""

    topic: str
    stance: str
    horizon: Horizon
    confidence: Confidence
    updated: dt.date | None = None


class Thesis(BaseModel):
    as_of: dt.date | None = None
    summary: str = ""
    pillars: list[ThesisPillar] = []
    open_threads: list[str] = []


def load_thesis(path: str | Path) -> Thesis:
    """讀 thesis.json;檔案不存在時回傳空的 seed thesis(首次執行)。"""
    path = Path(path)
    if not path.exists():
        logger.info("找不到 thesis {},回傳空白 seed", path)
        return Thesis()
    return Thesis.model_validate_json(path.read_text(encoding="utf-8"))


def save_thesis(thesis: Thesis, path: str | Path) -> None:
    """寫出 thesis.json(自動建父目錄)。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(thesis.model_dump_json(indent=2), encoding="utf-8")
    logger.info("thesis 已寫入 {}", path)
