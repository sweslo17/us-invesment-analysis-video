import { useCallback, useEffect, useRef, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import {
  type ArtifactKind,
  type BriefDoc,
  type NextSession,
  type ScriptDoc,
  type Status,
  type Step,
  convertFileSrc,
  coverPath,
  getStatus,
  listDates,
  nextSession,
  openPath,
  openRel,
  readArtifact,
  researchPrompt,
  runStep,
  videoPath,
} from "./api";

type StepId = "fetch" | "research" | "assemble" | "publish";
type Owner = "cloud" | "local";
type RTab = "script" | "brief" | "report" | "prompt";

interface StepDef {
  id: StepId;
  n: number;
  label: string;
  owner: Owner;
  statusKey: keyof Status;
  desc: string;
}

const STEPS: StepDef[] = [
  { id: "fetch", n: 1, label: "取數", owner: "local", statusKey: "snapshot", desc: "抓今日真實數據快照(FRED / Yahoo Finance)" },
  { id: "research", n: 2, label: "研究", owner: "cloud", statusKey: "brief", desc: "Claude Code 研判 → brief / 講稿 / 報告 / thesis" },
  { id: "assemble", n: 3, label: "合成", owner: "local", statusKey: "video", desc: "配音 + 合成直式短片" },
  { id: "publish", n: 4, label: "發布", owner: "local", statusKey: "publish", desc: "上傳 YouTube(private),人工再改公開" },
];

export default function App() {
  const [dates, setDates] = useState<string[]>([]);
  const [date, setDate] = useState("");
  const [status, setStatus] = useState<Status | null>(null);
  const [nextInfo, setNextInfo] = useState<NextSession | null>(null);
  const [sel, setSel] = useState<StepId>("research");
  const [rtab, setRtab] = useState<RTab>("script");

  const [view, setView] = useState<{ kind: string; ok: boolean; raw: string }>({ kind: "", ok: false, raw: "" });
  const [vpath, setVpath] = useState<string | null>(null);
  const [cpath, setCpath] = useState<string | null>(null);

  const [logs, setLogs] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [exitCode, setExitCode] = useState<number | null>(null);

  const dateRef = useRef(date); dateRef.current = date;
  const selRef = useRef(sel); selRef.current = sel;
  const rtabRef = useRef(rtab); rtabRef.current = rtab;
  const logEnd = useRef<HTMLDivElement>(null);

  const refreshStatus = useCallback(async (d: string) => {
    if (!d) return setStatus(null);
    try { setStatus(await getStatus(d)); } catch { setStatus(null); }
  }, []);

  const refreshDates = useCallback(async () => {
    const ds = await listDates();
    setDates(ds);
    setDate((c) => c || ds[0] || "");
  }, []);

  const loadView = useCallback(async (step: StepId, rt: RTab, d: string) => {
    if (!d) return setView({ kind: "", ok: false, raw: "" });
    if (step === "assemble") {
      setVpath(await videoPath(d).catch(() => null));
      setCpath(await coverPath(d).catch(() => null));
      return;
    }
    if (step === "research" && rt === "prompt") {
      try { setView({ kind: "prompt", ok: true, raw: await researchPrompt(d) }); }
      catch (e) { setView({ kind: "prompt", ok: false, raw: String(e) }); }
      return;
    }
    const kind: ArtifactKind =
      step === "fetch" ? "snapshot" : step === "publish" ? "publish" : (rt as ArtifactKind);
    try { setView({ kind, ok: true, raw: await readArtifact(d, kind) }); }
    catch (e) { setView({ kind, ok: false, raw: String(e) }); }
  }, []);

  useEffect(() => {
    refreshDates();
    nextSession().then(setNextInfo).catch(() => setNextInfo(null));
  }, [refreshDates]);

  useEffect(() => { refreshStatus(date); }, [date, refreshStatus]);
  useEffect(() => { loadView(sel, rtab, date); }, [sel, rtab, date, loadView]);

  useEffect(() => {
    // listen() 是非同步的;StrictMode 會掛載→卸載→再掛載。用 disposed 旗標確保
    // 第一輪的監聽器在 resolve 後若已卸載就立刻解除,避免累積成重複監聽(日誌印兩次)。
    let disposed = false;
    const unsubs: Array<() => void> = [];
    const track = (p: Promise<() => void>) =>
      p.then((u) => (disposed ? u() : unsubs.push(u)));
    track(listen<string>("pmb-log", (e) => setLogs((p) => [...p, e.payload])));
    track(
      listen<number>("pmb-done", (e) => {
        setRunning(false);
        setExitCode(e.payload);
        setLogs((p) => [...p, `— 結束(code ${e.payload})—`]);
        refreshDates();
        refreshStatus(dateRef.current);
        loadView(selRef.current, rtabRef.current, dateRef.current);
      })
    );
    return () => {
      disposed = true;
      unsubs.forEach((u) => u());
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { logEnd.current?.scrollIntoView({ behavior: "smooth" }); }, [logs]);

  const trigger = (step: Step, approve: boolean) => {
    if (running) return;
    setRunning(true);
    setExitCode(null);
    setLogs((p) => [...p, `\n▶ ${step}${date ? ` (${date})` : " (今天)"}${approve ? " · 上傳 YouTube" : ""}`]);
    runStep(step, date, false, approve).catch((err) => {
      setLogs((p) => [...p, `✗ ${err}`]);
      setRunning(false);
      setExitCode(-1);
    });
  };

  const copyPrompt = async () => {
    try {
      await navigator.clipboard.writeText(view.raw);
      setLogs((p) => [...p, "📋 已複製研究 prompt 到剪貼簿 — 貼到 Claude Code 即可做研究"]);
    } catch {
      setLogs((p) => [...p, "複製失敗,請在下方手動選取 prompt 文字複製"]);
    }
  };

  // 一鍵作業前置:取數 + 研究(brief + 講稿)須齊全,否則不給按
  const todayMissing = [
    !status?.snapshot && "取數",
    !status?.brief && "研究(brief)",
    !status?.script && "研究(講稿)",
  ].filter(Boolean) as string[];
  const canRunToday = !!date && todayMissing.length === 0;

  return (
    <div className="app">
      <div className="topbar">
        <h1>PMB 控台 · <span>美股早發車</span></h1>
        {nextInfo && (
          <span className="muted" style={{ fontSize: 12.5 }}>
            {nextInfo.is_trading_day ? `今天 ${nextInfo.today} 開市` : `今天休市 · 下次啟動 ${nextInfo.next_session}`}
          </span>
        )}
        <div className="spacer" style={{ flex: 1 }} />
        <span className="muted">交易日</span>
        <select value={date} onChange={(e) => setDate(e.target.value)}>
          <option value="">今天(自動)</option>
          {dates.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <button onClick={() => { refreshDates(); refreshStatus(date); }}>↻ 重整</button>
      </div>

      <div className="main">
        <div className="steps">
          <div className="today">
            <button
              className="today-btn"
              disabled={running || !canRunToday}
              title={canRunToday ? "合成 → 上傳(private)" : "前置未完成"}
              onClick={() => trigger("today", false)}
            >
              🚀 一鍵完成今日作業
            </button>
            <div className="today-hint">
              {!date
                ? "先選交易日"
                : canRunToday
                ? "合成 → 發佈(上傳 private),完成後到 Studio 改公開"
                : `缺前置:${todayMissing.join("、")}`}
            </div>
          </div>
          <div className="steps-legend">
            <span className="owner cloud">☁️ Claude Code</span>
            <span className="owner local">💻 本機(可點)</span>
          </div>
          {STEPS.map((s) => (
            <button key={s.id} className={`stepcard ${sel === s.id ? "active" : ""}`} onClick={() => setSel(s.id)}>
              <div className="sc-top">
                <span className="sc-n">{s.n}</span>
                <span className="sc-label">{s.label}</span>
                <span className={`owner ${s.owner}`}>{s.owner === "cloud" ? "☁️" : "💻"}</span>
                <div style={{ flex: 1 }} />
                <span className={`sc-dot ${status?.[s.statusKey] ? "on" : ""}`} />
              </div>
              <div className="sc-desc">{s.desc}</div>
            </button>
          ))}
        </div>

        <div className="right">
          <div className="detail">
            <StepDetail
              sel={sel}
              status={status}
              view={view}
              vpath={vpath}
              cpath={cpath}
              rtab={rtab}
              setRtab={setRtab}
              running={running}
              onTrigger={trigger}
              onCopy={copyPrompt}
            />
          </div>
          <div className="logwrap">
            <div className="logbar">
              <span className="status">
                {running ? <span className="running">執行中…</span>
                  : exitCode === null ? <span className="muted">待命</span>
                  : exitCode === 0 ? <span className="ok">✓ 完成</span>
                  : <span className="fail">✗ 失敗 (code {exitCode})</span>}
              </span>
              {running && <span className="spin" />}
              <div style={{ flex: 1 }} />
              <button onClick={() => setLogs([])} disabled={running}>清除</button>
            </div>
            <div className="log">
              {logs.length === 0
                ? <div className="empty">本機步驟的輸出會即時顯示在這裡。</div>
                : logs.map((l, i) => <div key={i} className={`line ${l.startsWith("$") ? "cmd" : ""}`}>{l}</div>)}
              <div ref={logEnd} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function StepDetail(props: {
  sel: StepId;
  status: Status | null;
  view: { kind: string; ok: boolean; raw: string };
  vpath: string | null;
  cpath: string | null;
  rtab: RTab;
  setRtab: (t: RTab) => void;
  running: boolean;
  onTrigger: (step: Step, approve: boolean) => void;
  onCopy: () => void;
}) {
  const { sel, status, view, vpath, cpath, rtab, setRtab, running, onTrigger, onCopy } = props;
  const def = STEPS.find((s) => s.id === sel)!;

  return (
    <div>
      <div className="dh">
        <span className="sc-n big">{def.n}</span>
        <h2>{def.label}</h2>
        <span className={`owner ${def.owner}`}>{def.owner === "cloud" ? "☁️ Claude Code routine" : "💻 本機操作"}</span>
        <span className={`sc-dot ${status?.[def.statusKey] ? "on" : ""}`} />
      </div>
      <p className="muted dh-desc">{def.desc}</p>

      {/* 動作區 */}
      {sel === "fetch" && (
        <div className="actions">
          <button className="primary" disabled={running} onClick={() => onTrigger("fetch", false)}>執行取數</button>
        </div>
      )}

      {sel === "research" && (
        <div className="cloudbox">
          <p>這步由 <b>Claude Code</b> 做,不用 API key:</p>
          <ul>
            <li><b>雲端 routine</b> 盤前自動執行(電腦關機也跑)。</li>
            <li>或<b>本機手動</b>:複製下方「研究 Prompt」→ 貼進 Claude Code → 它研究並寫出 brief/講稿/報告。</li>
          </ul>
          <div className="actions">
            <button className="primary" onClick={onCopy}>📋 複製研究 Prompt</button>
            <button onClick={() => openRel("prompts/daily_research.md")}>✎ 開 Prompt 範本</button>
          </div>
          <p className="muted" style={{ fontSize: 12 }}>※ 需先完成「1 取數」,Prompt 才會帶今日快照數字。</p>
        </div>
      )}

      {sel === "assemble" && (
        <div className="actions">
          <button className="primary" disabled={running} onClick={() => onTrigger("assemble", false)}>執行合成</button>
          <span className="muted" style={{ fontSize: 12 }}>需先有研究產出的講稿。</span>
        </div>
      )}

      {sel === "publish" && (
        <div className="actions">
          <button disabled={running} onClick={() => onTrigger("publish", false)}>預演(不上傳,只產發布資訊)</button>
          <button className="danger" disabled={running} onClick={() => onTrigger("publish", true)}>⬆ 上傳 YouTube(private)</button>
          <span className="muted" style={{ fontSize: 12 }}>上傳後自己到 Studio 揭露合成內容 + 改公開。</span>
        </div>
      )}

      {/* 輸出區 */}
      <div className="output">
        {sel === "research" && (
          <div className="tabs">
            {(["script", "brief", "report", "prompt"] as RTab[]).map((t) => (
              <button key={t} className={`tab ${rtab === t ? "active" : ""}`} onClick={() => setRtab(t)}>
                {t === "script" ? "講稿" : t === "brief" ? "Brief" : t === "report" ? "報告" : "研究 Prompt"}
              </button>
            ))}
          </div>
        )}
        <OutputView sel={sel} rtab={rtab} view={view} vpath={vpath} cpath={cpath} status={status} />
      </div>
    </div>
  );
}

function OutputView({
  sel, rtab, view, vpath, cpath, status,
}: {
  sel: StepId;
  rtab: RTab;
  view: { kind: string; ok: boolean; raw: string };
  vpath: string | null;
  cpath: string | null;
  status: Status | null;
}) {
  if (sel === "assemble") {
    if (!vpath) return <p className="empty">尚未產生影片。先完成研究 → 按「執行合成」。</p>;
    return (
      <div>
        <video className="preview" src={convertFileSrc(vpath)} poster={cpath ? convertFileSrc(cpath) : undefined} controls />
        <div style={{ margin: "10px 0" }}>
          <button onClick={() => openPath(vpath)}>▶ 系統播放器</button>{" "}
          <button onClick={() => openPath(vpath.replace(/\/[^/]+$/, ""))}>📂 資料夾</button>
        </div>
      </div>
    );
  }

  // 防止用「上一步的資料」渲染這一步:view.kind 必須對得上目前選的步驟/分頁,
  // 否則顯示載入中,等非同步重載完成(不然會 JSON.parse 到別的檔而 crash)。
  const expected = sel === "fetch" ? "snapshot" : sel === "publish" ? "publish" : rtab;
  if (view.kind !== expected) return <p className="empty">載入中…</p>;

  if (sel === "publish") {
    if (!view.ok) return <p className="empty">尚未發布。按「預演」會產出標題/描述/tags 供檢視。</p>;
    let m: Record<string, unknown>;
    try { m = JSON.parse(view.raw); } catch { return <pre className="raw">{view.raw}</pre>; }
    const tags = (m.tags as string[]) ?? [];
    return (
      <div>
        <div className="section-title">YouTube 發布資訊</div>
        <div className="item"><h4>{String(m.title ?? "")}</h4></div>
        <div className="section-title">tags</div>
        <div className="chips">{tags.map((t, i) => <span key={i} className="chip">{t}</span>)}</div>
        <div className="section-title">狀態</div>
        <p className="muted">
          可見度 {String(m.privacy ?? "?")} ·{" "}
          {m.published
            ? `已上傳:${String(m.video_id ?? "")} → 頻道 ${String(m.channel_title ?? m.channel_id ?? "?")}`
            : "尚未上傳(預演)"}
        </p>
        {status?.published && <p className="muted">⚠️ 確認上傳到的是「美股早發車」,再到 Studio 改公開。</p>}
        <details style={{ marginTop: 10 }}><summary className="muted">原始描述</summary><pre className="raw">{String(m.description ?? "")}</pre></details>
      </div>
    );
  }

  if (!view.ok) return <p className="empty">{view.raw || "尚未產生。"}</p>;

  if (sel === "fetch") return <pre className="raw">{view.raw}</pre>;

  // research: prompt / report / script / brief
  if (rtab === "prompt") {
    return (
      <div>
        <p className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
          貼進 Claude Code 即可做今天的研究(含今日快照數字):
        </p>
        <pre className="raw promptbox">{view.raw}</pre>
      </div>
    );
  }
  if (rtab === "report") return <pre className="raw">{view.raw}</pre>;

  if (rtab === "script") {
    let doc: ScriptDoc;
    try { doc = JSON.parse(view.raw); } catch { return <pre className="raw">{view.raw}</pre>; }
    if (!doc || !Array.isArray(doc.segments)) return <pre className="raw">{view.raw}</pre>;
    return (
      <div>
        <div className="section-title">
          講稿 · {doc.segments.length} 段 · {doc.segments.reduce((s, x) => s + (x.duration || 0), 0).toFixed(0)} 秒
        </div>
        {doc.segments.map((s, i) => {
          const isCard = s.headline != null;
          return (
            <div className="seg" key={i}>
              <div className="meta">
                <span className={`kind ${isCard ? "card" : "chart"}`}>{isCard ? "字卡" : `圖 ${s.chart_id ?? ""}`}</span>
                <span>{s.t_start.toFixed(0)}s</span><span>+{s.duration.toFixed(0)}s</span>
                {s.title && <span>· {s.title}</span>}
              </div>
              {isCard && <div style={{ fontWeight: 700, marginBottom: 4 }}>{s.headline}</div>}
              <div className="vo">{s.vo}</div>
              {s.tag && <div className="tag">{s.tag}</div>}
            </div>
          );
        })}
        {doc.coverage_gaps && doc.coverage_gaps.length > 0 && (
          <>
            <div className="section-title">⚠️ 圖表庫缺口</div>
            {doc.coverage_gaps.map((g, i) => <p key={i} className="muted">· {g}</p>)}
          </>
        )}
      </div>
    );
  }

  // brief
  let b: BriefDoc;
  try { b = JSON.parse(view.raw); } catch { return <pre className="raw">{view.raw}</pre>; }
  if (!b || !Array.isArray(b.items) || !b.regime || !b.thesis_delta)
    return <pre className="raw">{view.raw}</pre>;
  return (
    <div>
      <div className="section-title">市場 regime · lead {b.lead_horizon}</div>
      <div className="chips">{Object.entries(b.regime).map(([k, v]) => <span className="chip" key={k}>{k}: {v}</span>)}</div>
      <div className="section-title">研判({b.items.length})</div>
      {b.items.map((it, i) => (
        <div className="item" key={i}>
          <h4>{it.headline}</h4>
          <div className="chips">
            <span className="chip">{it.horizon}</span><span className="chip">{it.vs_thesis}</span>
            <span className="chip">重要度 {it.materiality}</span><span className="chip">{it.confidence}</span>
          </div>
          <div className="muted">{it.audience_value}</div>
        </div>
      ))}
      {b.catalysts && b.catalysts.length > 0 && (
        <>
          <div className="section-title">今日催化劑</div>
          {b.catalysts.map((c, i) => <p key={i} className="muted">· {c}</p>)}
        </>
      )}
      <div className="section-title">Thesis</div>
      <p className="muted">{b.thesis_delta.changed ? `變動(${b.thesis_delta.horizon ?? ""}):${b.thesis_delta.summary ?? ""}` : "今日無變動"}</p>
    </div>
  );
}
