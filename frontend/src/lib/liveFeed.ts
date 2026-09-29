import type { ConnState, Decision, Feed, LiveEvent, Office, Snapshot } from "./types";

/** Talks to the workforce backend: REST for reads/actions, Server-Sent Events for the live stream. */
export class LiveFeed implements Feed {
  mode = "live" as const;
  constructor(private base: string, private token: string) {
    this.base = base.replace(/\/+$/, "");
  }

  private async req<T>(path: string, init?: RequestInit): Promise<T> {
    const r = await fetch(this.base + path, {
      ...init,
      headers: { Authorization: `Bearer ${this.token}`, "Content-Type": "application/json", ...(init?.headers || {}) },
    });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      throw new Error(body.detail || `${r.status} ${r.statusText}`);
    }
    return r.json();
  }

  office() { return this.req<Office>("/api/office"); }
  state() { return this.req<Snapshot>("/api/office/state"); }

  subscribe(since: number, onEvent: (ev: LiveEvent) => void, onConn: (s: ConnState) => void) {
    // EventSource can't send headers, so the token rides in the query (owner-only app).
    const url = `${this.base}/api/live?token=${encodeURIComponent(this.token)}&since=${since}`;
    const es = new EventSource(url);
    onConn("connecting");
    es.onopen = () => onConn("live");
    es.onerror = () => onConn("reconnecting"); // the browser retries and resends Last-Event-ID
    const types = ["task.created", "handoff", "employee.state", "task.status", "approval.requested", "approval.decided",
      "message", "artifact.created", "run.finished", "cost", "resync"];
    for (const t of types) es.addEventListener(t, (m) => onEvent(JSON.parse((m as MessageEvent).data)));
    return () => es.close();
  }

  prompt(employeeId: string, text: string) {
    return this.req<{ task_id: string }>(`/api/desks/${encodeURIComponent(employeeId)}/prompt`, { method: "POST", body: JSON.stringify({ text }) });
  }
  async reply(taskId: string, text: string) {
    await this.req(`/api/tasks/${encodeURIComponent(taskId)}/reply`, { method: "POST", body: JSON.stringify({ text }) });
  }
  async decide(approvalId: string, body: Decision) {
    await this.req(`/api/approvals/${encodeURIComponent(approvalId)}`, { method: "POST", body: JSON.stringify(body) });
  }
  async command(text: string) {
    return (await this.req<{ text: string }>("/api/commands", { method: "POST", body: JSON.stringify({ text }) })).text;
  }
}
