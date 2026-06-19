"""dry-run 用的範例 brief(不打外部、schema 合法),供煙霧測試 pipeline 接線。

正式研究由 LLM 產出;此處只是讓 ``pmb research --dry-run`` 能在無金鑰、不連網下
跑通 runner → 驗證 → 去重 → 寫檔 的完整流程。
"""

from __future__ import annotations

import datetime as dt

from pmb.schemas.brief import Brief, BriefItem, Regime, ThesisDelta


def sample_brief(session_date: dt.date) -> Brief:
    return Brief(
        date=session_date,
        regime=Regime(vol="normal", rates="stable", stock_bond_corr="neutral", breadth="mixed"),
        items=[
            BriefItem(
                headline="(dry-run 範例)隔夜美股小幅走高,缺乏單一主導敘事",
                horizon="ST",
                vs_thesis="confirms",
                materiality=2,
                confidence="developing",
                audience_value="對一般投資人而言,代表短期風險偏好穩定,沒有需要立即反應的變化",
            )
        ],
        thesis_delta=ThesisDelta(changed=False),
        lead_horizon="ST",
    )


def sample_brief_json(session_date: dt.date) -> str:
    return sample_brief(session_date).model_dump_json()
