import type { OfficeEngine } from "../office/engine";
import { KeyedQueue } from "./scheduler";
import { store, type FeedLine } from "./store";
import type { Feed, LiveEvent, Presence, Snapshot } from "./types";

const KIND_TEXT: Record<string, string> = {
  request: "new task", subtask: "sub-task", approval_request: "needs your approval", approved: "approved", rejected: "sent back",
  assign: "assigned", return: "handed back", for_verification: "for checking", verdict: "verdict", for_factcheck: "for fact-checking", factcheck_result: "fact check", delivery: "delivery",
  escalation: "escalated", subtask_done: "part done",
};
const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
const clock = () => new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }).slice(0, 8);

/** Wires a Feed (live backend or demo) to the 3D engine and the UI store, playing events in order. */
export class Controller {
  private q = new KeyedQueue();
  private lastSeq = 0;
  private unsub: (() => void) | null = null;
  private lineId = 0;
  private bubbleTimer = 0;
  private names = new Map<string, string>();
  private namesFor: unknown = null;
  private decided = new Set<string>();
  private backlog = 0;

  constructor(public feed: Feed, private engine: OfficeEngine) {}

  async start() {
    store.set({ loading: true, error: null, mode: this.feed.mode });
    try {
      const office = await this.feed.office();
      this.engine.build(office);
      this.engine.onWalking = (id, w) => store.set((s) => ({ walking: { ...s.walking, [id]: w } }));
      store.set({ office, budget: office.monthly_budget_usd });
      await this.loadSnapshot();
      store.set({ loading: false });
    } catch (e) {
      store.set({ loading: false, error: (e as Error).message });
    }
  }

  stop() { this.unsub?.(); this.unsub = null; }

  private name(id: string | null | undefined) {
    if (!id) return "System";
    if (id === "owner") return "You";
    const o = store.get().office;
    if (!o) return id;
    if (this.namesFor !== o) {   // rebuilt only when the roster changes, not on every event
      this.namesFor = o;
      this.names = new Map([...Object.values(o.core), ...o.departments.flatMap((d) => [d.lead, ...d.specialists])].map((e) => [e.id, e.name]));
    }
    return this.names.get(id) ?? id;
  }

  private async loadSnapshot() {
    this.unsub?.();
    this.q.clear();
    const snap: Snapshot = await this.feed.state();
    this.engine.clearNotes();
    const presence: Record<string, { state: Presence; phase: string | null; task_id: string | null }> = {};
    for (const [id, p] of Object.entries(snap.presence)) { presence[id] = p; this.engine.setPresence(id, p.state); }
    const tasks: Record<string, any> = {};
    for (const t of snap.open_tasks) {
      tasks[t.id] = { ...t, log: [] };
      this.engine.createNote(t.id, t.department, t.holder ?? "owner");
    }
    store.set({ presence, tasks, approvals: snap.pending_approvals, spent: snap.month_spent_usd, budget: snap.month_budget_usd,
      paused: snap.pauses.some((p) => p.scope === "all") });
    this.lastSeq = snap.seq;
    this.unsub = this.feed.subscribe(snap.seq, (ev) => this.onEvent(ev), (conn) => store.set({ conn }));
  }

  private line(html: string, taskId: string | null, walk = false) {
    const l: FeedLine = { id: ++this.lineId, at: clock(), html, walk, taskId };
    store.set((s) => {
      const tasks = { ...s.tasks };
      if (taskId && tasks[taskId]) tasks[taskId] = { ...tasks[taskId], log: [...tasks[taskId].log, { at: l.at, html }].slice(-60) };
      return { feed: [l, ...s.feed].slice(0, 120), tasks };
    });
  }

  /** One speech bubble on screen at a time, and only from Leads, Atlas and Vera. */
  /** The task's plan as steps, built from the walks: an assignment starts a step, its return finishes it. */
  private step(taskId: string, d: Record<string, any>) {
    const start: Record<string, [string, string]> = { assign: [d.to, d.step ?? d.to], for_factcheck: ["fact_checker", "proof"], for_verification: ["verifier", "vera"] };
    const end: Record<string, [string, boolean]> = { return: [d.step ?? d.from, d.checks_passed !== false],
      factcheck_result: ["proof", d.passed !== false], verdict: ["vera", d.passed !== false] };
    store.set((s) => {
      const t = s.tasks[taskId]; if (!t) return {};
      const steps = [...(t.steps ?? [])];
      if (start[d.kind]) {
        const [who, id] = start[d.kind];
        const label = d.kind === "assign" ? `${this.name(who)}: ${String(d.task_type ?? d.note ?? "").replace(/_/g, " ").slice(0, 60)}`
          : d.kind === "for_factcheck" ? "Proof checks the facts" : "Vera checks against the brief";
        const i = steps.findIndex((x) => x.id === id);
        const row = { id, label, status: "running" as const, note: d.attempt > 1 ? `try ${d.attempt}` : undefined };
        if (i >= 0) steps[i] = row; else steps.push(row);
      } else if (end[d.kind]) {
        const [id, ok] = end[d.kind];
        const i = steps.findIndex((x) => x.id === id);
        if (i >= 0) steps[i] = { ...steps[i], status: ok ? "done" : "failed" };
      } else return {};
      return { tasks: { ...s.tasks, [taskId]: { ...t, steps } } };
    });
  }

  private bubble(id: string, text: string) {
    const o = store.get().office;
    const emp = o && [...Object.values(o.core), ...o.departments.map((d) => d.lead)].find((e) => e.id === id);
    if (!emp || !["lead", "router", "verifier"].includes(emp.kind)) return;
    store.set({ bubbles: { [id]: { id: this.lineId + Math.random(), text } } });
    clearTimeout(this.bubbleTimer);
    this.bubbleTimer = window.setTimeout(() => store.set({ bubbles: {} }), 4200);
  }

  private onEvent(ev: LiveEvent) {
    if (ev.type === "resync") { this.loadSnapshot().catch((e) => store.set({ error: String(e) })); return; }
    if (ev.seq <= this.lastSeq) return;
    this.lastSeq = ev.seq;
    if (ev.type === "handoff") this.catchUp(+1);
    const d = ev.data, t = ev.task_id;
    const T = t ? [`t:${t}`] : [];
    switch (ev.type) {
      case "task.created":
        this.q.run(T, () => {
          store.set((s) => ({ tasks: { ...s.tasks, [t!]: { id: t!, parent_id: d.parent_id, department: d.department, status: "RECEIVED",
            size: null, request: d.request, objective: d.request, holder: null, cost_usd: 0, log: [] } } }));
          this.engine.createNote(t!, d.department, d.parent_id ? "chief_of_staff" : "owner");
        });
        break;
      case "handoff":
        this.q.run([...T, `e:${d.from}`, `e:${d.to}`], async (release) => {
          if (!this.engine.hasNote(t!)) {
            const dept = store.get().tasks[t!]?.department ?? "hq";
            this.engine.createNote(t!, dept, d.from);
          }
          this.line(`<b>${esc(this.name(d.from))} → ${esc(this.name(d.to))}</b> · ${KIND_TEXT[d.kind] ?? esc(d.kind)}${d.note ? `: ${esc(String(d.note).slice(0, 90))}` : ""}`, t, true);
          this.step(t!, d);
          const { delivered, returned } = this.engine.handoff(t!, d.from, d.to);
          await delivered;
          store.set((s) => (s.tasks[t!] ? { tasks: { ...s.tasks, [t!]: { ...s.tasks[t!], holder: d.to } } } : {}));
          release[`t:${t}`]?.(); release[`e:${d.to}`]?.();
          await returned;
          this.catchUp(-1);
        });
        break;
      case "employee.state": {
        const id = d.employee_id as string;
        // a wake-up for a task waits until that task's note has arrived
        const keys = [`e:${id}`, ...(d.state === "working" && t ? T : [])];
        this.q.run(keys, () => {
          this.engine.setPresence(id, d.state);
          store.set((s) => ({ presence: { ...s.presence, [id]: { state: d.state, phase: d.phase ?? null, task_id: t } } }));
          if (d.state === "working" && d.previous === "sleeping") this.line(`<b>${esc(this.name(id))}</b> woke up (${esc(d.phase)})`, t);
        });
        break;
      }
      case "task.status":
        this.q.run(T, async () => {
          store.set((s) => (s.tasks[t!] ? { tasks: { ...s.tasks, [t!]: { ...s.tasks[t!], status: d.to } } } : {}));
          if (d.to === "CLOSED" || d.to === "CANCELLED") {
            await this.engine.removeNote(t!);
            store.set((s) => { const tasks = { ...s.tasks }; delete tasks[t!]; return { tasks }; });
          }
        });
        break;
      case "approval.requested":
        // lands in the inbox when the note's earlier walks have played, so the card never beats the note
        this.q.run(T, () => {
          if (this.decided.has(d.approval_id)) return;
          store.set((s) => ({ approvals: [...s.approvals.filter((a) => a.id !== d.approval_id), { id: d.approval_id, task_id: t!, gate: d.gate,
            employee_id: d.employee_id, action_hash: d.action_hash, title: d.title, summary: d.summary,
            preview: { artifacts: d.artifacts, memory_candidates: d.memory_candidates } }] }));
        });
        break;
      case "approval.decided":
        this.decided.add(d.approval_id);
        store.set((s) => ({ approvals: s.approvals.filter((a) => a.id !== d.approval_id) }));
        break;
      case "message":
        this.q.run(d.employee_id ? [`e:${d.employee_id}`] : [], () => {
          if (d.employee_id) this.bubble(d.employee_id, String(d.text).replace(/[*_`]/g, "").slice(0, 140));
          this.line(`<b>${esc(this.name(d.employee_id))}:</b> ${esc(String(d.text).replace(/[*_`]/g, "").slice(0, 160))}`, t);
        });
        break;
      case "artifact.created":
        this.q.run(T, () => { this.engine.pop(d.employee_id); this.line(`<b>${esc(this.name(d.employee_id))}</b> made <span class="tag">${esc(d.name)}</span>`, t); });
        break;
      case "cost":
        store.set({ spent: d.month_spent_usd });
        if (t) store.set((s) => (s.tasks[t] ? { tasks: { ...s.tasks, [t]: { ...s.tasks[t], cost_usd: d.task_cost_usd } } } : {}));
        break;
    }
  }

  // ------------------------------------------------------------------ owner actions
  async prompt(empId: string, text: string) { return this.feed.prompt(empId, text); }
  async reply(taskId: string, text: string) { return this.feed.reply(taskId, text); }
  async decide(id: string, approve: boolean, reason = "", ticks: string[] = []) {
    const a = store.get().approvals.find((x) => x.id === id);
    await this.feed.decide(id, { approve, reason, memory_ticks: ticks, action_hash: a?.action_hash ?? null });
  }
  async togglePause() {
    const paused = !store.get().paused;
    const msg = await this.feed.command(paused ? "pause-all" : "resume all");
    store.set({ paused });
    return msg;
  }
  setSpeed(x: number) { store.set({ speed: x }); this.applySpeed(); this.feed.setSpeed?.(x); }

  /** When walks pile up behind the backend, play them faster so the office stays close to real time. */
  private catchUp(delta: number) { this.backlog = Math.max(0, this.backlog + delta); this.applySpeed(); }
  private applySpeed() { this.engine.setSpeed(store.get().speed * Math.min(4, 1 + Math.max(0, this.backlog - 1) * 0.75)); }
}
