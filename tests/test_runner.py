"""研究 runner 測試:prompt 組裝、JSON 擷取/驗證、失敗重試(用假 LLM,不打外部)。"""

import datetime as dt

import pytest
from pydantic import ValidationError

from pmb.research.runner import (
    build_research_prompt,
    extract_json,
    parse_and_validate_brief,
    research_once,
    run_research,
)
from pmb.research.thesis import Thesis
from pmb.schemas.brief import Brief, BriefItem
from pmb.schemas.snapshot import Snapshot


def _valid_brief_json() -> str:
    return (
        '{"date":"2026-06-18",'
        '"regime":{"vol":"normal","rates":"stable","stock_bond_corr":"neutral","breadth":"mixed"},'
        '"items":[{"headline":"x","horizon":"ST","vs_thesis":"confirms","materiality":2,'
        '"confidence":"developing","audience_value":"y"}],'
        '"thesis_delta":{"changed":false},"lead_horizon":"ST"}'
    )


def _snapshot() -> Snapshot:
    return Snapshot(
        session_date=dt.date(2026, 6, 18),
        generated_at=dt.datetime(2026, 6, 18, 11, 0, tzinfo=dt.UTC),
    )


def _make_fake_llm(responses: list[str]):
    state = {"n": 0}

    def llm(prompt: str) -> str:
        idx = state["n"]
        state["n"] += 1
        return responses[idx]

    return llm, state


def test_extract_json_handles_plain_json():
    assert extract_json('{"a": 1}') == '{"a": 1}'


def test_extract_json_strips_markdown_fence_and_prose():
    raw = '好的,以下是輸出:\n```json\n{"a": 1}\n```\n謝謝'
    assert extract_json(raw) == '{"a": 1}'


def test_parse_and_validate_brief_accepts_fenced_output():
    raw = f"```json\n{_valid_brief_json()}\n```"
    brief = parse_and_validate_brief(raw)
    assert brief.date == dt.date(2026, 6, 18)


def test_parse_and_validate_brief_rejects_garbage():
    with pytest.raises(ValidationError):
        parse_and_validate_brief("這不是 JSON")


def test_run_research_returns_brief_on_first_success():
    llm, state = _make_fake_llm([_valid_brief_json()])
    brief = run_research(_snapshot(), Thesis(), llm=llm, prompt_template="T")
    assert brief.lead_horizon == "ST"
    assert state["n"] == 1


def test_run_research_retries_until_valid():
    llm, state = _make_fake_llm(["bad", "{still bad}", _valid_brief_json()])
    brief = run_research(_snapshot(), Thesis(), llm=llm, prompt_template="T", max_attempts=3)
    assert brief.date == dt.date(2026, 6, 18)
    assert state["n"] == 3


def test_run_research_raises_after_max_attempts():
    llm, state = _make_fake_llm(["bad", "bad", "bad"])
    with pytest.raises(ValidationError):
        run_research(_snapshot(), Thesis(), llm=llm, prompt_template="T", max_attempts=3)
    assert state["n"] == 3


def _brief_with_items(*items: BriefItem) -> Brief:
    return Brief.model_validate(
        {
            "date": "2026-06-17",
            "regime": {
                "vol": "normal",
                "rates": "stable",
                "stock_bond_corr": "neutral",
                "breadth": "mixed",
            },
            "thesis_delta": {"changed": False},
            "lead_horizon": "ST",
            "items": [i.model_dump() for i in items],
        }
    )


def _item(headline: str, horizon: str) -> BriefItem:
    return BriefItem(
        headline=headline,
        horizon=horizon,
        vs_thesis="confirms",
        materiality=2,
        confidence="developing",
        audience_value="...",
    )


def test_research_once_dedups_short_term_against_previous_brief():
    today_json = _brief_with_items(_item("Fed 維持", "ST"), _item("新題材", "ST")).model_dump_json()
    llm, _ = _make_fake_llm([today_json])
    previous = _brief_with_items(_item("Fed 維持", "ST"))

    brief = research_once(
        _snapshot(), Thesis(), llm=llm, prompt_template="T", previous_brief=previous
    )

    assert [i.headline for i in brief.items] == ["新題材"]  # 重複的短期項被去掉


def test_build_research_prompt_embeds_template_snapshot_and_thesis():
    prompt = build_research_prompt(
        _snapshot(),
        Thesis(summary="基準情境ABC"),
        prompt_template="<<RESEARCH TEMPLATE>>",
    )
    assert "<<RESEARCH TEMPLATE>>" in prompt
    assert "2026-06-18" in prompt  # 快照真實數據入 prompt
    assert "基準情境ABC" in prompt  # thesis 入 prompt


def test_build_research_prompt_holiday_gap_widens_coverage_window():
    # 6/22(週一)的上一交易日是 6/18(跨 Juneteenth + 週末)→ 4 天,要提醒涵蓋整段
    snap = Snapshot(
        session_date=dt.date(2026, 6, 22),
        previous_session_date=dt.date(2026, 6, 18),
        generated_at=dt.datetime(2026, 6, 22, 11, 0, tzinfo=dt.UTC),
    )
    prompt = build_research_prompt(snap, Thesis(), prompt_template="T")
    assert "研究涵蓋窗" in prompt
    assert "2026-06-18" in prompt and "共約 4 天" in prompt
    assert "假期/週末後的第一個交易日" in prompt


def test_build_research_prompt_files_mode_instructs_writing_artifacts():
    prompt = build_research_prompt(
        _snapshot(), Thesis(), prompt_template="T", output_mode="files"
    )
    assert "artifacts/brief_2026-06-18.json" in prompt
    assert "不要執行 pmb assemble 或 pmb publish" in prompt
