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
  runStep,
  videoPath,
} from "./api";

type Tab = "script" | "brief" | "report" | "video";

const STATUS_KEYS: { key: keyof Status; label: string }[] = [
  { key: "snapshot", label: "快照" },
  { key: "brief", label: "Brief" },
  { key: "script", label: "講稿" },
  { key: "report", label: "報告" },
  { key: "video", label: "影片" },
];

const STEP_BTNS: { step: Step; label: string; cls?: string }[] = [
  { step: "fetch", label: "1 取數" },
  { step: "research", label: "2 研究" },
  { step: "assemble", label: "3 合成" },
  { step: "publish", label: "4 發布", cls: "danger" },
];

export default function App() {
  const [dates, setDates] = useState<string[]>([]);
  const [date, setDate] = useState<string>("");
  const [status, setStatus] = useState<Status | null>(null);
  const [tab, setTab] = useState<Tab>("script");
  const [dryrun, setDryrun] = useState(true);
  const [approve, setApprove] = useState(false);

  const [logs, setLogs] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [exitCode, setExitCode] = useState<number | null>(null);
  const [nextInfo, setNextInfo] = useState<NextSession | null>(null);

  const dateRef = useRef(date);
  dateRef.current = date;
  const tabRef = useRef(tab);
  tabRef.current = tab;
  const logEnd = useRef<HTMLDivElement>(null);

  const refreshStatus = useCallback(async (d: string) => {
    if (!d) return setStatus(null);
    try {
      setStatus(await getStatus(d));
    } catch {
      setStatus(null);
    }
  }, []);

  const refreshDates = useCallback(async () => {
    const ds = await listDates();
    setDates(ds);
    setDate((cur) => cur || ds[0] || "");
  }, []);

  useEffect(() => {
    refreshDates();
    nextSession()
      .then(setNextInfo)
      .catch(() => setNextInfo(null));
  }, [refreshDates]);

  useEffect(() => {
    refreshStatus(date);
  }, [date, refreshStatus]);

  // ---- 內容檢視(宣告需在事件監聽 useEffect 之前)----
  const [content, setContent] = useState<{ kind: Tab; ok: boolean; raw: string }>({
    kind: "script",
    ok: false,
    raw: "",
  });
  const [vpath, setVpath] = useState<string | null>(null);
  const [cpath, setCpath] = useState<string | null>(null);

  const loadContent = useCallback(async (t: Tab, d: string) => {
    if (!d) {
      setContent({ kind: t, ok: false, raw: "" });
      return;
    }
    if (t === "video") {
      setVpath(await videoPath(d).catch(() => null));
      setCpath(await coverPath(d).catch(() => null));
      return;
    }
    const kind = t as ArtifactKind;
    try {
      const raw = await readArtifact(d, kind);
      setContent({ kind: t, ok: true, raw });
    } catch (err) {
      setContent({ kind: t, ok: false, raw: String(err) });
    }
  }, []);

  // 事件監聽:即時日誌 + 結束碼
  useEffect(() => {
    const unsubs: Array<() => void> = [];
    listen<string>("pmb-log", (e) => setLogs((p) => [...p, e.payload])).then((u) =>
      unsubs.push(u)
    );
    listen<number>("pmb-done", (e) => {
      setRunning(false);
      setExitCode(e.payload);
      setLogs((p) => [...p, `— 結束(code ${e.payload})—`]);
      refreshDates();
      refreshStatus(dateRef.current);
      loadContent(tabRef.current, dateRef.current);
    }).then((u) => unsubs.push(u));
    return () => unsubs.forEach((u) => u());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    logEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  const trigger = (step: Step) => {
    if (running) return;
    setRunning(true);
    setExitCode(null);
    setLogs((p) => [...p, `\n▶ ${step}${date ? ` (${date})` : " (今天)"} dry-run=${dryrun} approve=${approve}`]);
    runStep(step, date, dryrun, approve).catch((err) => {
      setLogs((p) => [...p, `✗ ${err}`]);
      setRunning(false);
      setExitCode(-1);
    });
  };

  useEffect(() => {
    loadContent(tab, date);
  }, [tab, date, loadContent]);

  return (
    <div className="app">
      <div className="topbar">
        <h1>
          PMB 控台 · <span>美股早發車</span>
        </h1>
        {nextInfo && (
          <span className="muted" style={{ fontSize: 12.5 }}>
            {nextInfo.is_trading_day
              ? `今天 ${nextInfo.today} 開市`
              : `今天休市 · 下次啟動 ${nextInfo.next_session}`}
          </span>
        )}
        <div className="spacer" />
        <span className="muted">交易日</span>
        <select value={date} onChange={(e) => setDate(e.target.value)}>
          <option value="">今天(自動)</option>
          {dates.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
        <button onClick={() => { refreshDates(); refreshStatus(date); }}>↻ 重整</button>
      </div>

      <div className="statusbar">
        {STATUS_KEYS.map(({ key, label }) => (
          <span key={key} className={`badge ${status?.[key] ? "on" : ""}`}>
            <span className="dot" />
            {label}
          </span>
        ))}
        {status?.publish && (
          <span className="badge pub">
            <span className="dot" />
            {status.published ? `已上傳 ${status.video_id ?? ""}` : "已產 manifest"}
          </span>
        )}
        {!date && <span className="muted">　選個交易日看狀態(或直接跑「今天」)</span>}
      </div>

      <div className="actionbar">
        <span
          className={`toggle ${dryrun ? "active" : ""}`}
          onClick={() => setDryrun((v) => !v)}
        >
          {dryrun ? "☑" : "☐"} dry-run(範例/靜音)
        </span>
        <span
          className={`toggle ${approve ? "active" : ""}`}
          onClick={() => setApprove((v) => !v)}
        >
          {approve ? "☑" : "☐"} approve(真上傳)
        </span>
        <div className="sep" />
        {STEP_BTNS.map(({ step, label, cls }) => (
          <button key={step} className={cls} disabled={running} onClick={() => trigger(step)}>
            {label}
          </button>
        ))}
        <div className="sep" />
        <button className="run" disabled={running} onClick={() => trigger("run")}>
          ▶ 全流程 run
        </button>
        {running && <span className="spin" />}
        <div className="spacer" style={{ flex: 1 }} />
        <button title="編輯研究 prompt" onClick={() => openRel("prompts/daily_research.md")}>
          ✎ prompt
        </button>
        <button title="編輯中長期 thesis" onClick={() => openRel("state/thesis.json")}>
          ✎ thesis
        </button>
        <button title="開啟 artifacts 資料夾" onClick={() => openRel("artifacts")}>
          📂 artifacts
        </button>
      </div>

      <div className="main">
        <div className="content">
          <div className="tabs">
            {(["script", "brief", "report", "video"] as Tab[]).map((t) => (
              <button
                key={t}
                className={`tab ${tab === t ? "active" : ""}`}
                onClick={() => setTab(t)}
              >
                {t === "script" ? "講稿" : t === "brief" ? "Brief" : t === "report" ? "報告" : "影片"}
              </button>
            ))}
          </div>
          <div className="pane">
            <ContentView
              tab={tab}
              content={content}
              vpath={vpath}
              cpath={cpath}
              status={status}
            />
          </div>
        </div>

        <div className="logwrap">
          <div className="logbar">
            <span className="status">
              {running ? (
                <span className="running">執行中…</span>
              ) : exitCode === null ? (
                <span className="muted">待命</span>
              ) : exitCode === 0 ? (
                <span className="ok">✓ 完成</span>
              ) : (
                <span className="fail">✗ 失敗 (code {exitCode})</span>
              )}
            </span>
            <div className="spacer" style={{ flex: 1 }} />
            <button onClick={() => setLogs([])} disabled={running}>
              清除
            </button>
          </div>
          <div className="log">
            {logs.length === 0 ? (
              <div className="empty">按上方按鈕觸發步驟,輸出會即時顯示在這裡。</div>
            ) : (
              logs.map((l, i) => (
                <div key={i} className={`line ${l.startsWith("$") ? "cmd" : ""}`}>
                  {l}
                </div>
              ))
            )}
            <div ref={logEnd} />
          </div>
        </div>
      </div>
    </div>
  );
}

function ContentView({
  tab,
  content,
  vpath,
  cpath,
  status,
}: {
  tab: Tab;
  content: { kind: Tab; ok: boolean; raw: string };
  vpath: string | null;
  cpath: string | null;
  status: Status | null;
}) {
  if (tab === "video") {
    return (
      <div>
        <div className="section-title">影片</div>
        {vpath ? (
          <>
            <video
              className="preview"
              src={convertFileSrc(vpath)}
              poster={cpath ? convertFileSrc(cpath) : undefined}
              controls
            />
            <div style={{ margin: "10px 0" }}>
              <button onClick={() => openPath(vpath)}>▶ 系統播放器</button>{" "}
              <button onClick={() => openPath(vpath.replace(/\/[^/]+$/, ""))}>📂 資料夾</button>
            </div>
            <p className="muted" style={{ wordBreak: "break-all", fontSize: 12 }}>{vpath}</p>
            <div className="section-title" style={{ marginTop: 18 }}>發布狀態</div>
            <p className="muted">
              {status?.publish
                ? status.published
                  ? `已上傳 YouTube:${status.video_id ?? "(無 id)"}`
                  : "已產 publish manifest(尚未上傳;dry-run 或缺憑證)"
                : "尚未發布"}
            </p>
          </>
        ) : (
          <p className="empty">尚未產生影片。先跑「3 合成」。</p>
        )}
      </div>
    );
  }

  if (!content.ok || content.kind !== tab) {
    return <p className="empty">{content.kind === tab ? content.raw : "載入中…"}</p>;
  }

  if (tab === "report") {
    return <pre className="raw">{content.raw}</pre>;
  }

  if (tab === "script") {
    let doc: ScriptDoc;
    try {
      doc = JSON.parse(content.raw);
    } catch {
      return <pre className="raw">{content.raw}</pre>;
    }
    return (
      <div>
        <div className="section-title">
          講稿 · {doc.segments.length} 段 ·{" "}
          {doc.segments.reduce((s, x) => s + (x.duration || 0), 0).toFixed(0)} 秒
        </div>
        {doc.segments.map((s, i) => {
          const isCard = s.headline != null;
          return (
            <div className="seg" key={i}>
              <div className="meta">
                <span className={`kind ${isCard ? "card" : "chart"}`}>
                  {isCard ? "字卡" : `圖 ${s.chart_id ?? ""}`}
                </span>
                <span>{s.t_start.toFixed(0)}s</span>
                <span>+{s.duration.toFixed(0)}s</span>
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
            {doc.coverage_gaps.map((g, i) => (
              <p key={i} className="muted">
                · {g}
              </p>
            ))}
          </>
        )}
      </div>
    );
  }

  // brief
  let b: BriefDoc;
  try {
    b = JSON.parse(content.raw);
  } catch {
    return <pre className="raw">{content.raw}</pre>;
  }
  return (
    <div>
      <div className="section-title">市場 regime · lead {b.lead_horizon}</div>
      <div className="chips">
        {Object.entries(b.regime).map(([k, v]) => (
          <span className="chip" key={k}>
            {k}: {v}
          </span>
        ))}
      </div>

      <div className="section-title">研判({b.items.length})</div>
      {b.items.map((it, i) => (
        <div className="item" key={i}>
          <h4>{it.headline}</h4>
          <div className="chips">
            <span className="chip">{it.horizon}</span>
            <span className="chip">{it.vs_thesis}</span>
            <span className="chip">重要度 {it.materiality}</span>
            <span className="chip">{it.confidence}</span>
          </div>
          <div className="muted">{it.audience_value}</div>
        </div>
      ))}

      {b.catalysts && b.catalysts.length > 0 && (
        <>
          <div className="section-title">今日催化劑</div>
          {b.catalysts.map((c, i) => (
            <p key={i} className="muted">
              · {c}
            </p>
          ))}
        </>
      )}

      <div className="section-title">Thesis</div>
      <p className="muted">
        {b.thesis_delta.changed
          ? `變動(${b.thesis_delta.horizon ?? ""}):${b.thesis_delta.summary ?? ""}`
          : "今日無變動"}
      </p>
    </div>
  );
}
