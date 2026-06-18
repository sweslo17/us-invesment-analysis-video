"""pmb CLI 入口。

批次 pipeline 的命令列介面。Phase 0 提供 ``fetch``(組出並印出當日真實數據快照);
其餘子命令(research / render / assemble / publish / run)於後續階段加入。
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections.abc import Callable
from zoneinfo import ZoneInfo

from loguru import logger

from pmb.config import get_settings
from pmb.data.calendar import is_trading_day
from pmb.data.fred import FredClient
from pmb.data.snapshot import build_snapshot
from pmb.data.yfinance import YFinanceClient
from pmb.schemas.snapshot import Quote, Snapshot

_EASTERN = ZoneInfo("America/New_York")


def today_eastern() -> dt.date:
    """美東當前日期(市場時區)。"""
    return dt.datetime.now(tz=_EASTERN).date()


def resolve_fetch_target(today: dt.date, explicit_date: dt.date | None) -> dt.date | None:
    """決定要 fetch 的交易日。

    - 指定 ``explicit_date``:直接採用(開發 / 重跑用,不檢查休市)。
    - 否則:今天開市回今天;休市回 None(代表整條 skip)。
    """
    if explicit_date is not None:
        return explicit_date
    return today if is_trading_day(today) else None


def _opt(value: float | None, fmt: Callable[[float], str]) -> str:
    """格式化可能為 None 的數值;None 顯示 n/a。"""
    return fmt(value) if value is not None else "n/a"


def _fmt_quote(quote: Quote | None) -> str:
    if quote is None:
        return "  (無資料)"
    change = quote.change_pct
    change_str = f"{change:+.2f}%" if change is not None else "n/a"
    label = quote.name or quote.ticker
    return f"  {quote.ticker:<10} {label:<18} {quote.last:>12,.2f}  ({change_str})"


def format_snapshot(snapshot: Snapshot) -> str:
    """把快照組成人類可讀的文字摘要。"""
    lines: list[str] = []
    lines.append(f"=== PMB 市場快照 · {snapshot.session_date} ===")
    lines.append(f"產生時間 (UTC): {snapshot.generated_at.isoformat()}")

    lines.append("\n[指數期貨]")
    lines.extend(_fmt_quote(q) for q in snapshot.futures)

    lines.append("\n[指數現貨]")
    lines.extend(_fmt_quote(q) for q in snapshot.indices)

    lines.append("\n[波動率 / 利率 / 美元]")
    lines.append(_fmt_quote(snapshot.volatility))
    lines.append(_fmt_quote(snapshot.treasury_10y))
    lines.append(_fmt_quote(snapshot.dollar_index))

    lines.append("\n[槓桿載具 — 風險教育用,非投資建議]")
    lines.extend(_fmt_quote(q) for q in snapshot.leverage)

    lines.append("\n[總經 (FRED)]")
    if snapshot.macro:
        for obs in snapshot.macro:
            unit = f" {obs.units}" if obs.units else ""
            lines.append(
                f"  {obs.series_id:<10} {obs.label:<18} "
                f"{obs.value:>12,.3f}{unit}  @{obs.date}"
            )
    else:
        lines.append("  (無資料 — 是否缺 FRED_API_KEY?)")

    def pct(v: float) -> str:
        return f"{v * 100:.0f}%"

    r = snapshot.regime
    lines.append("\n[市場 regime — 數值]")
    lines.append(f"  VIX                : {_opt(r.vix, lambda v: f'{v:.2f}')}")
    lines.append(f"  已實現波動(20d年化): {_opt(r.realized_vol_20d, lambda v: f'{v * 100:.1f}%')}")
    lines.append(f"  股債相關(20d)      : {_opt(r.stock_bond_corr_20d, lambda v: f'{v:+.2f}')}")
    lines.append(f"  廣度(>50日均線)    : {_opt(r.breadth_pct_above_ma50, pct)}")
    lines.append(f"  廣度(當日上漲)     : {_opt(r.breadth_pct_positive, pct)}")

    lines.append("\n※ 本內容為市場資訊與風險教育,非投資建議。")
    return "\n".join(lines)


def cmd_fetch(args: argparse.Namespace) -> int:
    settings = get_settings()
    settings.ensure_dirs()

    explicit = dt.date.fromisoformat(args.date) if args.date else None
    target = resolve_fetch_target(today_eastern(), explicit)
    if target is None:
        logger.info("今天非 NYSE 交易日,skip。")
        print("今天非 NYSE 交易日,skip。")
        return 0

    if args.dry_run:
        logger.info("dry-run:目標交易日 {},不取數。", target)
        print(f"[dry-run] 將為交易日 {target} 組裝快照(未實際取數)。")
        return 0

    yf_client = YFinanceClient()
    fred_client = FredClient(settings.fred_api_key)
    generated_at = dt.datetime.now(tz=dt.UTC)
    snapshot = build_snapshot(
        target,
        yf_client=yf_client,
        fred_client=fred_client,
        generated_at=generated_at,
        history_period=settings.history_period,
    )

    if args.json:
        print(snapshot.model_dump_json(indent=2))
    else:
        print(format_snapshot(snapshot))

    out_path = settings.artifacts_dir / f"snapshot_{target}.json"
    out_path.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
    logger.info("快照已寫入 {}", out_path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pmb", description="Pre-Market Macro Brief CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="組出並印出當日真實數據快照")
    fetch.add_argument("--date", help="指定交易日 YYYY-MM-DD(開發/重跑用)")
    fetch.add_argument("--json", action="store_true", help="以 JSON 輸出")
    fetch.add_argument("--dry-run", action="store_true", help="不取數,只印目標日")
    fetch.set_defaults(func=cmd_fetch)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
