"""確定性 pipeline 編排 + 人工 gate。

吃 routine / 前面步驟產出的 artifacts(snapshot / brief / script / report / video),
盤點、組出 review manifest 並落到 review 資料夾,等人工放行。**絕不自動對外發布**
(發布是另一條 ``pmb publish --approve`` 的明確步驟)。
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from loguru import logger

_GATE_NOTE = (
    "此為開發/審稿用途:所有產物落在本機 review 資料夾,**不會自動對外發布**。"
    "確認內容無誤後,影片用 `pmb publish --approve` 放行上傳;報告人工貼上。"
    "全部內容為市場資訊與風險教育,非投資建議。"
)

_ARTIFACT_FILES = {
    "snapshot": "snapshot_{d}.json",
    "brief": "brief_{d}.json",
    "script": "script_{d}.json",
    "report": "report_{d}.md",
    "video": "video_{d}.mp4",
}


def collect_artifacts(target: dt.date, artifacts_dir: str | Path) -> dict[str, Path | None]:
    """盤點某交易日的各項產物是否已存在,回傳 {名稱: 路徑或 None}。"""
    artifacts_dir = Path(artifacts_dir)
    found: dict[str, Path | None] = {}
    for name, pattern in _ARTIFACT_FILES.items():
        path = artifacts_dir / pattern.format(d=target)
        found[name] = path if path.exists() else None
    return found


def review_summary(target: dt.date, artifacts_dir: str | Path) -> str:
    """人工 gate 用的可讀摘要:列出各產物狀態 + 放行提示。"""
    arts = collect_artifacts(target, artifacts_dir)
    lines = [f"=== {target} 產物審查(人工放行 gate)==="]
    for name, path in arts.items():
        mark = "✓" if path else "—"
        lines.append(f"  [{mark}] {name:<9} {path.name if path else '(未產出)'}")
    lines.append("")
    lines.append(_GATE_NOTE)
    return "\n".join(lines)


def build_review_manifest(target: dt.date, artifacts_dir: str | Path) -> dict:
    """寫出 review manifest(標記未放行/未發布),供 gate 流程追蹤。"""
    artifacts_dir = Path(artifacts_dir)
    arts = collect_artifacts(target, artifacts_dir)
    manifest = {
        "date": str(target),
        "artifacts": {k: (str(v) if v else None) for k, v in arts.items()},
        "approved": False,
        "published": False,
        "note": _GATE_NOTE,
    }
    out = artifacts_dir / f"review_{target}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("review manifest → {}", out)
    return manifest
