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

from pmb.charts.select import implemented_modules, render_chart
from pmb.config import get_settings
from pmb.data.calendar import is_trading_day
from pmb.data.fred import FredClient
from pmb.data.snapshot import build_snapshot
from pmb.data.yfinance import YFinanceClient
from pmb.orchestrator import build_review_manifest, review_summary
from pmb.publish.report import render_report
from pmb.publish.youtube import build_youtube_metadata, upload_video
from pmb.research.dedup import load_previous_brief
from pmb.research.runner import make_anthropic_caller, research_once
from pmb.research.sample import sample_brief_json
from pmb.research.script_builder import build_script_from_brief
from pmb.research.thesis import load_thesis
from pmb.schemas.brief import Brief
from pmb.schemas.chart import ChartSpec
from pmb.schemas.script import Script
from pmb.schemas.snapshot import Quote, Snapshot
from pmb.tts.edge import edge_synthesize, probe_duration, silent_synth
from pmb.video.assemble import assemble_video

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


def _load_snapshot_for_research(target: dt.date, settings, *, dry_run: bool) -> Snapshot:
    """研究用快照:優先讀 fetch 落下的 artifact;dry-run 缺檔時用最小占位(不連網)。"""
    snap_path = settings.artifacts_dir / f"snapshot_{target}.json"
    if snap_path.exists():
        return Snapshot.model_validate_json(snap_path.read_text(encoding="utf-8"))
    if dry_run:
        logger.warning("找不到 {},dry-run 用最小占位快照", snap_path)
        return Snapshot(session_date=target, generated_at=dt.datetime.now(tz=dt.UTC))
    logger.info("找不到 {},改即時取數建快照", snap_path)
    return build_snapshot(
        target,
        yf_client=YFinanceClient(),
        fred_client=FredClient(settings.fred_api_key),
        generated_at=dt.datetime.now(tz=dt.UTC),
        history_period=settings.history_period,
    )


def cmd_research(args: argparse.Namespace) -> int:
    settings = get_settings()
    settings.ensure_dirs()

    explicit = dt.date.fromisoformat(args.date) if args.date else None
    target = resolve_fetch_target(today_eastern(), explicit)
    if target is None:
        print("今天非 NYSE 交易日,skip。")
        return 0

    snapshot = _load_snapshot_for_research(target, settings, dry_run=args.dry_run)
    thesis = load_thesis(settings.state_dir / "thesis.json")
    previous_brief = load_previous_brief(settings.artifacts_dir, target)
    prompt_template = settings.prompt_path.read_text(encoding="utf-8")

    if args.dry_run:
        logger.info("dry-run:用範例 brief 跑通 pipeline,不呼叫 LLM")
        llm = lambda _prompt: sample_brief_json(target)  # noqa: E731
    else:
        if not settings.anthropic_api_key:
            print("缺少 ANTHROPIC_API_KEY,無法跑 live 研究(或用 --dry-run)。")
            return 1
        llm = make_anthropic_caller(settings.anthropic_api_key)

    brief: Brief = research_once(
        snapshot,
        thesis,
        llm=llm,
        prompt_template=prompt_template,
        previous_brief=previous_brief,
    )

    brief_path = settings.artifacts_dir / f"brief_{target}.json"
    brief_path.write_text(brief.model_dump_json(indent=2), encoding="utf-8")

    # 同一次研究的另外兩種 renderer:30 秒講稿 + 長文報告
    script = build_script_from_brief(brief)
    script_path = settings.artifacts_dir / f"script_{target}.json"
    script_path.write_text(script.model_dump_json(indent=2), encoding="utf-8")

    report_md = render_report(brief, snapshot)
    report_path = settings.artifacts_dir / f"report_{target}.md"
    report_path.write_text(report_md, encoding="utf-8")
    logger.info("產出 brief / script / report → {}", settings.artifacts_dir)

    print(f"=== brief · {brief.date}(lead_horizon={brief.lead_horizon})===")
    for item in brief.items:
        print(f"  [{item.horizon}/{item.confidence}/m{item.materiality}] {item.headline}")
        print(f"      → {item.audience_value}")
    if not brief.items:
        print("  (今日無項目)")
    print(f"\n=== script({script.total_duration:.0f}s,{len(script.segments)} 段)===")
    for seg in script.segments:
        print(f"  [{seg.t_start:>4.0f}s +{seg.duration:.0f}s · {seg.chart_id}] {seg.vo}")
    print(f"\n報告:{report_path}")
    print("※ 本內容為市場資訊與風險教育,非投資建議。")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    settings = get_settings()
    settings.ensure_dirs()

    explicit = dt.date.fromisoformat(args.date) if args.date else None
    target = resolve_fetch_target(today_eastern(), explicit)
    if target is None:
        print("今天非 NYSE 交易日,skip。")
        return 0

    snap_path = settings.artifacts_dir / f"snapshot_{target}.json"
    if not snap_path.exists():
        print(f"找不到 {snap_path},請先跑 pmb fetch --date {target}。")
        return 1
    snapshot = Snapshot.model_validate_json(snap_path.read_text(encoding="utf-8"))

    out_dir = settings.artifacts_dir / "charts"
    modules = args.module or implemented_modules()
    for module in modules:
        spec = ChartSpec(id=module, module=module)
        path = render_chart(spec, snapshot, out_dir)
        print(f"  {module:<22} → {path}")
    print(f"\n已實作模組:{', '.join(implemented_modules())}")
    return 0


def cmd_assemble(args: argparse.Namespace) -> int:
    settings = get_settings()
    settings.ensure_dirs()

    explicit = dt.date.fromisoformat(args.date) if args.date else None
    target = resolve_fetch_target(today_eastern(), explicit)
    if target is None:
        print("今天非 NYSE 交易日,skip。")
        return 0

    script_path = settings.artifacts_dir / f"script_{target}.json"
    snap_path = settings.artifacts_dir / f"snapshot_{target}.json"
    if not script_path.exists() or not snap_path.exists():
        print(f"缺 script 或 snapshot({target}),請先跑 pmb fetch 與 pmb research。")
        return 1
    script = Script.model_validate_json(script_path.read_text(encoding="utf-8"))
    snapshot = Snapshot.model_validate_json(snap_path.read_text(encoding="utf-8"))

    if args.dry_run:
        logger.info("dry-run:用靜音配音合成,不打 edge-tts")
        synth_fn = lambda vo, path, planned: silent_synth(vo, path, duration=planned)  # noqa: E731
    else:
        synth_fn = lambda vo, path, planned: edge_synthesize(vo, path)  # noqa: E731

    out_path = settings.artifacts_dir / f"video_{target}.mp4"
    work_dir = settings.artifacts_dir / f"video_{target}_work"
    assemble_video(script, snapshot, out_path, synth_fn=synth_fn, work_dir=work_dir)

    duration = probe_duration(out_path)
    print(f"影片合成完成:{out_path}({duration:.1f}s,{len(script.segments)} 段)")
    print("※ 本內容為市場資訊與風險教育,非投資建議。")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """全流程(開發用):fetch → research → assemble → 人工 gate。絕不自動發布。"""
    settings = get_settings()
    settings.ensure_dirs()
    explicit = dt.date.fromisoformat(args.date) if args.date else None
    target = resolve_fetch_target(today_eastern(), explicit)
    if target is None:
        print("今天非 NYSE 交易日,skip。")
        return 0

    date_arg = args.date or str(target)
    logger.info("pmb run:{}(dry_run={})", target, args.dry_run)
    cmd_fetch(argparse.Namespace(date=date_arg, json=False, dry_run=False))
    if cmd_research(argparse.Namespace(date=date_arg, dry_run=args.dry_run)) != 0:
        return 1
    if cmd_assemble(argparse.Namespace(date=date_arg, dry_run=args.dry_run)) != 0:
        return 1

    build_review_manifest(target, settings.artifacts_dir)
    print()
    print(review_summary(target, settings.artifacts_dir))
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    """發布(預設 dry-run / 需 --approve 放行)。報告走人工貼上,影片走 YouTube gate。"""
    settings = get_settings()
    settings.ensure_dirs()
    explicit = dt.date.fromisoformat(args.date) if args.date else None
    target = resolve_fetch_target(today_eastern(), explicit)
    if target is None:
        print("今天非 NYSE 交易日,skip。")
        return 0

    video = settings.artifacts_dir / f"video_{target}.mp4"
    brief_path = settings.artifacts_dir / f"brief_{target}.json"
    if not video.exists() or not brief_path.exists():
        print(f"缺 video 或 brief({target}),請先跑 pmb run。")
        return 1

    brief = Brief.model_validate_json(brief_path.read_text(encoding="utf-8"))
    title, description = build_youtube_metadata(brief)
    result = upload_video(
        video,
        title=title,
        description=description,
        approve=args.approve,
        manifest_path=settings.artifacts_dir / f"publish_{target}.json",
        settings=settings,
    )

    if result["published"]:
        print(f"✅ 已上傳 YouTube:{result.get('video_id')}")
    else:
        print(f"[dry-run] 未發布。標題:{title}")
        print(f"  manifest:{settings.artifacts_dir / f'publish_{target}.json'}")
        print("  要真正上傳:pmb publish --approve(需 YouTube OAuth 憑證)。")
    report_path = settings.artifacts_dir / f"report_{target}.md"
    print(f"  報告(人工貼上):{report_path}")
    print("※ 本內容為市場資訊與風險教育,非投資建議。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pmb", description="Pre-Market Macro Brief CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="組出並印出當日真實數據快照")
    fetch.add_argument("--date", help="指定交易日 YYYY-MM-DD(開發/重跑用)")
    fetch.add_argument("--json", action="store_true", help="以 JSON 輸出")
    fetch.add_argument("--dry-run", action="store_true", help="不取數,只印目標日")
    fetch.set_defaults(func=cmd_fetch)

    research = sub.add_parser("research", help="研究 + 產出 brief.json(LLM)")
    research.add_argument("--date", help="指定交易日 YYYY-MM-DD(開發/重跑用)")
    research.add_argument(
        "--dry-run", action="store_true", help="用範例 brief 跑通 pipeline,不呼叫 LLM"
    )
    research.set_defaults(func=cmd_research)

    render = sub.add_parser("render", help="依模組從快照渲染圖表 PNG")
    render.add_argument("--date", help="指定交易日 YYYY-MM-DD")
    render.add_argument(
        "--module", action="append", help="指定圖表模組(可重複);省略則渲染全部已實作模組"
    )
    render.set_defaults(func=cmd_render)

    assemble = sub.add_parser("assemble", help="配音 + 合成 30 秒影片")
    assemble.add_argument("--date", help="指定交易日 YYYY-MM-DD")
    assemble.add_argument(
        "--dry-run", action="store_true", help="用靜音配音(不打 edge-tts),只驗證合成"
    )
    assemble.set_defaults(func=cmd_assemble)

    publish = sub.add_parser("publish", help="發布(預設 dry-run;--approve 才上傳)")
    publish.add_argument("--date", help="指定交易日 YYYY-MM-DD")
    publish.add_argument("--approve", action="store_true", help="人工放行:實際上傳 YouTube")
    publish.set_defaults(func=cmd_publish)

    run = sub.add_parser("run", help="全流程 fetch→research→assemble→gate(不自動發布)")
    run.add_argument("--date", help="指定交易日 YYYY-MM-DD")
    run.add_argument("--dry-run", action="store_true", help="研究用範例、配音用靜音(不打 LLM/TTS)")
    run.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
