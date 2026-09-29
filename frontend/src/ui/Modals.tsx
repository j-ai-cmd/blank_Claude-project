import { useEffect, useRef, useState } from "react";
import type { Controller } from "../lib/controller";
import { useStore } from "../lib/store";
import type { Employee } from "../lib/types";
import { deptColor } from "../office/engine";

export type Sheet =
  | { kind: "prompt"; emp: Employee }
  | { kind: "profile"; emp: Employee }
  | { kind: "task"; taskId: string }
  | { kind: "connect" }
  | null;

const SUGGEST: Record<string, string[]> = {
  chief_of_staff: ["Pitch Acme a promo video: proposal plus a 30s sample", "Build me a portfolio page and a script for its launch reel"],
  studio_lead: ["Make a Sherlock reel on how AI agents use tools", "Make a Striker reel on this week's ISL top scorer"],
  sales_lead: ["Find 20 companies hiring designers and draft pitch emails", "Tailor my CV and cover letter for this job post"],
  talent_lead: ["Design a new employee who edits podcasts", "Propose a customer-support employee"],
  eng_lead: ["Build a landing page for my portfolio", "Set up a Make automation that logs new invoices"],
  ops_lead: ["Sort last month's bank statement into income and expenses", "Weekly report: pitches sent and replies"],
};
const STATE_TEXT: Record<string, string> = { sleeping: "Asleep", working: "Working", supervising: "Supervising", waiting_owner: "Waiting on you", blocked: "Blocked", paused: "Paused" };

function hex(n: number) { return "#" + n.toString(16).padStart(6, "0"); }
function colorOf(e: Employee, deptIds: string[]) { return e.department === "hq" ? "var(--core)" : hex(deptColor(e.department, deptIds.indexOf(e.department))); }

export function Modal({ sheet, close, ctl, openSheet, onFollow, onConnect }: {
  sheet: Sheet; close: () => void; ctl: Controller | null; openSheet: (s: Sheet) => void;
  onFollow: (taskId: string) => void; onConnect: (url: string, token: string) => void;
}) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [close]);
  if (!sheet) return null;
  return (
    <div className="sheet" onPointerDown={(e) => { if (e.target === e.currentTarget) close(); }}>
      <div className="modal" role="dialog" aria-modal="true">
        {sheet.kind === "prompt" && <Prompt emp={sheet.emp} ctl={ctl} close={close} />}
        {sheet.kind === "profile" && <Profile emp={sheet.emp} close={close} openSheet={openSheet} />}
        {sheet.kind === "task" && <TaskView taskId={sheet.taskId} ctl={ctl} close={close} onFollow={onFollow} />}
        {sheet.kind === "connect" && <Connect close={close} onConnect={onConnect} />}
      </div>
    </div>
  );
}

function Header({ emp }: { emp: Employee }) {
  const office = useStore((s) => s.office);
  const depts = office?.departments.map((d) => d.id) ?? [];
  return (
    <header>
      <div className="avatar" style={{ background: colorOf(emp, depts) }}>{emp.name[0]}</div>
      <div><h2>{emp.name}</h2><div className="sub">{emp.role.slice(0, 3).join(" · ")}</div></div>
    </header>
  );
}

function Prompt({ emp, ctl, close }: { emp: Employee; ctl: Controller | null; close: () => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const ta = useRef<HTMLTextAreaElement>(null);
  useEffect(() => ta.current?.focus(), []);
  const send = async () => {
    const v = text.trim();
    if (!v) { ta.current?.focus(); return; }
    setBusy(true); setErr(null);
    try { await ctl?.prompt(emp.id, v); close(); } catch (e) { setErr((e as Error).message); setBusy(false); }
  };
  const team = emp.kind === "router" ? "Atlas splits it across departments and walks a note to each Lead."
    : `${emp.name} decides who on the team does it, and wakes them up.`;
  return (
    <>
      <header>
        <div className="avatar" style={{ background: "var(--note)" }}>{emp.name[0]}</div>
        <div><h2>Give {emp.name} a task</h2><div className="sub">{emp.role[0]}</div></div>
      </header>
      <p className="muted">{team}</p>
      <textarea id="prompt-text" ref={ta} className="field" placeholder="What do you need?" value={text} onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send(); }} aria-label={`Task for ${emp.name}`} />
      <div className="sugs">{(SUGGEST[emp.id] ?? []).map((s) => <button key={s} type="button" onClick={() => setText(s)}>{s}</button>)}</div>
      {err && <p className="form-err">Couldn't send it: {err}</p>}
      <div className="row">
        <button className="btn" onClick={close}>Cancel</button>
        <button className="btn primary" onClick={send} disabled={busy}>{busy ? "Sending…" : "Hand over the note"}</button>
      </div>
    </>
  );
}

function Profile({ emp, close, openSheet }: { emp: Employee; close: () => void; openSheet: (s: Sheet) => void }) {
  const p = useStore((s) => s.presence[emp.id]);
  const walking = useStore((s) => !!s.walking[emp.id]);
  const task = useStore((s) => (p?.task_id ? s.tasks[p.task_id] : undefined));
  const lead = useStore((s) => s.office?.departments.find((d) => d.id === emp.department)?.lead);
  const deptName = emp.department === "hq" ? "Head table" : emp.department;
  return (
    <>
      <Header emp={emp} />
      <dl className="kv">
        <dt>State</dt><dd>{walking ? "Walking a note" : STATE_TEXT[p?.state ?? "sleeping"]}{p?.phase ? ` (${p.phase})` : ""}</dd>
        <dt>Department</dt><dd style={{ textTransform: "capitalize" }}>{deptName}</dd>
        <dt>Current task</dt><dd>{task ? task.request : "None"}</dd>
      </dl>
      {emp.does_not?.length ? <p className="muted">Won't: {emp.does_not.join("; ")}</p> : null}
      <p className="muted">{lead && emp.kind === "specialist" ? `You don't assign work to ${emp.name} directly. ${lead.name} does.` : `${emp.name} works automatically when a task needs them.`}</p>
      <div className="row">
        {lead && emp.kind === "specialist" && <button className="btn" onClick={() => openSheet({ kind: "prompt", emp: lead })}>Give {lead.name} a task</button>}
        <button className="btn primary" onClick={close}>Close</button>
      </div>
    </>
  );
}

function TaskView({ taskId, ctl, close, onFollow }: { taskId: string; ctl: Controller | null; close: () => void; onFollow: (id: string) => void }) {
  const t = useStore((s) => s.tasks[taskId]);
  const holderName = useStore((s) => {
    const h = t?.holder; if (!h) return "—"; if (h === "owner") return "You";
    const o = s.office; if (!o) return h;
    return [...Object.values(o.core), ...o.departments.flatMap((d) => [d.lead, ...d.specialists])].find((e) => e.id === h)?.name ?? h;
  });
  const [reply, setReply] = useState("");
  const [sent, setSent] = useState(false);
  if (!t) return (<><p>This task is finished.</p><div className="row"><button className="btn primary" onClick={close}>Close</button></div></>);
  return (
    <>
      <header>
        <div className="avatar" style={{ background: "var(--note)" }}>✉</div>
        <div><h2>{t.request.slice(0, 90)}</h2><div className="sub">{t.id} · {t.department}</div></div>
      </header>
      <dl className="kv">
        <dt>Status</dt><dd><span className="tag">{t.status}</span></dd>
        <dt>Note is with</dt><dd>{holderName}</dd>
        <dt>Cost</dt><dd>${(t.cost_usd ?? 0).toFixed(2)}</dd>
      </dl>
      {t.log.length > 0 && <ol className="tl">{t.log.slice(-14).map((l, i) => <li key={i}><time>{l.at}</time><span dangerouslySetInnerHTML={{ __html: l.html }} /></li>)}</ol>}
      {!t.parent_id && (
        <div className="card">
          <label htmlFor="reply-text" className="muted">Tell the Lead something (answers a question or changes direction)</label>
          <input id="reply-text" className="field" value={reply} onChange={(e) => { setReply(e.target.value); setSent(false); }} placeholder="e.g. keep it under 20 words" />
          <div className="acts">
            <button className="btn" disabled={!reply.trim()} onClick={async () => { await ctl?.reply(t.id, reply.trim()); setReply(""); setSent(true); }}>Send</button>
            {sent && <span className="muted">Sent.</span>}
          </div>
        </div>
      )}
      <div className="row">
        <button className="btn" onClick={() => { onFollow(t.id); close(); }}>Follow this note</button>
        <button className="btn primary" onClick={close}>Close</button>
      </div>
    </>
  );
}

function Connect({ close, onConnect }: { close: () => void; onConnect: (url: string, token: string) => void }) {
  const [url, setUrl] = useState(() => { try { return localStorage.getItem("office.url") || import.meta.env.VITE_API_URL || ""; } catch { return ""; } });
  const [token, setToken] = useState("");
  return (
    <>
      <header><div className="avatar" style={{ background: "var(--ok)" }}>⇄</div><div><h2>Connect to your office</h2><div className="sub">The workforce backend's URL and its API token</div></div></header>
      <label className="muted" htmlFor="api-url">Backend URL</label>
      <input id="api-url" className="field" placeholder="https://workforce.example.com" value={url} onChange={(e) => setUrl(e.target.value)} />
      <label className="muted" htmlFor="api-token">API token (WORKFORCE_API_TOKEN)</label>
      <input id="api-token" className="field" type="password" value={token} onChange={(e) => setToken(e.target.value)} />
      <p className="muted">Saved in this browser only.</p>
      <div className="row">
        <button className="btn" onClick={close}>Cancel</button>
        <button className="btn primary" disabled={!url.trim() || !token.trim()} onClick={() => { onConnect(url.trim(), token.trim()); close(); }}>Connect</button>
      </div>
    </>
  );
}
