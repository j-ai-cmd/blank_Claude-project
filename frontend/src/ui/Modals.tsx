import { useEffect, useRef, useState } from "react";
import AISuggestions from "../components/smoothui/ai-suggestions";
import AITaskList from "../components/smoothui/ai-task-list";
import type { Controller } from "../lib/controller";
import { useStore } from "../lib/store";
import type { Employee } from "../lib/types";

export type Sheet =
  | { kind: "prompt"; emp: Employee }
  | { kind: "task"; taskId: string }
  | { kind: "connect" }
  | null;

const SUGGEST: Record<string, string[]> = {
  chief_of_staff: ["Sherlock reel on AI agents, plus a pitch email offering one to Acme", "Recruit an employee who edits my podcast"],
  studio_lead: ["Sherlock, make a reel on how AI agents use tools", "Football reel from my script and voiceover on this week's ISL top scorer"],
  sales_lead: ["Find 20 jobs that fit me and write cover letters", "Write a pitch email in my voice to Acme"],
  eng_lead: ["Fix the login bug in the office app", "Company work: a Power Automate flow that posts new rows to Teams"],
  ops_lead: ["Sort last month's bank statement into income and expenses", "Weekly report: pitches sent and replies"],
};


export function Modal({ sheet, close, ctl, onFollow, onConnect }: {
  sheet: Sheet; close: () => void; ctl: Controller | null;
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
        {sheet.kind === "task" && <TaskView taskId={sheet.taskId} ctl={ctl} close={close} onFollow={onFollow} />}
        {sheet.kind === "connect" && <Connect close={close} onConnect={onConnect} />}
      </div>
    </div>
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
      <AISuggestions className="sm-sugs" label="Try one" onSelect={(s) => { setText(s.label); ta.current?.focus(); }}
        suggestions={(SUGGEST[emp.id] ?? []).map((label) => ({ id: label, label }))} />
      {err && <p className="form-err">Couldn't send it: {err}</p>}
      <div className="row">
        <button className="btn" onClick={close}>Cancel</button>
        <button className="btn primary" onClick={send} disabled={busy}>{busy ? "Sending…" : "Hand over the note"}</button>
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
      {(t.steps?.length ?? 0) > 0 && <AITaskList className="sm-plan" label="Who's doing what" tasks={t.steps!} />}
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
