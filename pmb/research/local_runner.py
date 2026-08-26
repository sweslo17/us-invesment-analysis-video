"""本機研究 runner:headless Claude Code(``claude -p``)跑同一份研究 prompt。

雲端 routine 的純本地替代/備援:用本機 Claude Code 的登入(免 API key)、內建
web search,研究產物直接寫進 artifacts/;寫完由這裡以 pydantic 驗證,不過就帶著
錯誤訊息重試。機器反正要開著做合成,研究也在本機跑就完全不依賴雲端 GitHub 權限。
"""

from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from zoneinfo import ZoneInfo

from loguru import logger
from pydantic import ValidationError

from pmb.research.dedup import load_previous_brief
from pmb.research.runner import build_research_prompt
from pmb.research.thesis import load_thesis
from pmb.schemas.brief import Brief
from pmb.schemas.script import Script
from pmb.schemas.snapshot import Snapshot

# invoke(prompt) -> None:把 prompt 丟給 agent 執行,產物以「寫檔」為副作用(可注入供測試)
InvokeFn = Callable[[str], None]

_HEADLESS_TIMEOUT_MIN = 35.0
# 額度上限有明確恢復時間,等到重置再試才有意義(2026-08-26:19:46 撞牆、20:00 重置,
# 卻在 6 秒內把兩次重試燒完,整天沒產出)。等待上限要趕得上美股開盤前出片。
_MAX_RATE_LIMIT_WAIT_MIN = 75.0
_RATE_LIMIT_BUFFER_SEC = 90.0  # 重置時間常是整點近似值,多等一點再敲
_MAX_RATE_LIMIT_WAITS = 2
_DEFAULT_RATE_LIMIT_WAIT_SEC = 20 * 60.0  # 訊息沒給重置時間時的保守等待
_RATE_LIMIT_MARKERS = (
    "session limit",
    "usage limit",
    "limit reached",
    "rate limit",
    "rate_limit",
)
# 成片長度 ≈ 總字數 × SEC_PER_CHAR(實測:0.168–0.171,取 0.17)。Shorts 上限 180s,
# 留餘裕取 1000 字(≈170s)為硬上限;prompt 給的目標是 850–930 字。
SEC_PER_CHAR = 0.17
SHORTS_CAP_SEC = 180.0
MAX_VO_CHARS = 1000
# 研究只需要:搜尋 + 讀寫 repo 檔案 + 跑 schema 驗證;不給其他 Bash
_ALLOWED_TOOLS = [
    "WebSearch",
    "WebFetch",
    "Read",
    "Glob",
    "Grep",
    "Write",
    "Edit",
    "Bash(poetry run:*)",
]


class RateLimitedError(RuntimeError):
    """headless agent 撞到額度上限;``reset_at`` 是解析出的重置時間(可能為 None)。

    與一般執行失敗分開,因為處置方式完全不同:一般失敗值得馬上重試,額度上限馬上
    重試必然再撞,要等到重置。
    """

    def __init__(self, message: str, reset_at: dt.datetime | None = None) -> None:
        super().__init__(message)
        self.reset_at = reset_at


def parse_reset_at(text: str, now: dt.datetime | None = None) -> dt.datetime | None:
    """從額度訊息裡解析重置時間,如 ``resets 8pm (Asia/Taipei)`` → 今天 20:00 台北。

    解析不出來回 None(呼叫端改用保守的預設等待,不要因為格式變了就整天不出片)。
    """
    now = now or dt.datetime.now().astimezone()
    m = re.search(r"resets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text, re.I)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    meridiem = (m.group(3) or "").lower()
    if meridiem == "pm" and hour < 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23):
        return None
    tz_match = re.search(r"\(([A-Za-z]+/[A-Za-z_]+)\)", text)
    tz = now.tzinfo
    if tz_match:
        try:
            tz = ZoneInfo(tz_match.group(1))
        except Exception:  # noqa: BLE001 — 未知時區就退回本地時區
            pass
    local_now = now.astimezone(tz)
    reset = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if reset <= local_now:  # 已過 → 指的是明天同一時刻
        reset += dt.timedelta(days=1)
    return reset


def invoke_headless_claude(
    prompt: str, cwd: Path, model: str | None = None, oauth_token: str | None = None
) -> None:
    """以 headless Claude Code 執行研究 prompt(用本機登入,不需 ANTHROPIC_API_KEY)。

    ``model`` 指定 ``--model``(如 claude-sonnet-5);None 用 CLI 預設。預設模型(Fable 5)
    額度較易用罄,滿了會 rc=1、研究直接失敗,故建議在 settings 指定額度餘裕的模型。
    ``oauth_token`` 注入子行程的 CLAUDE_CODE_OAUTH_TOKEN——launchd 那條乾淨 shell 沒有
    互動登入,一般 OAuth session 會過期,長效 token 才穩(2026-07-22 因 session 過期斷線)。
    """
    cmd = ["claude", "-p"]
    if model:
        cmd += ["--model", model]
    cmd += ["--permission-mode", "acceptEdits", "--allowedTools", *_ALLOWED_TOOLS]
    env = os.environ.copy()
    if oauth_token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token
    logger.info("headless claude 研究開始(上限 {:.0f} 分鐘)…", _HEADLESS_TIMEOUT_MIN)
    proc = subprocess.run(
        cmd,
        input=prompt,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=_HEADLESS_TIMEOUT_MIN * 60,
        env=env,
    )
    if proc.returncode != 0:
        # 額度/API 錯誤是印在 stdout 的,只看 stderr 會得到一行空白錯誤(2026-08-26
        # 查因得去翻 session transcript 才知道是撞額度)。兩邊都帶上。
        combined = f"{proc.stdout.strip()}\n{proc.stderr.strip()}".strip()
        detail = combined[-600:] or "(無輸出)"
        if any(marker in combined.lower() for marker in _RATE_LIMIT_MARKERS):
            raise RateLimitedError(
                f"claude -p 撞到額度上限(rc={proc.returncode}):{detail}",
                reset_at=parse_reset_at(combined),
            )
        raise RuntimeError(f"claude -p 失敗(rc={proc.returncode}):{detail}")
    tail = proc.stdout.strip()[-300:]
    logger.info("headless claude 完成:…{}", tail)


def validate_research_artifacts(
    artifacts_dir: Path, target: dt.date, *, include_budget: bool = True
) -> list[str]:
    """驗證研究產物,回傳錯誤清單(空 = 通過)。

    檢查:brief/script 過 schema、report 非空、**講稿字數在預算內**(超標會讓成片
    超過 Shorts 上限,必須在配音前擋下並讓 agent 重寫)。

    ``include_budget=False`` 只回「硬錯」(缺檔/schema 壞),用來區分「不能出片」與
    「字數超標但仍可出片(只是失去 Shorts 資格)」。
    """
    errors: list[str] = []
    brief_path = artifacts_dir / f"brief_{target}.json"
    script_path = artifacts_dir / f"script_{target}.json"
    report_path = artifacts_dir / f"report_{target}.md"
    script: Script | None = None
    for path, model in ((brief_path, Brief), (script_path, Script)):
        if not path.exists():
            errors.append(f"缺 {path.name}")
            continue
        try:
            parsed = model.model_validate_json(path.read_text(encoding="utf-8"))
            if model is Script:
                script = parsed
        except (ValidationError, ValueError) as exc:
            errors.append(f"{path.name} 未過 schema:{str(exc)[:600]}")
    if script is not None and include_budget:
        errors.extend(check_vo_budget(script))
    if not report_path.exists() or len(report_path.read_text(encoding="utf-8")) < 200:
        errors.append(f"缺 {report_path.name} 或內容過短")
    return errors


def check_vo_budget(script: Script) -> list[str]:
    """檢查講稿總字數是否會讓成片超過 Shorts 上限;超標回傳可據以重寫的錯誤訊息。

    成片長度 ≈ 總字數 × ``SEC_PER_CHAR``(實測校準:866字→145s、916→156、908→155、
    1203→197,穩定在 0.17 秒/字)。字數是配音前唯一可控的槓桿,故在此強制。
    """
    total = sum(len(seg.vo) for seg in script.segments)
    if total <= MAX_VO_CHARS:
        return []
    est = total * SEC_PER_CHAR
    return [
        f"講稿字數超標:{total} 字(上限 {MAX_VO_CHARS} 字),預估成片 {est:.0f} 秒 "
        f"會超過 YouTube Shorts 的 {SHORTS_CAP_SEC:.0f} 秒上限、失去 Shorts 資格。"
        f"請砍到 {MAX_VO_CHARS} 字以內(目標 850–930):刪掉次要段落或把每段講得更精簡,"
        f"不要只是刪句尾;保留貫穿主軸與數字精準度。"
    ]


def rate_limit_wait_seconds(exc: RateLimitedError, now: dt.datetime) -> float | None:
    """撞額度後該睡多久;None = 重置太晚、趕不上出片,別傻等。"""
    if exc.reset_at is None:
        return _DEFAULT_RATE_LIMIT_WAIT_SEC
    wait = (exc.reset_at - now).total_seconds() + _RATE_LIMIT_BUFFER_SEC
    if wait > _MAX_RATE_LIMIT_WAIT_MIN * 60:
        return None
    return max(wait, _RATE_LIMIT_BUFFER_SEC)


def run_local_research(
    target: dt.date,
    settings,
    *,
    invoke: InvokeFn | None = None,
    max_attempts: int = 2,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], dt.datetime] | None = None,
) -> bool:
    """本機跑一次完整研究(組 prompt → headless agent 寫檔 → 驗證,失敗帶錯誤重試)。

    呼叫端需先確保 ``snapshot_<target>.json`` 已存在(缺就先 ``pmb fetch``)。
    成功回 True;用盡重試回 False(不拋例外,交由呼叫端通知)。

    撞到額度上限(``RateLimitedError``)不算一次產物重試:那不是「寫壞了」,而是根本
    沒跑到,馬上重試必然再撞。改成睡到重置後再敲同一次嘗試,最多 ``_MAX_RATE_LIMIT_WAITS``
    次;重置晚到趕不上出片就放棄。
    """
    now = now or (lambda: dt.datetime.now(tz=dt.UTC))
    if invoke is None:
        cwd = Path(__file__).resolve().parent.parent.parent
        model = getattr(settings, "research_claude_model", "") or None
        token = getattr(settings, "claude_code_oauth_token", None) or None
        invoke = lambda p: invoke_headless_claude(  # noqa: E731
            p, cwd, model=model, oauth_token=token
        )

    snap_path = settings.artifacts_dir / f"snapshot_{target}.json"
    snapshot = Snapshot.model_validate_json(snap_path.read_text(encoding="utf-8"))
    thesis = load_thesis(settings.state_dir / "thesis.json")
    previous_brief = load_previous_brief(settings.artifacts_dir, target)
    template = settings.prompt_path.read_text(encoding="utf-8")
    base_prompt = build_research_prompt(
        snapshot, thesis, template, previous_brief, output_mode="files"
    )

    last_errors: list[str] = []
    attempt = 0
    rate_limit_waits = 0
    while attempt < max_attempts:
        prompt = base_prompt
        if last_errors:
            prompt += (
                f"\n\n【第 {attempt + 1} 次嘗試】前次產物未通過驗證,請修正後重寫檔案:\n"
                + "\n".join(f"- {e}" for e in last_errors)
            )
        try:
            invoke(prompt)
        except RateLimitedError as exc:
            wait = rate_limit_wait_seconds(exc, now())
            if wait is None or rate_limit_waits >= _MAX_RATE_LIMIT_WAITS:
                logger.error(
                    "撞到額度上限且等不到重置(已等 {} 次,重置 {}),放棄本機研究:{}",
                    rate_limit_waits,
                    exc.reset_at,
                    exc,
                )
                break
            rate_limit_waits += 1
            logger.warning(
                "撞到額度上限(重置 {}),等 {:.0f} 分鐘後重試第 {} 次嘗試:{}",
                exc.reset_at,
                wait / 60,
                attempt + 1,
                exc,
            )
            sleep(wait)
            continue  # 額度上限不吃產物重試次數
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            attempt += 1
            logger.warning("本機研究第 {}/{} 次執行失敗:{}", attempt, max_attempts, exc)
            last_errors = [f"agent 執行失敗:{exc}"]
            continue
        attempt += 1
        last_errors = validate_research_artifacts(settings.artifacts_dir, target)
        if not last_errors:
            logger.info("本機研究完成並通過驗證({})", target)
            return True
        logger.warning(
            "本機研究第 {}/{} 次驗證失敗:{}", attempt, max_attempts, "; ".join(last_errors)
        )

    # 重試用盡:若只剩「字數超標」這類軟錯(產物本身合法),寧可出非 Shorts 的長片,
    # 也不要整天沒影片;硬錯(缺檔/schema 壞)才真的放棄。
    hard_errors = validate_research_artifacts(settings.artifacts_dir, target, include_budget=False)
    if not hard_errors:
        logger.warning(
            "字數仍超標但產物合法,以「超長片」繼續({})——成片會超過 {:.0f}s、"
            "失去 Shorts 資格,發布前請自行斟酌",
            target,
            SHORTS_CAP_SEC,
        )
        return True
    return False
