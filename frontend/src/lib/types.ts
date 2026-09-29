// Shapes returned by the backend (see docs/STITCH-HANDOFF.md, Part 2).

export type Presence = "sleeping" | "working" | "supervising" | "waiting_owner" | "blocked" | "paused";

export interface Employee {
  id: string;
  name: string;
  kind: "router" | "verifier" | "librarian" | "lead" | "specialist";
  department: string;
  model?: string;
  role: string[];
  does_not?: string[];
  voice?: string[];
  signoff?: string | null;
  promptable: boolean;
}

export interface Department {
  id: string;
  channel: string;
  lead: Employee;
  specialists: Employee[];
}

export interface Office {
  company: string | null;
  owner: { id: "owner" };
  core: Record<string, Employee>;
  departments: Department[];
  monthly_budget_usd: number;
}

export interface PresenceEntry {
  state: Presence;
  task_id: string | null;
  phase: string | null;
  since: string;
}

export interface TaskSummary {
  id: string;
  parent_id: string | null;
  department: string;
  status: string;
  size: string | null;
  request: string;
  objective: string | null;
  holder: string | null;
  cost_usd: number;
  created_at?: string;
}

export interface Approval {
  id: string;
  task_id: string;
  gate: "G1" | "G2" | "G3" | "G4" | "GM";
  employee_id: string | null;
  action_hash: string | null;
  title?: string;
  summary?: string;
  preview?: Record<string, unknown>;
}

export interface Snapshot {
  seq: number;
  presence: Record<string, PresenceEntry>;
  open_tasks: TaskSummary[];
  pending_approvals: Approval[];
  month_spent_usd: number;
  month_budget_usd: number;
  pauses: { scope: string; reason: string }[];
}

export interface LiveEvent {
  seq: number;
  at?: string;
  type: string;
  task_id: string | null;
  data: Record<string, any>;
}

export interface Decision {
  approve: boolean;
  reason?: string;
  memory_ticks?: string[];
  action_hash?: string | null;
}

export type ConnState = "connecting" | "live" | "reconnecting" | "demo";

/** One interface for the real backend and the in-browser demo. */
export interface Feed {
  mode: "live" | "demo";
  office(): Promise<Office>;
  state(): Promise<Snapshot>;
  subscribe(since: number, onEvent: (ev: LiveEvent) => void, onConn: (s: ConnState) => void): () => void;
  prompt(employeeId: string, text: string): Promise<{ task_id: string }>;
  reply(taskId: string, text: string): Promise<void>;
  decide(approvalId: string, body: Decision): Promise<void>;
  command(text: string): Promise<string>;
  setSpeed?(x: number): void;
}
