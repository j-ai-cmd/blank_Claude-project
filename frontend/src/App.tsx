import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";
import { DynamicIsland } from "./components/amicro/dynamic-island";
import { PulseDot } from "./components/amicro/pulse-dot";
import { Skeleton } from "./components/amicro/skeleton";
import { Controller } from "./lib/controller";
import { DemoFeed } from "./lib/demoFeed";
import { LiveFeed } from "./lib/liveFeed";
import { store, useStore } from "./lib/store";
import type { Approval, Employee, Feed } from "./lib/types";
import { OfficeEngine } from "./office/engine";
import { Labels } from "./ui/Labels";
import { Modal, type Sheet } from "./ui/Modals";

const GATE_TEXT: Record<string, string> = { G1: "Contract", G2: "Plan", G3: "External action", G4: "Delivery", GM: "Standing rule" };

function savedConnection(): { url: string; token: string } | null {
  try {
    const url = localStorage.getItem("office.url"), token = localStorage.getItem("office.token");
    return url && token ? { url, token } : null;
  } catch { return null; }
}

export default function App() {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [engine, setEngine] = useState<OfficeEngine | null>(null);
  const [ctl, setCtl] = useState<Controller | null>(null);
  const [sheet, setSheet] = useState<Sheet>(null);
  const [conn, setConn] = useState(savedConnection);
  const [focus, setFocus] = useState("all");
  const [hint, setHint] = useState(true);
  useEffect(() => { const t = setTimeout(() => setHint(false), 20000); return () => clearTimeout(t); }, []);

  const office = useStore((s) => s.office);
  const loading = useStore((s) => s.loading);
  const error = useStore((s) => s.error);

  // one engine + controller per connection (demo or live)
  useEffect(() => {
    const eng = new OfficeEngine(canvas.current!);
    const feed: Feed = conn ? new LiveFeed(conn.url, conn.token) : new DemoFeed();
    const c = new Controller(feed, eng);
    setEngine(eng); setCtl(c);
    let live = true;
    c.start().then(() => {
      if (live && feed.mode === "demo") {
        timers.push(window.setTimeout(() => feed.prompt("studio_lead", "Make a Sherlock reel on how AI agents use tools"), 900));
        timers.push(window.setTimeout(() => feed.prompt("sales_lead", "Find 20 companies hiring designers and draft pitch emails"), 3500));
      }
    });
    const timers: number[] = [];
    return () => { live = false; timers.forEach(clearTimeout); c.stop(); eng.dispose(); };
  }, [conn]);

  const openSheet = useCallback((s: Sheet) => setSheet(s), []);
  const close = useCallback(() => setSheet(null), []);

  useEffect(() => {
    if (!engine || !office) return;
    const all: Employee[] = [...Object.values(office.core), ...office.departments.flatMap((d) => [d.lead, ...d.specialists])];
    engine.onPick = (p) => {
      if (p.task) { setSheet({ kind: "task", taskId: p.task }); return; }
      const e = all.find((x) => x.id === p.emp);
      if (!e) return;
      setHint(false);
      setSheet(e.promptable ? { kind: "prompt", emp: e } : { kind: "profile", emp: e });
    };
    engine.onHover = (id) => store.set({ hovered: id });
    engine.onFocus = (k) => { setFocus(k); setHint(false); };
  }, [engine, office]);

  const connect = (url: string, token: string) => {
    try { localStorage.setItem("office.url", url); localStorage.setItem("office.token", token); } catch { /* private window: session only */ }
    setConn({ url, token });
  };
  const disconnect = () => {
    try { localStorage.removeItem("office.token"); } catch { /* ignore */ }
    setConn(null);
  };

  const foci: [string, string][] = office ? [["all", "Whole office"], ["hq", "Head table"],
    ...office.departments.map((d) => [d.id, d.id] as [string, string]), ["owner", "Your desk"]] : [];

  return (
    <div id="app">
      <canvas id="office" ref={canvas} aria-label="3D office floor. Click Atlas or a department Lead to give a task." />
      <Labels engine={engine} />

      <StatusPill ctl={ctl} onConnect={() => setSheet({ kind: "connect" })} onDisconnect={disconnect} />

      {hint && !loading && !error && <div className="hint">Everyone sleeps until there's work. <b>Click Atlas or a Lead</b> (gold badge) to give a task.</div>}
      {error && <div className="error" role="alert">Couldn't load the office: {error}. Check the backend URL and token, or <button className="btn" onClick={disconnect}>switch to demo</button></div>}

      <CameraMenu foci={foci} focus={focus} onPick={(k) => { setFocus(k); engine?.focus(k); }} />
      <Ticker />
      <InboxCard ctl={ctl} onShow={(id) => engine?.follow(id)} />

      <Modal sheet={sheet} close={close} ctl={ctl} openSheet={openSheet} onFollow={(id) => engine?.follow(id)} onConnect={connect} />

      {loading && (
        <div className="loading" aria-busy="true">
          <div className="box amicro-skeleton">
            <p>Opening the office…</p>
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-1/2" />
          </div>
        </div>
      )}
    </div>
  );
}

/** One pill: live dot, budget, open tasks, inbox count. Hover (or tap) to open the controls. */
function StatusPill({ ctl, onConnect, onDisconnect }: { ctl: Controller | null; onConnect: () => void; onDisconnect: () => void }) {
  const conn = useStore((s) => s.conn), mode = useStore((s) => s.mode);
  const spent = useStore((s) => s.spent), budget = useStore((s) => s.budget);
  const open = useStore((s) => Object.values(s.tasks).filter((t) => !t.parent_id).length);
  const pending = useStore((s) => s.approvals.length);
  const busy = useStore((s) => Object.values(s.presence).some((p) => p.state === "working"));
  const paused = useStore((s) => s.paused), speed = useStore((s) => s.speed);
  const [openPill, setOpenPill] = useState(false);
  const pct = Math.min(100, (spent / Math.max(1, budget)) * 100);
  const connText = mode === "demo" ? "Demo" : conn === "live" ? "Live" : conn === "reconnecting" ? "Reconnecting" : "Connecting";
  return (
    <div className="pill-wrap" onMouseEnter={() => setOpenPill(true)} onMouseLeave={() => setOpenPill(false)}
      onFocus={() => setOpenPill(true)} onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setOpenPill(false); }}>
      <motion.div className="pill" layout transition={{ type: "spring", stiffness: 420, damping: 34 }} data-open={openPill}>
        <button className="pill-row" onClick={() => setOpenPill((v) => !v)} aria-expanded={openPill} aria-label="Office status and controls">
          <span className="amicro-live" data-conn={mode === "demo" ? "demo" : conn}><PulseDot /></span>
          <span className="pill-item">{connText}</span>
          {busy && !paused && <span className="amicro-island" title="Someone is working"><DynamicIsland /></span>}
          <span className="pill-sep" />
          <span className="pill-item" title="Claude plan credit used this month">${spent.toFixed(2)}<span className="mini-bar"><b style={{ width: `${pct}%`, background: pct > 80 ? "var(--bad)" : pct > 60 ? "var(--warn)" : "var(--ok)" }} /></span></span>
          <span className="pill-item">{open} open</span>
          <span className="count" data-n={pending} title="Waiting on you">{pending}</span>
        </button>
        <AnimatePresence initial={false}>
          {openPill && (
            <motion.div className="pill-more" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }}>
              <div className="pill-meta">AI budget ${spent.toFixed(2)} of ${budget.toFixed(0)} this month · {pending} waiting on you</div>
              <div className="pill-actions">
                {mode === "demo" && <button className="btn" onClick={() => ctl?.setSpeed(speed === 1 ? 2 : speed === 2 ? 4 : 1)}>Speed {speed}×</button>}
                <button className="btn" onClick={() => ctl?.togglePause()}>{paused ? "Resume all" : "Pause all"}</button>
                <button className="btn" onClick={mode === "demo" ? onConnect : onDisconnect}>{mode === "demo" ? "Connect backend" : "Switch to demo"}</button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  );
}

function CameraMenu({ foci, focus, onPick }: { foci: [string, string][]; focus: string; onPick: (k: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="cam">
      {open && (
        <div className="cam-menu" role="menu">
          {foci.map(([k, label]) => (
            <button key={k} role="menuitemradio" aria-checked={focus === k} onClick={() => { onPick(k); setOpen(false); }}>{label}</button>
          ))}
        </div>
      )}
      <button className="btn" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        Camera: <span style={{ textTransform: "capitalize" }}>{foci.find(([k]) => k === focus)?.[1] ?? "Whole office"}</span>
      </button>
    </div>
  );
}

/** Latest event on one line; click for the recent history. */
function Ticker() {
  const feed = useStore((s) => s.feed);
  const [open, setOpen] = useState(false);
  const last = feed[0];
  return (
    <div className="ticker-wrap">
      {open && (
        <div className="ticker-history">
          {feed.slice(0, 30).map((l) => (
            <div key={l.id} className={"feed-line" + (l.walk ? " walk" : "")}><time>{l.at}</time><div dangerouslySetInnerHTML={{ __html: l.html }} /></div>
          ))}
        </div>
      )}
      <button className="ticker" onClick={() => setOpen((v) => !v)} aria-expanded={open} title="Show recent activity">
        {last ? (
          <AnimatePresence mode="popLayout" initial={false}>
            <motion.span key={last.id} className={"ticker-line" + (last.walk ? " walk" : "")} initial={{ y: 12, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: -12, opacity: 0 }}>
              <time>{last.at}</time> <span dangerouslySetInnerHTML={{ __html: last.html }} />
            </motion.span>
          </AnimatePresence>
        ) : <span className="ticker-line muted">Quiet. Nothing is happening yet.</span>}
      </button>
    </div>
  );
}

/** Appears only when something needs you. Shows one approval at a time. */
function InboxCard({ ctl, onShow }: { ctl: Controller | null; onShow: (taskId: string) => void }) {
  const approvals = useStore((s) => s.approvals);
  const [i, setI] = useState(0);
  const idx = Math.min(i, Math.max(0, approvals.length - 1));
  const a = approvals[idx];
  return (
    <AnimatePresence>
      {a && (
        <motion.aside className="inbox-card" aria-label="Needs your decision" initial={{ opacity: 0, y: -10, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -10, scale: 0.97 }}>
          <div className="inbox-head">
            <span>Needs you</span>
            {approvals.length > 1 && (
              <span className="inbox-nav">
                <button className="btn" aria-label="Previous" onClick={() => setI((idx - 1 + approvals.length) % approvals.length)}>‹</button>
                {idx + 1} of {approvals.length}
                <button className="btn" aria-label="Next" onClick={() => setI((idx + 1) % approvals.length)}>›</button>
              </span>
            )}
          </div>
          <ApprovalCard key={a.id} a={a} ctl={ctl} onShow={onShow} />
        </motion.aside>
      )}
    </AnimatePresence>
  );
}



function ApprovalCard({ a, ctl, onShow }: { a: Approval; ctl: Controller | null; onShow: (taskId: string) => void }) {
  const from = useStore((s) => {
    const o = s.office; const id = a.employee_id; if (!o || !id) return "";
    return [...Object.values(o.core), ...o.departments.flatMap((d) => [d.lead, ...d.specialists])].find((e) => e.id === id)?.name ?? id;
  });
  const task = useStore((s) => s.tasks[a.task_id]);
  const artifacts = (a.preview?.artifacts as string[] | undefined) ?? [];
  const mem = (a.preview?.memory_candidates as { id: string; text: string }[] | undefined) ?? [];
  const [ticks, setTicks] = useState<string[]>(() => mem.map((m) => m.id));
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const act = async (approve: boolean) => {
    try { await ctl?.decide(a.id, approve, reason, ticks); } catch (e) { setErr((e as Error).message); }
  };
  return (
    <div className="card">
      <div className="gate"><b>{a.gate}</b>{GATE_TEXT[a.gate]}{from ? ` · from ${from}` : ""}</div>
      <h3>{task?.request ?? a.title ?? "Approval"}</h3>
      {a.summary && <p className="sum">{a.summary.replace(/[*_`]/g, "")}</p>}
      {artifacts.length > 0 && <p className="sum">Files: {artifacts.map((f) => <span key={f} className="tag" style={{ marginRight: 4 }}>{f}</span>)}</p>}
      {mem.map((m) => (
        <label key={m.id}>
          <input type="checkbox" id={`mem-${a.id}-${m.id}`} checked={ticks.includes(m.id)}
            onChange={(e) => setTicks((t) => (e.target.checked ? [...t, m.id] : t.filter((x) => x !== m.id)))} />
          Save to memory: {m.text}
        </label>
      ))}
      {rejecting && <input id={`reason-${a.id}`} className="field" autoFocus placeholder="What should change?" value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Reason for sending back" />}
      {err && <p className="form-err">{err}</p>}
      <div className="acts">
        {!rejecting && <button className="btn ok" onClick={() => act(true)}>{a.gate === "G4" ? "Accept" : "Approve"}</button>}
        {rejecting ? <button className="btn bad" onClick={() => act(false)}>Send back</button> : <button className="btn bad" onClick={() => setRejecting(true)}>Reject</button>}
        <button className="btn" onClick={() => onShow(a.task_id)}>Show note</button>
      </div>
    </div>
  );
}

