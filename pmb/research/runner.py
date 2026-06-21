"""研究 runner——組 prompt、呼叫 LLM、驗證輸出、失敗重試。

LLM 以可注入的 ``llm(prompt) -> str`` 介面提供(provider-agnostic):
- 正式部署的研究在 Claude Code 雲端 routine 跑同一份 prompt(不經此 caller)。
- 本機開發/測試用 ``make_anthropic_caller`` 跑 Anthropic API(需 ANTHROPIC_API_KEY)。
- 單元測試注入假 llm,驗證解析/驗證/重試邏輯,不打外部。

輸出一律過 brief schema 驗證,失敗自動重試(規格鐵則)。
"""

from __future__ import annotations

import re
from collections.abc import Callable

from loguru import logger
from pydantic import ValidationError

from pmb.research.dedup import dedup_items
from pmb.research.thesis import Thesis
from pmb.schemas.brief import Brief
from pmb.schemas.snapshot import Snapshot

LLMCaller = Callable[[str], str]

DEFAULT_MODEL = "claude-opus-4-8"

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def build_research_prompt(
    snapshot: Snapshot,
    thesis: Thesis,
    prompt_template: str,
    previous_brief: Brief | None = None,
    *,
    output_mode: str = "json",
) -> str:
    """把研究 prompt 模板 + 真實數據快照 + thesis(+ 昨日 brief)組成完整 prompt。

    數字只來自快照,LLM 不得編造。
    ``output_mode="json"``(預設,給 API runner 解析)要求只輸出單一 brief JSON;
    ``output_mode="files"``(給本機 Claude Code agent)要求把產物寫成檔案。
    """
    cur = snapshot.session_date
    prev = snapshot.previous_session_date
    window = "\n=== 研究涵蓋窗(重要)==="
    if prev is not None:
        gap = (cur - prev).days
        window += f"\n從上一個交易日 {prev}(收盤)到今天 {cur}(盤前),共約 {gap} 天。"
        if gap > 1:
            window += (
                f"\n⚠️ 這是假期/週末後的第一個交易日:要涵蓋這 {gap} 天內的"
                "全球事件與市場變化,不是只看前一日。"
            )
    window += (
        "\n搜尋與研判涵蓋自上一交易日收盤以來的整段;重大事件影響常跨多日,"
        "把仍在發酵的近期重大事件也納入,別只截取當天,以免失真。"
    )
    parts = [
        prompt_template,
        window,
        "\n=== 今日真實數據快照(只能引用,不可編造)===",
        snapshot.model_dump_json(indent=2),
        "\n=== 當前 thesis(市場中長期基準情境)===",
        thesis.model_dump_json(indent=2),
    ]
    if previous_brief is not None:
        parts.append("\n=== 昨日 brief(短期去重 / 中長期 open threads 參考)===")
        parts.append(previous_brief.model_dump_json(indent=2))
    if output_mode == "files":
        date = snapshot.session_date.isoformat()
        parts.append(
            "\n【本機輸出 — 請把結果寫成檔案,不要只印在對話裡】\n"
            f"完成研究後,把產物寫到專案目錄(日期 = {date}):\n"
            f"- artifacts/brief_{date}.json — 過 Brief schema(pmb/schemas/brief.py)\n"
            f"- artifacts/script_{date}.json — 過 Script schema"
            "(每段 chart_id 對得上 charts[].id;模組限 8 個固定模組)\n"
            f"- artifacts/report_{date}.md — 面向一般讀者的長文\n"
            "- 有重大且夠確認的變化才保守更新 state/thesis.json;否則不動\n"
            "寫完用 pmb/schemas 驗證(載入 Brief / Script 做 model_validate_json),不過就修正重寫。\n"
            "不要執行 pmb assemble 或 pmb publish(那是後續本機步驟)。"
        )
    else:
        parts.append("\n請嚴格依 brief schema 輸出單一 JSON 物件,不要加任何說明文字。")
    return "\n".join(parts)


def extract_json(raw: str) -> str:
    """從 LLM 原始輸出抽出 JSON 字串(去掉 markdown fence 與前後文字)。"""
    text = raw.strip()
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    return text


def parse_and_validate_brief(raw: str) -> Brief:
    """擷取 JSON 並以 brief schema 驗證(失敗拋 ValidationError)。"""
    return Brief.model_validate_json(extract_json(raw))


def run_research(
    snapshot: Snapshot,
    thesis: Thesis,
    *,
    llm: LLMCaller,
    prompt_template: str,
    previous_brief: Brief | None = None,
    max_attempts: int = 3,
) -> Brief:
    """跑研究並回傳通過驗證的 ``Brief``;驗證失敗自動重試,用盡後拋出。"""
    base_prompt = build_research_prompt(snapshot, thesis, prompt_template, previous_brief)
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        prompt = base_prompt
        if attempt > 1:
            prompt += f"\n\n(第 {attempt} 次嘗試:前次輸出未通過 schema 驗證,請只輸出合法 JSON。)"
        raw = llm(prompt)
        try:
            return parse_and_validate_brief(raw)
        except ValidationError as exc:
            last_exc = exc
            logger.warning("研究輸出第 {}/{} 次驗證失敗:{}", attempt, max_attempts, exc)
    assert last_exc is not None
    raise last_exc


def research_once(
    snapshot: Snapshot,
    thesis: Thesis,
    *,
    llm: LLMCaller,
    prompt_template: str,
    previous_brief: Brief | None = None,
    max_attempts: int = 3,
) -> Brief:
    """跑一次研究並套用 horizon-aware 去重(對昨日 brief),回傳最終 ``Brief``。"""
    brief = run_research(
        snapshot,
        thesis,
        llm=llm,
        prompt_template=prompt_template,
        previous_brief=previous_brief,
        max_attempts=max_attempts,
    )
    previous_items = previous_brief.items if previous_brief else []
    brief.items = dedup_items(brief.items, previous_items)
    return brief


def make_anthropic_caller(
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 16000,
) -> LLMCaller:
    """本機開發/測試用的 Anthropic API caller(需 ANTHROPIC_API_KEY)。

    用 Opus 4.8 + adaptive thinking + 串流取最終訊息。正式日更走 Claude Code 雲端
    routine,不經此函式。
    """

    def call(prompt: str) -> str:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            system="你是盤前市場研究助理。嚴格只輸出單一合法 JSON 物件,符合指定 brief schema。",
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            message = stream.get_final_message()
        return "\n".join(block.text for block in message.content if block.type == "text")

    return call
