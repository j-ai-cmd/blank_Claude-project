import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DynamicIsland } from "./components/amicro/dynamic-island";
import { PulseDot } from "./components/amicro/pulse-dot";
import { Skeleton } from "./components/amicro/skeleton";
import { Controller } from "./lib/controller";
import { DemoFeed } from "./lib/demoFeed";
import { LiveFeed } from "./lib/liveFeed";
import { store, useStore } from "./lib/store";
import type { Approval, Employee, Feed, Office } from "./lib/types";
import { OfficeEngine, deptColor } from "./office/engine";
import { Labels } from "./ui/Labels";
import { Modal, type Sheet } from "./ui/Modals";

// Layout (Stitch "Sterling" design): header banner, filing cabinet left, personnel record right, memo bar bottom.
const GATE_TEXT: Record<string, string> = { G1: "Contract approval", G2: "Plan approval", G3: "Action authorization", G4: "Delivery acceptance", GM: "Standing rule" };
const STATE_TEXT: Record<string, string> = { sleeping: "Asleep at desk", working: "Working", supervising: "Supervising", waiting_owner: "Waiting on you", blocked: "Blocked", paused: "Paused" };
const hex = (n: number) => "#" + n.toString(16).padStart(6, "0");

function savedConnection(): { url: string; token: string } | null {
  try {
    const url = localStorage.getItem("office.url"), token = localStorage.getItem("office.token");
    return url && token ? { url, token } : null;
  } catch { return null; }
}
function everyone(o: Office | null): Employee[] {
  return o ? [...Object.values(o.core), ...o.departments.flatMap((d) => [d.lead, ...d.specialists])] : [];
}
function deptLabel(id: string) { return id === "hq" ? "Executive suite" : id === "owner" ? "Your desk" : id.charAt(0).toUpperCase() + id.slice(1); }

export default function App() {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [engine, setEngine] = useState<OfficeEngine | null>(null);
  const [ctl, setCtl] = useState<Controller | null>(null);
  const [sheet, setSheet] = useState<Sheet>(null);
  const [conn, setConn] = useState(savedConnection);
  const [selected, setSelected] = useState("chief_of_staff");
  const [trayOpen, setTrayOpen] = useState(false);
  const [panels, setPanels] = useState<"none" | "docket" | "record">("none"); // phone only

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
    const timers: number[] = [];
    c.start().then(() => {
      if (live && feed.mode === "demo") {
        timers.push(window.setTimeout(() => feed.prompt("studio_lead", "Make a Sherlock reel on how AI agents use tools"), 900));
        timers.push(window.setTimeout(() => feed.prompt("sales_lead", "Find 20 companies hiring designers and draft pitch emails"), 3500));
      }
    });
    return () => { live = false; timers.forEach(clearTimeout); c.stop(); eng.dispose(); };
  }, [conn]);

  const close = useCallback(() => setSheet(null), []);
  const openSheet = useCallback((s: Sheet) => setSheet(s), []);

  useEffect(() => {
    if (!engine || !office) return;
    const all = everyone(office);
    engine.onPick = (p) => {
      if (p.task) { setSheet({ kind: "task", taskId: p.task }); return; }
      const e = all.find((x) => x.id === p.emp);
      if (!e) return;
      setSelected(e.id); setPanels((v) => (v === "none" ? v : "record"));
      if (e.promptable) setSheet({ kind: "prompt", emp: e });
    };
    engine.onHover = (id) => store.set({ hovered: id });
  }, [engine, office]);

  const connect = (url: string, token: string) => {
    try { localStorage.setItem("office.url", url); localStorage.setItem("office.token", token); } catch { /* private window */ }
    setConn({ url, token });
  };
  const disconnect = () => {
    try { localStorage.removeItem("office.token"); } catch { /* ignore */ }
    setConn(null);
  };

  return (
    <div id="app">
      <canvas id="office" ref={canvas} aria-label="3D office floor. Click Atlas or a department Lead to give a task." />
      <Labels engine={engine} />

      <Banner ctl={ctl} engine={engine} onTray={() => setTrayOpen(true)} onConnect={() => setSheet({ kind: "connect" })}
        onDisconnect={disconnect} onPanel={(p) => setPanels((v) => (v === p ? "none" : p))} />

      <FilingCabinet open={panels === "docket"} onTask={(id) => setSheet({ kind: "task", taskId: id })}
        onPerson={(id) => { setSelected(id); engine?.focusEmployee(id); }} />
      <PersonnelRecord open={panels === "record"} id={selected} engine={engine} onPrompt={(e) => setSheet({ kind: "prompt", emp: e })}
        onTask={(id) => setSheet({ kind: "task", taskId: id })} />
      <MemoBar ctl={ctl} />

      {error && <div className="error" role="alert">Couldn't load the office: {error}. Check the backend URL and token, or <button className="btn" onClick={disconnect}>switch to demo</button></div>}

      <InTray open={trayOpen} onClose={() => setTrayOpen(false)} ctl={ctl} onShow={(id) => { setTrayOpen(false); engine?.follow(id); }} />
      <Modal sheet={sheet} close={close} ctl={ctl} openSheet={openSheet} onFollow={(id) => engine?.follow(id)} onConnect={connect} />

      {loading && (
        <div className="loading" aria-busy="true">
          <div className="box amicro-skeleton">
            <p>Opening the office…</p>
            <Skeleton className="h-4 w-3/4" /><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-1/2" />
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- header banner
function Banner({ ctl, engine, onTray, onConnect, onDisconnect, onPanel }: {
  ctl: Controller | null; engine: OfficeEngine | null; onTray: () => void; onConnect: () => void; onDisconnect: () => void;
  onPanel: (p: "docket" | "record") => void;
}) {
  const office = useStore((s) => s.office);
  const conn = useStore((s) => s.conn), mode = useStore((s) => s.mode);
  const spent = useStore((s) => s.spent), budget = useStore((s) => s.budget);
  const pending = useStore((s) => s.approvals.length);
  const working = useStore((s) => Object.values(s.presence).filter((p) => p.state === "working").length);
  const paused = useStore((s) => s.paused), speed = useStore((s) => s.speed);
  const [clock, setClock] = useState(() => new Date());
  useEffect(() => { const t = setInterval(() => setClock(new Date()), 1000); return () => clearInterval(t); }, []);
  const pct = Math.min(1, spent / Math.max(1, budget));
  const headcount = everyone(office).length;
  const connText = mode === "demo" ? "Demo feed" : conn === "live" ? "Live wire" : conn === "reconnecting" ? "Reconnecting" : "Connecting";
  const floor = paused ? "Floor paused" : working ? `${working} at work` : "Quiet floor";
  return (
    <header className="banner">
      <div className="seal-row">
        <div className="seal" aria-hidden="true">{(office?.company && !office.company.startsWith("<") ? office.company : "Atlas")[0]}</div>
        <div>
          <h1>{office?.company && !office.company.startsWith("<") ? office.company : "Atlas & Co."}</h1>
          <p className="type">Autonomous dispatch division · {headcount} on staff</p>
        </div>
      </div>
      <div className="instruments">
        <div className="instrument">
          <span className="cap">Floor clock</span>
          <b>{clock.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</b>
        </div>
        <div className="instrument gauge-wrap" title="Claude plan credit used this month">
          <div className="gauge" aria-hidden="true"><i style={{ transform: `rotate(${-80 + pct * 160}deg)` }} /><s /></div>
          <div><span className="cap">Op. budget</span><b>${spent.toFixed(2)} <small>/ ${budget.toFixed(0)}</small></b></div>
        </div>
        <div className="instrument cond">
          <span className="amicro-live" data-conn={mode === "demo" ? "demo" : conn}><PulseDot /></span>
          <div><span className="cap">{connText}</span><b>{floor}</b></div>
          {working > 0 && !paused && <span className="amicro-island"><DynamicIsland /></span>}
        </div>
      </div>
      <div className="banner-actions">
        <button className="btn tray" onClick={onTray}>In-tray <span className="badge" data-n={pending}>{pending}</span></button>
        <select className="btn select" aria-label="Camera" defaultValue="all" onChange={(e) => engine?.focus(e.target.value)}>
          <option value="all">Floor: panoramic</option>
          <option value="hq">Executive suite</option>
          {office?.departments.map((d) => <option key={d.id} value={d.id}>Bullpen: {deptLabel(d.id)}</option>)}
          <option value="owner">Your desk</option>
        </select>
        {mode === "demo" && <button className="btn" onClick={() => ctl?.setSpeed(speed === 1 ? 2 : speed === 2 ? 4 : 1)}>Speed {speed}×</button>}
        <button className="btn" onClick={() => ctl?.togglePause()}>{paused ? "Resume floor" : "Pause floor"}</button>
        <button className="btn" onClick={mode === "demo" ? onConnect : onDisconnect}>{mode === "demo" ? "Connect backend" : "Use demo"}</button>
        <button className="btn phone-only" onClick={() => onPanel("docket")}>Docket</button>
        <button className="btn phone-only" onClick={() => onPanel("record")}>Record</button>
      </div>
    </header>
  );
}

// ---------------------------------------------------------------- left: filing cabinet (open tasks + log)
function FilingCabinet({ open, onTask, onPerson }: { open: boolean; onTask: (id: string) => void; onPerson: (id: string) => void }) {
  const office = useStore((s) => s.office);
  const tasks = useStore((s) => s.tasks);
  const feed = useStore((s) => s.feed);
  const [filter, setFilter] = useState("all");
  const [tab, setTab] = useState<"docket" | "log">("docket");
  const names = useMemo(() => Object.fromEntries(everyone(office).map((e) => [e.id, e.name])), [office]);
  const list = Object.values(tasks).filter((t) => filter === "all" || t.department === filter)
    .sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
  return (
    <aside className="cabinet panel" data-open={open} aria-label="Active docket">
      <div className="carbon panel-head">
        <h2>{tab === "docket" ? "Active docket" : "Floor log"}</h2>
        <div className="seg">
          <button aria-pressed={tab === "docket"} onClick={() => setTab("docket")}>Docket</button>
          <button aria-pressed={tab === "log"} onClick={() => setTab("log")}>Log</button>
        </div>
      </div>
      {tab === "docket" && (
        <div className="ribbons">
          <button aria-pressed={filter === "all"} onClick={() => setFilter("all")}>All</button>
          <button aria-pressed={filter === "hq"} onClick={() => setFilter("hq")}>Exec</button>
          {office?.departments.map((d) => (
            <button key={d.id} aria-pressed={filter === d.id} onClick={() => setFilter(d.id)}>{d.id.slice(0, 5)}</button>
          ))}
        </div>
      )}
      <div className="panel-body">
        {tab === "docket" && list.length === 0 && <p className="empty">No open files. Dictate a memo below, or click Atlas or a Lead's desk.</p>}
        {tab === "docket" && list.map((t) => (
          <button key={t.id} className="docket-card" onClick={() => onTask(t.id)}>
            <span className="row">
              <span className="who" onClick={(e) => { if (t.holder && t.holder !== "owner") { e.stopPropagation(); onPerson(t.holder); } }}>
                {t.holder ? (t.holder === "owner" ? "On your desk" : `With ${names[t.holder] ?? t.holder}`) : "In transit"}
              </span>
              <span className="tag">{t.status.replace(/_/g, " ")}</span>
            </span>
            <span className="memo-text">{t.request}</span>
            <span className="foot">{deptLabel(t.department)}{t.parent_id ? " · sub-task" : ""} · ${(t.cost_usd ?? 0).toFixed(2)}</span>
          </button>
        ))}
        {tab === "log" && feed.length === 0 && <p className="empty">Every handoff, wake-up and delivery is logged here.</p>}
        {tab === "log" && feed.map((l) => (
          <div key={l.id} className={"log-line" + (l.walk ? " walk" : "")}><time>{l.at}</time><div dangerouslySetInnerHTML={{ __html: l.html }} /></div>
        ))}
      </div>
      <div className="panel-foot"><span>Click a file to open it</span><b>{list.length} open</b></div>
    </aside>
  );
}

// ---------------------------------------------------------------- right: personnel record
function PersonnelRecord({ open, id, engine, onPrompt, onTask }: {
  open: boolean; id: string; engine: OfficeEngine | null; onPrompt: (e: Employee) => void; onTask: (id: string) => void;
}) {
  const office = useStore((s) => s.office);
  const p = useStore((s) => s.presence[id]);
  const walking = useStore((s) => !!s.walking[id]);
  const task = useStore((s) => (p?.task_id ? s.tasks[p.task_id] : undefined));
  const e = everyone(office).find((x) => x.id === id);
  if (!office || !e) return null;
  const deptIdx = office.departments.findIndex((d) => d.id === e.department);
  const lead = office.departments.find((d) => d.id === e.department)?.lead;
  const initials = e.name.split(/[-\s]/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  const state = walking ? "Walking a note" : STATE_TEXT[p?.state ?? "sleeping"];
  return (
    <aside className="record panel" data-open={open} aria-label="Personnel record">
      <div className="panel-head clip"><h2>Personnel record</h2><span className="stamp-tag">{e.kind === "specialist" ? "Staff" : e.kind === "lead" ? "Lead" : "Executive"}</span></div>
      <div className="id-card">
        <div className="mug" style={{ background: e.department === "hq" ? "var(--brass)" : hex(deptColor(e.department, deptIdx)) }}>{initials}</div>
        <div className="min0">
          <h3>{e.name}</h3>
          <div className="role">{e.role[0] ?? ""}</div>
          <div className="dept">{deptLabel(e.department)}</div>
        </div>
      </div>
      <dl className="ledger">
        <dt>Status</dt><dd data-s={walking ? "walking" : p?.state ?? "sleeping"}>{state}{p?.phase && !walking ? ` · ${p.phase}` : ""}</dd>
        <dt>Assignment</dt><dd>{task ? <button className="linkish" onClick={() => onTask(task.id)}>{task.request}</button> : "None"}</dd>
        <dt>Reports to</dt><dd>{e.kind === "specialist" ? lead?.name : e.kind === "lead" ? "Atlas" : "You"}</dd>
        {e.does_not?.length ? <><dt>Won't</dt><dd>{e.does_not.slice(0, 2).join("; ")}</dd></> : null}
      </dl>
      {e.role.length > 1 && <p className="duties">Duties: {e.role.slice(0, 4).join(" · ")}</p>}
      <div className="record-actions">
        <button className="btn" onClick={() => engine?.focusEmployee(e.id)}>Center desk</button>
        {e.promptable
          ? <button className="btn primary" onClick={() => onPrompt(e)}>Give {e.name} a task</button>
          : lead && <button className="btn" onClick={() => onPrompt(lead)}>Ask {lead.name} instead</button>}
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------- bottom: memo bar
function MemoBar({ ctl }: { ctl: Controller | null }) {
  const office = useStore((s) => s.office);
  const [text, setText] = useState("");
  const [to, setTo] = useState("chief_of_staff");
  const [state, setState] = useState<"idle" | "sending" | "sent" | string>("idle");
  const addressees = office ? [office.core.chief_of_staff, ...office.departments.map((d) => d.lead)].filter(Boolean) : [];
  const send = async () => {
    const v = text.trim();
    if (!v || !ctl) return;
    setState("sending");
    try { await ctl.prompt(to, v); setText(""); setState("sent"); setTimeout(() => setState("idle"), 2500); }
    catch (e) { setState((e as Error).message); }
  };
  return (
    <form className="memobar" onSubmit={(e) => { e.preventDefault(); send(); }}>
      <label htmlFor="memo-text" className="type memo-label">Office memorandum:</label>
      <input id="memo-text" className="field" value={text} onChange={(e) => setText(e.target.value)}
        placeholder="Dictate a task for Atlas or a department Lead…" />
      <select id="memo-to" className="field select" value={to} onChange={(e) => setTo(e.target.value)} aria-label="Addressee">
        {addressees.map((e) => <option key={e.id} value={e.id}>To: {e.name} ({e.department === "hq" ? "Chief of Staff" : `${deptLabel(e.department)} Lead`})</option>)}
      </select>
      <button className="btn primary" disabled={!text.trim() || state === "sending"}>{state === "sending" ? "Sending…" : state === "sent" ? "Sent" : "Transmit"}</button>
      {state !== "idle" && state !== "sending" && state !== "sent" && <span className="form-err">Couldn't send: {state}</span>}
    </form>
  );
}

// ---------------------------------------------------------------- in-tray: manila memos with rubber stamps
function InTray({ open, onClose, ctl, onShow }: { open: boolean; onClose: () => void; ctl: Controller | null; onShow: (taskId: string) => void }) {
  const approvals = useStore((s) => s.approvals);
  const [i, setI] = useState(0);
  const [stamp, setStamp] = useState<null | "approved" | "returned">(null);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  if (!open) return null;
  const idx = Math.min(i, Math.max(0, approvals.length - 1));
  const a = approvals[idx];
  return (
    <div className="sheet" onPointerDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="manila" role="dialog" aria-modal="true" aria-label="In-tray">
        <div className="folder-tab type">Confidential memorandum · pending authorization</div>
        <button className="x" aria-label="Close" onClick={onClose}>×</button>
        {!a && <p className="empty">Your in-tray is empty. Memos land here when a Lead needs your signature.</p>}
        <AnimatePresence mode="wait">
          {a && (
            <motion.div key={a.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}>
              <Memo a={a} ctl={ctl} onShow={onShow} onStamped={(s) => { setStamp(s); setTimeout(() => setStamp(null), 900); }} />
            </motion.div>
          )}
        </AnimatePresence>
        <AnimatePresence>
          {stamp && (
            <motion.div className={"big-stamp " + stamp} initial={{ scale: 2.2, opacity: 0, rotate: -18 }} animate={{ scale: 1, opacity: 0.9, rotate: -9 }} exit={{ opacity: 0 }}
              transition={{ type: "spring", stiffness: 500, damping: 22 }}>{stamp === "approved" ? "Authorized" : "Returned"}</motion.div>
          )}
        </AnimatePresence>
        {approvals.length > 1 && (
          <div className="tray-nav type">
            <button className="btn" onClick={() => setI((idx - 1 + approvals.length) % approvals.length)}>‹ Prev</button>
            Memo {idx + 1} of {approvals.length}
            <button className="btn" onClick={() => setI((idx + 1) % approvals.length)}>Next ›</button>
          </div>
        )}
      </div>
    </div>
  );
}

function Memo({ a, ctl, onShow, onStamped }: { a: Approval; ctl: Controller | null; onShow: (taskId: string) => void; onStamped: (s: "approved" | "returned") => void }) {
  const office = useStore((s) => s.office);
  const task = useStore((s) => s.tasks[a.task_id]);
  const from = everyone(office).find((e) => e.id === a.employee_id)?.name;
  const artifacts = (a.preview?.artifacts as string[] | undefined) ?? [];
  const mem = (a.preview?.memory_candidates as { id: string; text: string }[] | undefined) ?? [];
  const [ticks, setTicks] = useState<string[]>(() => mem.map((m) => m.id));
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const act = async (approve: boolean) => {
    try { onStamped(approve ? "approved" : "returned"); await ctl?.decide(a.id, approve, reason, ticks); } catch (e) { setErr((e as Error).message); }
  };
  return (
    <>
      <div className="carbon memo-head type">
        <span>Memo ref: {a.id.slice(-6).toUpperCase()}</span>
        <span>{new Date().toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })}</span>
      </div>
      <h3 className="memo-subject">{GATE_TEXT[a.gate] ?? a.gate}{a.title && !/^(Contract|Plan|Accept delivery\?)/.test(a.title) ? `: ${a.title}` : ""}</h3>
      <div className="memo-body type">
        <p><b>Originator:</b> {from ?? "The floor"}</p>
        <p><b>Subject:</b> {task?.request ?? a.title}</p>
        {a.summary && <div className="excerpt">{a.summary.replace(/[*_`]/g, "")}</div>}
        {artifacts.length > 0 && <p><b>Enclosures:</b> {artifacts.join(", ")}</p>}
        {mem.map((m) => (
          <label key={m.id} className="tick">
            <input type="checkbox" id={`mem-${a.id}-${m.id}`} checked={ticks.includes(m.id)}
              onChange={(e) => setTicks((t) => (e.target.checked ? [...t, m.id] : t.filter((x) => x !== m.id)))} />
            File in company memory: {m.text}
          </label>
        ))}
        {rejecting && <input id={`reason-${a.id}`} className="field" autoFocus placeholder="Return slip: what should change?" value={reason}
          onChange={(e) => setReason(e.target.value)} aria-label="Reason for returning" />}
        {err && <p className="form-err">{err}</p>}
      </div>
      <div className="stamps">
        <button className="btn ghost" onClick={() => onShow(a.task_id)}>Show the note</button>
        {rejecting
          ? <button className="stamp-btn reject" onClick={() => act(false)}>Send return slip</button>
          : <button className="stamp-btn reject" onClick={() => setRejecting(true)}>Reject / return</button>}
        {!rejecting && <button className="stamp-btn approve" onClick={() => act(true)}>{a.gate === "G4" ? "Stamp accepted" : "Stamp authorized"}</button>}
      </div>
    </>
  );
}
