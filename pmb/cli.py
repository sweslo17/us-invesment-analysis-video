"""pmb CLI 入口。

批次 pipeline 的命令列介面。Phase 0 提供 ``fetch``(組出並印出當日真實數據快照);
其餘子命令(research / render / assemble / publish / run)於後續階段加入。
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections.abc import Callable
from pathlib import Path
from zoneinfo import ZoneInfo

from loguru import logger

from pmb.charts.select import implemented_modules, render_chart
from pmb.config import get_settings
from pmb.data.calendar import is_trading_day, next_trading_day
from pmb.data.fred import FredClient
from pmb.data.snapshot import build_snapshot
from pmb.data.yfinance import YFinanceClient
from pmb.orchestrator import build_review_manifest, review_summary
from pmb.publish.report import render_report
from pmb.publish.youtube import build_youtube_metadata, upload_video
from pmb.research.dedup import load_previous_brief
from pmb.research.runner import build_research_prompt, make_anthropic_caller, research_once
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
    script = build_script_from_brief(brief, thesis=thesis, channel_name=settings.channel_name)
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


def _resolve_bgm(settings, target: dt.date, work_dir: Path) -> Path | None:
    """挑 BGM:assets/bgm 有音檔就按日輪播;沒有就程序化合成預設 pad;停用回 None。"""
    if not settings.bgm_enable:
        return None
    exts = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg"}
    files = (
        sorted(p for p in settings.bgm_dir.iterdir() if p.suffix.lower() in exts)
        if settings.bgm_dir.is_dir()
        else []
    )
    if files:
        return files[target.toordinal() % len(files)]
    from pmb.audio.bgm import generate_default_pad

    return generate_default_pad(work_dir / "bgm_pad.wav")


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
        logger.info("dry-run:用靜音配音合成,不打 edge-tts;跳過 BGM/響度母帶")
        synth_fn = lambda vo, path, planned: silent_synth(vo, path, duration=planned)  # noqa: E731
    else:
        rate, voice, pitch = settings.tts_rate, settings.tts_voice, settings.tts_pitch
        synth_fn = lambda vo, path, planned: edge_synthesize(  # noqa: E731
            vo, path, voice=voice, rate=rate, pitch=pitch
        )

    out_path = settings.artifacts_dir / f"video_{target}.mp4"
    work_dir = settings.artifacts_dir / f"video_{target}_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    bgm_path = None if args.dry_run else _resolve_bgm(settings, target, work_dir)
    assemble_video(
        script,
        snapshot,
        out_path,
        synth_fn=synth_fn,
        work_dir=work_dir,
        font=settings.video_font,
        channel_name=settings.channel_name,
        bgm_path=bgm_path,
        bgm_gain_db=settings.bgm_gain_db,
        master_audio=not args.dry_run,
    )

    duration = probe_duration(out_path)
    print(f"影片合成完成:{out_path}({duration:.1f}s,{len(script.segments)} 段)")
    print("※ 本內容為市場資訊與風險教育,非投資建議。")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """全流程:fetch → research → assemble → gate。

    預設停在 gate(不上傳)。加 ``--approve`` 則跑完直接上傳 YouTube(以 ``private``,
    絕不自動公開)——人工只需到 Studio 改成公開。
    """
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

    if getattr(args, "approve", False):
        print()
        return cmd_publish(argparse.Namespace(date=date_arg, approve=True))
    return 0


def _render_cover(target, settings) -> Path | None:
    """用講稿的開場鉤子卡產出封面圖(Shorts 首幀同款),回傳路徑;無講稿則 None。"""
    from pmb.charts.cards import accent_for, render_headline_card
    from pmb.schemas.script import Script

    script_path = settings.artifacts_dir / f"script_{target}.json"
    if not script_path.exists():
        return None
    script = Script.model_validate_json(script_path.read_text(encoding="utf-8"))
    for idx, seg in enumerate(script.segments):
        if seg.headline:
            cover = settings.artifacts_dir / f"cover_{target}.png"
            render_headline_card(
                str(cover),
                seg.headline,
                accent=accent_for(idx),
                tag=seg.tag or settings.channel_name,
            )
            return cover
    return None


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
    title, description, tags = build_youtube_metadata(brief, channel_name=settings.channel_name)
    cover = _render_cover(target, settings)

    approve = args.approve
    # dry-run 範例內容(headline 帶「dry-run」標記):只警告、不擋上傳
    if approve and ("dry-run" in title or any("dry-run" in it.headline for it in brief.items)):
        print("⚠️ 偵測到 dry-run 範例內容(含「dry-run」字樣),確認這是要發布的真內容嗎?")
        print("   真內容請用 pmb research(接 LLM)或雲端 routine 產出。")
    # --approve 但沒憑證時,優雅退回 dry-run(排程不會炸),並提示如何取得憑證
    if approve and not settings.youtube_refresh_token:
        approve = False
        print("⚠️ 指定 --approve 但缺 YouTube OAuth 憑證,退回 dry-run。")
        print("   先跑一次:pmb auth-youtube --client-secrets <桌面用戶端.json>")

    result = upload_video(
        video,
        title=title,
        description=description,
        tags=tags,
        thumbnail=cover,
        privacy=settings.youtube_privacy,
        approve=approve,
        manifest_path=settings.artifacts_dir / f"publish_{target}.json",
        settings=settings,
        disclose_synthetic=settings.youtube_disclose_synthetic,
        playlist_id=settings.youtube_playlist_id,
    )

    if result["published"]:
        print(f"✅ 已上傳 YouTube(可見度 {settings.youtube_privacy}):{result.get('video_id')}")
        ch = result.get("channel_title") or result.get("channel_id") or "(未知)"
        print(f"   📺 上傳到頻道:{ch} — 確認是「美股早發車」!")
        disclosed = "已揭露" if settings.youtube_disclose_synthetic else "未揭露(依設定)"
        print(f"   🏷️ 合成內容(TTS):{disclosed};語言 zh-TW;非兒童內容 —— 已由 API 設定")
        if settings.youtube_playlist_id:
            mark = "✓ 已加入" if result.get("playlist_added") else "✗ 失敗(見 log,不擋上傳)"
            print(f"   🎞️ 播放清單:{mark}")
        else:
            print("   🎞️ 播放清單:未設定(在 .env 填 YOUTUBE_PLAYLIST_ID 可自動加入)")
        print("   → 剩最後一步:到 YouTube Studio 看片確認,改成『公開』。")
    else:
        print(f"[dry-run] 未發布。標題:{title}")
        print(f"  manifest:{settings.artifacts_dir / f'publish_{target}.json'}")
        print("  要真正上傳:pmb publish --approve(需 YouTube OAuth 憑證)。")
    print(f"  tags:{'、'.join(tags)}")
    if cover:
        print(f"  封面:{cover}")
    report_path = settings.artifacts_dir / f"report_{target}.md"
    print(f"  報告(人工貼上):{report_path}")
    print("※ 本內容為市場資訊與風險教育,非投資建議。")
    return 0


def today_blockers(artifacts_dir: Path, target: str) -> list[str]:
    """一鍵作業的前置檢查:回傳缺少的前置產物標籤(空 = 可執行)。

    合成/發佈是本機步驟,但需要「取數(snapshot)」與「研究(brief + 講稿)」先完成。
    """
    need = [
        ("snapshot", "取數"),
        ("brief", "研究(brief)"),
        ("script", "研究(講稿)"),
    ]
    return [
        label for kind, label in need if not (artifacts_dir / f"{kind}_{target}.json").exists()
    ]


def cmd_today(args: argparse.Namespace) -> int:
    """一鍵完成今日本機作業:合成 → 發佈。前置(取數+研究)缺則中止、不執行。

    供桌面控台一鍵與之後 cron 共用。預設上傳(private);``--no-upload`` 只合成+產發布資訊。
    """
    settings = get_settings()
    settings.ensure_dirs()
    explicit = dt.date.fromisoformat(args.date) if args.date else None
    target = resolve_fetch_target(today_eastern(), explicit)
    if target is None:
        print("今天非 NYSE 交易日,skip。")
        return 0

    blockers = today_blockers(settings.artifacts_dir, str(target))
    if blockers:
        print(f"⛔ 前置步驟未完成,不執行一鍵作業:缺 {'、'.join(blockers)}。")
        print("   請先完成「取數」+「研究(Claude Code)」,產出齊全再執行。")
        return 1

    print(f"🚀 一鍵完成今日作業({target}):合成 → 發佈")
    rc = cmd_assemble(argparse.Namespace(date=str(target), dry_run=False))
    if rc != 0:
        print("✗ 合成失敗,中止,不發佈。")
        return rc
    return cmd_publish(argparse.Namespace(date=str(target), approve=not args.no_upload))


def cmd_auto(args: argparse.Namespace) -> int:
    """每日全自動:等雲端研究 → 合成 → 上傳(private)→ 通知;人工只剩改公開。

    給 launchd / cron 排程呼叫(``pmb autopilot install``),手動跑也行。冪等:
    當天已上傳過會直接跳過。非交易日 skip。
    """
    from pmb import autopilot

    settings = get_settings()
    settings.ensure_dirs()
    explicit = dt.date.fromisoformat(args.date) if args.date else None
    target = resolve_fetch_target(today_eastern(), explicit)
    if target is None:
        print("今天非 NYSE 交易日,skip。")
        return 0

    if (vid := autopilot.already_published(settings.artifacts_dir, target)) is not None:
        print(f"今天({target})已上傳過:{autopilot.studio_url(vid)},不重複執行。")
        return 0

    logger.info("pmb auto:{} 開始(等待研究上限 {} 分鐘)", target, args.wait_minutes)
    ready = autopilot.wait_for_research(
        settings.artifacts_dir,
        target,
        pull=not args.no_pull,
        wait_minutes=args.wait_minutes,
    )
    if not ready:
        autopilot.notify(
            "PMB 自動流程失敗",
            f"{target} 等不到雲端研究產物(brief/script),請檢查雲端 routine。",
        )
        print(f"⛔ 等了 {args.wait_minutes:.0f} 分鐘仍缺研究產物,中止。")
        return 1

    # 雲端已 commit snapshot 的話直接沿用(數字與講稿一致);缺才本機補取
    snap_path = settings.artifacts_dir / f"snapshot_{target}.json"
    if not snap_path.exists():
        logger.warning("缺 snapshot_{},本機補 fetch(數字可能與講稿有時間差)", target)
        rc = cmd_fetch(argparse.Namespace(date=str(target), json=False, dry_run=False))
        if rc != 0:
            autopilot.notify("PMB 自動流程失敗", f"{target} 補取快照失敗。")
            return rc

    if (rc := cmd_assemble(argparse.Namespace(date=str(target), dry_run=False))) != 0:
        autopilot.notify("PMB 自動流程失敗", f"{target} 影片合成失敗,見 autopilot.log。")
        return rc
    if (rc := cmd_publish(argparse.Namespace(date=str(target), approve=not args.no_upload))) != 0:
        autopilot.notify("PMB 自動流程失敗", f"{target} 上傳失敗,見 autopilot.log。")
        return rc

    vid = autopilot.already_published(settings.artifacts_dir, target)
    if vid:
        autopilot.notify(
            "PMB 影片已上傳(private)",
            f"{target} 完成,到 Studio 看片改公開:{autopilot.studio_url(vid)}",
        )
        print(f"🎬 最後一步:{autopilot.studio_url(vid)} → 改『公開』")
    else:
        autopilot.notify(
            "PMB 完成合成(未上傳)",
            f"{target} 影片已產出;上傳未執行(缺憑證或 --no-upload)。",
        )
    return 0


def cmd_autopilot(args: argparse.Namespace) -> int:
    """管理每日排程(launchd):install / uninstall / status。"""
    from pmb import autopilot

    if args.action == "install":
        try:
            hour, minute = (int(x) for x in args.time.split(":"))
            assert 0 <= hour <= 23 and 0 <= minute <= 59
        except (ValueError, AssertionError):
            print(f"--time 格式錯誤:{args.time}(要 HH:MM,例 19:30)")
            return 1
        return autopilot.install_autopilot(hour, minute)
    if args.action == "uninstall":
        return autopilot.uninstall_autopilot()
    return autopilot.autopilot_status()


def cmd_research_prompt(args: argparse.Namespace) -> int:
    """輸出今日「研究 prompt」(模板 + 真實快照 + thesis + 昨日 brief),供貼進 Claude Code。

    研究這步是 Claude Code(雲端 routine 或本機 Claude Code session)做的,不走 API key。
    """
    settings = get_settings()
    settings.ensure_dirs()
    explicit = dt.date.fromisoformat(args.date) if args.date else None
    target = resolve_fetch_target(today_eastern(), explicit)
    if target is None:
        print("今天非 NYSE 交易日,skip。")
        return 0
    snap_path = settings.artifacts_dir / f"snapshot_{target}.json"
    if not snap_path.exists():
        print(f"缺快照({target}),請先跑 pmb fetch。")
        return 1
    snapshot = Snapshot.model_validate_json(snap_path.read_text(encoding="utf-8"))
    thesis = load_thesis(settings.state_dir / "thesis.json")
    previous_brief = load_previous_brief(settings.artifacts_dir, target)
    template = settings.prompt_path.read_text(encoding="utf-8")
    prompt = build_research_prompt(
        snapshot, thesis, template, previous_brief, output_mode="files"
    )
    if args.out:
        Path(args.out).write_text(prompt, encoding="utf-8")
        print(f"研究 prompt 已寫入 {args.out}")
    else:
        print(prompt)
    return 0


def cmd_next_session(args: argparse.Namespace) -> int:
    """印出今天是否交易日 + 下一個交易日(=盤前 routine 下次啟動日)。"""
    today = today_eastern()
    trading = is_trading_day(today)
    nxt = next_trading_day(today)
    if args.json:
        import json as _json

        print(
            _json.dumps(
                {"today": str(today), "is_trading_day": trading, "next_session": str(nxt)},
                ensure_ascii=False,
            )
        )
        return 0
    mark = "交易日" if trading else "休市"
    print(f"今天 {today}({today.strftime('%A')}):{mark}")
    print(f"下一個交易日(下次盤前啟動):{nxt}({nxt.strftime('%A')})")
    if trading:
        print("→ 今天就是交易日,可直接 pmb run。")
    return 0


def cmd_auth_youtube(args: argparse.Namespace) -> int:
    """一次性:跑 OAuth 同意流程,印出 refresh token 供貼進 .env(密鑰不入庫)。"""
    secrets = Path(args.client_secrets)
    if not secrets.exists():
        print(f"找不到 OAuth 用戶端 JSON:{secrets}")
        print("到 Google Cloud Console → API 與服務 → 憑證 → 建立「OAuth 用戶端 ID")
        print("(應用程式類型:桌面應用程式)」,下載 JSON 後再跑本指令。")
        return 1

    from google_auth_oauthlib.flow import InstalledAppFlow

    # youtube.upload:上傳影片/封面;youtube:playlistItems.insert(自動加播放清單)
    scopes = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube",
    ]
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets), scopes=scopes)
    creds = flow.run_local_server(port=args.port)
    print("\n✅ OAuth 完成。把下面三行貼進 .env(.gitignore 已排除,勿提交):\n")
    print(f"YOUTUBE_CLIENT_ID={creds.client_id}")
    print(f"YOUTUBE_CLIENT_SECRET={creds.client_secret}")
    print(f"YOUTUBE_REFRESH_TOKEN={creds.refresh_token}")
    print("\n之後 pmb publish --approve(或 pmb run --approve)即會以 private 自動上傳。")
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

    run = sub.add_parser("run", help="全流程 fetch→research→assemble→gate(預設不上傳)")
    run.add_argument("--date", help="指定交易日 YYYY-MM-DD")
    run.add_argument("--dry-run", action="store_true", help="研究用範例、配音用靜音(不打 LLM/TTS)")
    run.add_argument(
        "--approve", action="store_true", help="跑完直接上傳 YouTube(private,需手動改公開)"
    )
    run.set_defaults(func=cmd_run)

    nexts = sub.add_parser("next-session", help="顯示今天是否交易日 + 下一個交易日")
    nexts.add_argument("--json", action="store_true", help="以 JSON 輸出")
    nexts.set_defaults(func=cmd_next_session)

    rprompt = sub.add_parser("research-prompt", help="輸出今日研究 prompt(貼進 Claude Code 做研究)")
    rprompt.add_argument("--date", help="指定交易日 YYYY-MM-DD")
    rprompt.add_argument("--out", help="寫到檔案而非印出")
    rprompt.set_defaults(func=cmd_research_prompt)

    todaycmd = sub.add_parser("today", help="一鍵完成今日本機作業:合成→發佈(前置缺則中止)")
    todaycmd.add_argument("--date", help="指定交易日 YYYY-MM-DD")
    todaycmd.add_argument("--no-upload", action="store_true", help="只合成+產發布資訊,不上傳")
    todaycmd.set_defaults(func=cmd_today)

    auto = sub.add_parser(
        "auto", help="每日全自動:等雲端研究→合成→上傳 private→通知(給排程呼叫)"
    )
    auto.add_argument("--date", help="指定交易日 YYYY-MM-DD")
    auto.add_argument("--no-pull", action="store_true", help="不 git pull(用本機現有產物)")
    auto.add_argument("--no-upload", action="store_true", help="只合成,不上傳")
    auto.add_argument(
        "--wait-minutes",
        type=float,
        default=90.0,
        help="等雲端研究產物的上限(預設 90 分,涵蓋美東冬令/夏令的落地時間差)",
    )
    auto.set_defaults(func=cmd_auto)

    ap = sub.add_parser("autopilot", help="管理每日排程(macOS launchd)")
    ap.add_argument("action", choices=["install", "uninstall", "status"])
    ap.add_argument("--time", default="19:30", help="平日觸發時間 HH:MM(本地,預設 19:30)")
    ap.set_defaults(func=cmd_autopilot)

    authyt = sub.add_parser("auth-youtube", help="一次性:取得 YouTube OAuth refresh token")
    authyt.add_argument("--client-secrets", required=True, help="OAuth 桌面用戶端 JSON 路徑")
    authyt.add_argument("--port", type=int, default=0, help="本機回呼埠(預設自動選)")
    authyt.set_defaults(func=cmd_auth_youtube)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
