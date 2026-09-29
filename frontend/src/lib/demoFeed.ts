import officeJson from "./demoOffice.json";
import type { Approval, ConnState, Decision, Feed, LiveEvent, Office, Presence, Snapshot, TaskSummary } from "./types";

/**
 * An in-browser stand-in for the backend. It emits the same events, in the same order and with the
 * same presence rules as workforce/live.py, so the office can be tried without a server.
 */
const OFFICE = officeJson as unknown as Office;

const SUPERVISED = new Set(["CONTRACT_APPROVED", "PLANNED", "IN_PROGRESS", "VERIFYING", "REVISION"]);

const PICK: Record<string, [RegExp, string][]> = {
  marketing: [[/video|edit|teaser|b-roll/i, "mkt_video_editor"], [/reel|instagram|sherlock|jai|peter/i, "mkt_personal_reels"],
    [/caption|copy|headline|email|script/i, "mkt_copywriter"], [/graphic|image|thumbnail|banner|\bad\b|visual/i, "mkt_graphic_designer"],
    [/seo|blog|keyword/i, "mkt_seo_content"], [/post|schedule|social|linkedin|calendar/i, "mkt_social_manager"],
    [/number|report|analytics|performance/i, "mkt_analyst"]],
  sales: [[/lead|list|prospect|icp/i, "sales_prospector"], [/research|account|competitor|call prep|brief/i, "sales_researcher"],
    [/email|outreach|message|follow/i, "sales_outreach_writer"], [/crm|note|dedupe/i, "sales_crm_keeper"],
    [/proposal|pricing|one-pager/i, "sales_proposal_writer"]],
  recruiting: [[/jd|job description|scorecard|job post/i, "rec_jd_writer"], [/source|candidates|find/i, "rec_sourcer"],
    [/screen|application|resume|cv/i, "rec_screener"], [/schedule|interview|slot/i, "rec_scheduler"],
    [/update|reject|candidate message/i, "rec_candidate_comms"]],
  ops: [[/project|task|deadline|standup/i, "ops_project_manager"], [/sop|checklist|onboarding|process/i, "ops_sop_writer"],
    [/automat|zap|\bmake\b|script/i, "ops_automation_engineer"], [/kpi|metric|dashboard/i, "ops_reporting_analyst"],
    [/vendor|quote|supplier/i, "ops_vendor_manager"]],
};
const FILES: Record<string, string> = {
  mkt_graphic_designer: "ad-1080x1080.png", mkt_video_editor: "teaser-9x16.mp4", mkt_personal_reels: "reel-final.mp4",
  mkt_copywriter: "caption.md", mkt_seo_content: "blog-outline.md", mkt_social_manager: "post-schedule.json",
  mkt_analyst: "weekly-numbers.md", sales_prospector: "leads.csv", sales_researcher: "account-brief.md",
  sales_outreach_writer: "outreach-drafts.md", sales_crm_keeper: "crm-changes.json", sales_proposal_writer: "proposal.pdf",
  rec_jd_writer: "job-description.md", rec_sourcer: "candidates.csv", rec_screener: "screening-scores.md",
  rec_scheduler: "interview-slots.md", rec_candidate_comms: "candidate-updates.md", ops_project_manager: "project-plan.md",
  ops_sop_writer: "sop.md", ops_automation_engineer: "automation-draft.json", ops_reporting_analyst: "kpis.md",
  ops_vendor_manager: "vendor-comparison.md",
};

interface DTask extends TaskSummary { owner: string; cost: number }
interface Waiter { approval: Approval; resolve: (d: Decision) => void }

export class DemoFeed implements Feed {
  mode = "demo" as const;
  private seq = 0;
  private listeners = new Set<(ev: LiveEvent) => void>();
  private ids: string[] = [];
  private presence: Record<string, { state: Presence; task_id: string | null; phase: string | null; since: string }> = {};
  private runs: Record<string, [string, string][]> = {};
  private sup: Record<string, Set<string>> = {};
  private blocked: Record<string, Set<string>> = {};
  private waiting = new Map<string, string>(); // approval id -> employee
  private approvals = new Map<string, Waiter>();
  private tasks = new Map<string, DTask>();
  private holders: Record<string, string> = {};
  private paused = false;
  private spent = 0;
  private speed = 1;
  private leadOf: Record<string, string> = {};
  private specsOf: Record<string, string[]> = {};

  constructor() {
    this.ids = [...Object.keys(OFFICE.core)];
    for (const d of OFFICE.departments) {
      this.leadOf[d.id] = d.lead.id;
      this.specsOf[d.id] = d.specialists.map((s) => s.id);
      this.ids.push(d.lead.id, ...d.specialists.map((s) => s.id));
    }
    const now = new Date().toISOString();
    for (const id of this.ids) {
      this.presence[id] = { state: "sleeping", task_id: null, phase: null, since: now };
      this.runs[id] = []; this.sup[id] = new Set(); this.blocked[id] = new Set();
    }
  }

  // ------------------------------------------------------------------ Feed
  async office() { return OFFICE; }
  async state(): Promise<Snapshot> {
    return {
      seq: this.seq, presence: structuredClone(this.presence),
      open_tasks: [...this.tasks.values()].map((t) => ({ ...t, holder: this.holders[t.id] ?? null })),
      pending_approvals: [...this.approvals.values()].map((w) => w.approval),
      month_spent_usd: this.spent, month_budget_usd: OFFICE.monthly_budget_usd,
      pauses: this.paused ? [{ scope: "all", reason: "owner kill switch" }] : [],
    };
  }
  subscribe(_since: number, onEvent: (ev: LiveEvent) => void, onConn: (s: ConnState) => void) {
    this.listeners.add(onEvent);
    onConn("demo");
    return () => { this.listeners.delete(onEvent); };
  }
  async prompt(employeeId: string, text: string) {
    const emp = employeeId === "chief_of_staff" ? "hq" : Object.keys(this.leadOf).find((d) => this.leadOf[d] === employeeId);
    if (!emp) throw new Error("only the Chief of Staff and department Leads take requests");
    const t = this.createTask(emp, text, null);
    (emp === "hq" ? this.runAtlas(t) : this.runDept(t, false)).catch(console.error);
    return { task_id: t.id };
  }
  async reply(taskId: string, text: string) {
    const t = this.tasks.get(taskId);
    if (t) this.message(t.owner, taskId, `Noted: "${text.slice(0, 80)}"`);
  }
  async decide(approvalId: string, body: Decision) {
    const w = this.approvals.get(approvalId);
    if (!w) throw new Error("approval is no longer pending");
    this.approvals.delete(approvalId);
    const emp = this.waiting.get(approvalId);
    this.waiting.delete(approvalId);
    this.emit("approval.decided", w.approval.task_id, { approval_id: approvalId, status: body.approve ? "approved" : "rejected" });
    if (emp) this.settle(emp);
    w.resolve(body);
  }
  async command(text: string) {
    const [cmd] = text.trim().split(/\s+/);
    if (cmd === "pause-all") { this.paused = true; this.ids.forEach((i) => this.settle(i)); return "All employees paused."; }
    if (cmd === "resume") { this.paused = false; this.ids.forEach((i) => this.settle(i)); return "Resumed all."; }
    return "Demo supports: pause-all, resume all";
  }
  setSpeed(x: number) { this.speed = x; }

  // ------------------------------------------------------------------ backend-equivalent internals
  private emit(type: string, task_id: string | null, data: Record<string, any>) {
    const ev: LiveEvent = { seq: ++this.seq, at: new Date().toISOString(), type, task_id, data };
    this.listeners.forEach((l) => l(ev));
  }
  private settle(emp: string) {
    if (!this.presence[emp]) return;
    let state: Presence = "sleeping", task: string | null = null, phase: string | null = null;
    const runs = this.runs[emp];
    if (this.paused) state = "paused";
    else if (runs.length) { state = "working"; [task, phase] = runs[runs.length - 1]; }
    else if (this.blocked[emp].size) { state = "blocked"; task = [...this.blocked[emp]][0]; }
    else if ([...this.waiting.values()].includes(emp)) {
      state = "waiting_owner";
      task = [...this.waiting.entries()].find(([, e]) => e === emp)![0];
      task = this.approvals.get(task)?.approval.task_id ?? null;
    } else if (this.sup[emp].size) { state = "supervising"; task = [...this.sup[emp]][0]; }
    const cur = this.presence[emp];
    if (cur.state !== state || cur.task_id !== task || cur.phase !== phase) {
      this.presence[emp] = { state, task_id: task, phase, since: new Date().toISOString() };
      this.emit("employee.state", task, { employee_id: emp, state, previous: cur.state, phase });
    }
  }
  private wait(ms: number) { return new Promise((r) => setTimeout(r, ms / this.speed)); }
  private createTask(dept: string, text: string, parent: DTask | null): DTask {
    const id = "task_" + Math.random().toString(16).slice(2, 12);
    const owner = dept === "hq" ? "chief_of_staff" : this.leadOf[dept];
    const t: DTask = { id, parent_id: parent?.id ?? null, department: dept, status: "RECEIVED", size: null, request: text,
      objective: text, holder: null, cost_usd: 0, owner, cost: 0 };
    this.tasks.set(id, t);
    this.emit("task.created", id, { department: dept, assignee: owner, request: text, parent_id: t.parent_id });
    this.handoff(t, parent ? "chief_of_staff" : "owner", owner, parent ? "subtask" : "request", text);
    return t;
  }
  private handoff(t: DTask, from: string, to: string, kind: string, note = "", extra: Record<string, any> = {}) {
    this.holders[t.id] = to;
    this.emit("handoff", t.id, { from, to, kind, note: note.slice(0, 280), ...extra });
  }
  private status(t: DTask, to: string, reason = "") {
    const from = t.status;
    t.status = to;
    this.emit("task.status", t.id, { from, to, actor: t.owner, reason });
    const s = this.sup[t.owner], b = this.blocked[t.owner];
    if (s) { SUPERVISED.has(to) ? s.add(t.id) : s.delete(t.id); to === "ESCALATED" ? b.add(t.id) : b.delete(t.id); }
    if (to === "CLOSED" || to === "CANCELLED") { delete this.holders[t.id]; this.tasks.delete(t.id); }
    this.settle(t.owner);
  }
  private async run(emp: string, t: DTask, phase: string, ms: number) {
    while (this.paused) await this.wait(500);
    this.runs[emp].push([t.id, phase]);
    this.settle(emp);
    await this.wait(ms * (0.85 + Math.random() * 0.4));
    this.runs[emp] = this.runs[emp].filter(([id, p]) => !(id === t.id && p === phase));
    const cost = +(0.02 + Math.random() * (phase === "execute" ? 0.18 : 0.06)).toFixed(3);
    this.spent += cost; t.cost += cost; t.cost_usd = t.cost;
    this.emit("cost", t.id, { task_cost_usd: t.cost, month_spent_usd: this.spent, month_budget_usd: OFFICE.monthly_budget_usd });
    this.emit("run.finished", t.id, { employee_id: emp, phase, cost_usd: cost, error: false });
    this.settle(emp);
  }
  private message(emp: string | null, taskId: string, text: string) { this.emit("message", taskId, { employee_id: emp, text }); }
  private ask(t: DTask, gate: Approval["gate"], emp: string, title: string, summary: string, extra: Record<string, any> = {}) {
    return new Promise<Decision>((resolve) => {
      const approval: Approval = { id: "apr_" + Math.random().toString(16).slice(2, 10), task_id: t.id, gate, employee_id: emp,
        action_hash: null, title, summary, preview: extra };
      this.approvals.set(approval.id, { approval, resolve });
      this.waiting.set(approval.id, emp);
      this.emit("approval.requested", t.id, { approval_id: approval.id, gate, employee_id: emp, title, summary, action_hash: null, ...extra });
      this.settle(emp);
    });
  }

  private size(text: string) { return /campaign|\bplan\b|launch week|list of|strategy|hire|build|\band\b/i.test(text) || text.length > 70 ? "M" : "S"; }
  private pickSpecs(dept: string, text: string, size: string) {
    let ids = [...new Set((PICK[dept] || []).filter(([re]) => re.test(text)).map(([, id]) => id))];
    const all = this.specsOf[dept];
    if (!ids.length) ids = [all[Math.floor(Math.random() * all.length)]];
    if (size !== "S" && ids.length < 2) { const o = all.filter((s) => !ids.includes(s)); ids.push(o[Math.floor(Math.random() * o.length)]); }
    return ids.slice(0, size === "S" ? 1 : 2);
  }

  private async runDept(t: DTask, inherited: boolean): Promise<boolean> {
    const lead = t.owner, size = inherited ? "S" : this.size(t.request);
    t.size = size;
    if (!inherited) {
      await this.run(lead, t, "contract", 3000);
      this.status(t, "CONTRACT_DRAFTED");
      if (size === "S") { this.message(lead, t.id, "*Contract (small task — starting now)*"); this.status(t, "CONTRACT_APPROVED", "S task auto-start"); }
      else {
        const summary = `*Objective:* ${t.request}\n*Acceptance criteria:*\n1. Matches the brief exactly\n2. Every claim has a source\n3. On-brand and ready to use\n*Size:* ${size}`;
        this.message(lead, t.id, "Contract ready for approval");
        const d = this.ask(t, "G1", lead, `Contract v1`, summary);
        this.handoff(t, lead, "owner", "approval_request", t.request, { gate: "G1" });
        const r = await d;
        this.handoff(t, "owner", lead, r.approve ? "approved" : "rejected", r.reason || "", { gate: "G1" });
        if (!r.approve) { this.status(t, "CANCELLED", "owner cancelled at G1"); return false; }
        this.status(t, "CONTRACT_APPROVED");
      }
    } else { this.status(t, "CONTRACT_DRAFTED"); this.status(t, "CONTRACT_APPROVED", "inherits parent G1"); }
    const steps = this.pickSpecs(t.department, t.request, size);
    for (let round = 0; round < 3; round++) {
      await this.run(lead, t, "plan", 2500);
      if (t.status === "CONTRACT_APPROVED") this.status(t, "PLANNED");
      this.status(t, "IN_PROGRESS");
      for (const [i, sp] of steps.entries()) {
        this.handoff(t, lead, sp, "assign", t.request, { step: `T${i + 1}`, attempt: 1 });
        await this.wait(4000);
        await this.run(sp, t, "execute", 7000);
        this.emit("artifact.created", t.id, { employee_id: sp, name: FILES[sp], step: `T${i + 1}` });
        this.handoff(t, sp, lead, "return", `${FILES[sp]} ready`, { step: `T${i + 1}`, attempt: 1, checks_passed: true });
        await this.wait(3500);
      }
      this.status(t, "VERIFYING");
      if (size !== "S") {
        this.handoff(t, lead, "verifier", "for_verification", t.request);
        await this.wait(4500);
        await this.run("verifier", t, "verify", 4000);
        this.message("verifier", t.id, "All criteria met. PASS.");
        this.handoff(t, "verifier", lead, "verdict", "PASS", { passed: true });
        await this.wait(4500);
      }
      await this.run(lead, t, "deliver", 2000);
      this.status(t, "DELIVERED");
      const files = steps.map((s) => FILES[s]);
      const memory = [{ id: "mem_" + t.id, text: "Owner prefers short, direct copy" }];
      const d = this.ask(t, "G4", lead, "Accept delivery?", `The finished work is ready. Checks passed${size !== "S" ? " and Vera signed it off" : ""}.`,
        { artifacts: files, memory_candidates: memory });
      this.handoff(t, lead, "owner", "delivery", files.join(", "), { artifacts: files, memory_candidates: memory });
      const r = await d;
      if (r.approve) { this.status(t, "ACCEPTED"); if (!inherited) this.status(t, "CLOSED"); return true; }
      this.handoff(t, "owner", lead, "rejected", r.reason || "", { gate: "G4" });
      this.status(t, "REJECTED", r.reason || ""); this.status(t, "REVISION");
      this.message(lead, t.id, `On it: "${r.reason || "another pass"}"`);
    }
    this.status(t, "ESCALATED", "too many revisions");
    return false;
  }

  private async runAtlas(t: DTask) {
    await this.run("chief_of_staff", t, "contract", 3200);
    this.status(t, "CONTRACT_DRAFTED");
    const re: [RegExp, string][] = [[/market|campaign|post|content|brand/i, "marketing"], [/sale|lead|outreach|prospect|deal/i, "sales"],
      [/hire|recruit|candidate|role/i, "recruiting"], [/ops|process|sop|vendor|automat/i, "ops"]];
    let depts = re.filter(([r]) => r.test(t.request)).map(([, d]) => d);
    if (depts.length < 2) depts = ["marketing", "sales"];
    const summary = depts.map((d) => `• ${d}: their part of "${t.request}"`).join("\n");
    const g1 = this.ask(t, "G1", "chief_of_staff", "Cross-department contract", summary);
    this.handoff(t, "chief_of_staff", "owner", "approval_request", t.request, { gate: "G1" });
    const r = await g1;
    this.handoff(t, "owner", "chief_of_staff", r.approve ? "approved" : "rejected", r.reason || "", { gate: "G1" });
    if (!r.approve) { this.status(t, "CANCELLED"); return; }
    this.status(t, "CONTRACT_APPROVED"); this.status(t, "PLANNED"); this.status(t, "IN_PROGRESS", "sub-tasks spawned");
    const kids = depts.map((d) => {
      const kid = this.createTask(d, `${d} part: ${t.request}`, t);
      return this.runDept(kid, true).then(async (ok) => {
        if (ok) { this.handoff(kid, kid.owner, "chief_of_staff", "subtask_done", d, { parent_id: t.id }); this.status(kid, "CLOSED"); }
      });
    });
    await Promise.all(kids);
    this.status(t, "VERIFYING"); this.status(t, "DELIVERED");
    this.message("chief_of_staff", t.id, "All departments delivered");
    const g4 = this.ask(t, "G4", "chief_of_staff", "Close cross-department task?", depts.map((d) => `• ${d}: CLOSED`).join("\n"));
    this.handoff(t, "chief_of_staff", "owner", "delivery", "all parts done");
    if ((await g4).approve) { this.status(t, "ACCEPTED"); this.status(t, "CLOSED"); }
  }
}
