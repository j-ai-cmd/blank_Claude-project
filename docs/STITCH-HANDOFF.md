# Live Office — handoff for Google Stitch

Two parts:

1. **Prompt for Stitch.** Paste it into Stitch. It says what the app must do, not how it should look. Stitch does the design.
2. **Backend reference.** The API the app talks to: every endpoint, event, state, and employee id. Give it to whoever wires the Stitch output to live data.

The backend is already built (`workforce/live.py`, `workforce/app.py`, tests in `tests/test_live.py`).

---

## Part 1 — Prompt for Stitch

> Design a **live, highly animated 3D office web app** where my AI company works in real time. It's a single-page app. I'm the only user (the owner).
>
> **The world**
> - One office floor. Each department gets its own zone: **Studio, Sales, Talent, Engineering, Ops**. There's also a **head table** for the core team.
> - Every employee is a **small 3D Minecraft-style character** with their own desk. There are 36 of them (roster below). Each character shows their name. Leads look slightly different from their specialists so I can tell who runs the department.
> - **Atlas** (Chief of Staff) sits at the head of the office. **Vera** (Verifier), **Proof** (fact checker) and **Lex** (Librarian) sit at the head table too.
> - The **Owner (me)** has a spot too, like a desk or an inbox by the door. Notes walk to it when something needs my answer and walk away from it when I give a task.
>
> **Employee states (the backend sends these, the app just shows them)**
> - `sleeping`: no work. The character is asleep at their desk (head down, Zzz). This is the default for everyone.
> - `working`: awake and busy at the desk (typing, screen lit). A small label shows the phase: *contract, plan, execute, verify, deliver*.
> - `supervising`: a Lead or Atlas is awake and watching their team work.
> - `waiting_owner`: waiting on me. The character looks at the owner's spot and shows a visible "needs you" marker.
> - `blocked`: the task is escalated. Show a clear warning on the character.
> - `paused`: switched off by me. Frozen or greyed out.
>
> **The note (this is the heart of the app)**
> - Every task is a **paper note**. At any moment the note is in exactly one person's hands, and I must always be able to see where it is.
> - When the backend sends a `handoff` event, the character **gets up, walks the note to the receiver's desk, hands it over, and walks back**. Walks must cross the floor visibly (between departments too, e.g. Studio to Vera's head table).
> - If several handoffs arrive quickly, **queue them per task and play them in order**. Never skip one, and never show one note in two places. Different tasks can animate at the same time.
> - When a Lead hands work to a specialist, that specialist **wakes up** (stretch, sit up) before they start working. When they finish, they walk the note back to their Lead and **fall asleep again**.
> - Clicking a note shows its details: the task request, objective, current status, who holds it, and a timeline of every handoff so far.
>
> **Giving work**
> - Only **Atlas and the department Leads** (Maya, Sam, Rhea, Forge, Otto) take work from me. Their desks are clickable. Clicking opens a prompt box: "Give Maya a task…". When I send it, a new note walks from my spot to that desk.
> - Atlas takes work that involves more than one department. He splits it and walks a sub-note to each Lead involved.
> - Specialists are **not** clickable for prompts. Clicking them only shows a profile card: name, role, what they do, their current state, and their current task.
> - The Leads decide who works. I never wake specialists myself.
>
> **My inbox (approvals)**
> - Some notes come back to me for a decision: **approve the contract**, **approve the plan**, **accept the delivery**, or **approve an external action** (e.g. publishing a post). Each shows a readable preview with **Approve** and **Reject** buttons. Reject asks for a short reason.
> - When a delivery comes back, show its list of files and a set of "save to memory?" checkboxes the backend provides.
> - A counter on my spot shows how many decisions are waiting.
> - When a Lead asks me questions, I can reply from the note (a reply box).
>
> **Always visible (HUD)**
> - Live connection indicator (live / reconnecting).
> - Monthly AI budget: spent vs $20, as a bar.
> - Number of open tasks, and how many are waiting on me.
> - A kill switch: pause everyone, pause one department, resume.
> - A scrolling activity feed: one short line per event ("Maya → Quill: caption for launch", "Vera: PASS").
> - Speech bubbles: when an employee posts a `message`, show it briefly above their head.
>
> **Camera and controls**
> - Free orbit and zoom, plus one-click focus on each department and on the head table.
> - "Follow this note" mode: the camera follows a selected task's note as it moves.
> - Works on desktop first. On a phone it should still show the office and my inbox.
>
> **Empty and edge states**
> - First load: everyone asleep, a hint to click Atlas or a Lead.
> - Connection lost: dim the office and show "reconnecting". On return, snap everyone to their correct state without replaying old animations.
> - Budget used up: everyone `paused`, with a banner.
>
> **Roster.** Each line gives id, name, and role. The id is what the backend uses.
> - Head table: `chief_of_staff` Atlas (route requests that need more than one department, clickable) · `verifier` Vera (grade the deliverable against the approved brief criterion by criterion) · `fact_checker` Proof (extract every factual claim) · `librarian` Lex (save only memories the owner ticks)
> - Studio: `studio_lead` **Maya** (Lead, clickable) · `studio_faceless_editor` Reel · `studio_designer` Pixel · `show_jai_producer` Jai · `show_jai_designer` Jai-Design · `show_sherlock_producer` Sherlock · `show_sherlock_designer` Sherlock-Design · `show_peter_producer` Peter · `show_peter_designer` Peter-Design · `show_striker_producer` Striker · `show_striker_designer` Striker-Design
> - Sales: `sales_lead` **Sam** (Lead, clickable) · `sales_scout` Scout · `sales_researcher` Intel · `sales_outreach_writer` Hook · `sales_application_writer` Apply · `sales_proposal_writer` Pitch · `sales_script_writer` Script · `show_jai_writer` Jai-Writer · `show_sherlock_writer` Sherlock-Writer · `show_peter_writer` Peter-Writer · `show_striker_writer` Striker-Writer
> - Talent: `talent_lead` **Rhea** (Lead, clickable) · `talent_architect` Architect
> - Engineering: `eng_lead` **Forge** (Lead, clickable) · `eng_backend` Byte · `eng_frontend` Loom · `eng_qa` Audit · `eng_automation` Gear
> - Ops: `ops_lead` **Otto** (Lead, clickable) · `ops_bookkeeper` Ledger · `ops_reporting_analyst` Gauge
>
> **Data.** All data comes from a REST + Server-Sent Events backend (spec attached). Build the roster and layout from `GET /api/office`. Don't hardcode it; departments may be added later. Use mock data that follows the spec until it's wired up.

---

## Part 2 — Backend reference

### Stack and config

- FastAPI (`workforce/app.py`) + Postgres (SQLite locally). Agents run on the Claude Agent SDK.
- Env vars the frontend depends on:
  - `WORKFORCE_API_TOKEN`: the owner's key. Every `/api/*` call needs it.
  - `WORKFORCE_FRONTEND_ORIGIN`: the frontend URL(s), comma-separated, for CORS (e.g. `https://office.vercel.app`).
- Local run with scripted agents (no Claude usage):
  `WORKFORCE_RUNNER=fake WORKFORCE_API_TOKEN=tok uvicorn workforce.app:app --port 8000`

### Auth

- REST: header `Authorization: Bearer <WORKFORCE_API_TOKEN>`.
- SSE: browser `EventSource` can't send headers, so use `?token=<WORKFORCE_API_TOKEN>` on `/api/live`. The app is owner-only; keep the token out of shared links.
- `401` means the token is bad or missing.

### How the frontend syncs

1. `GET /api/office` loads the floor plan and roster, once.
2. `GET /api/office/state` loads the snapshot: `seq`, presence, open tasks with holders, pending approvals, budget, pauses. Draw everyone in place with no animation.
3. Open `EventSource('/api/live?token=…&since=<snapshot.seq>')` and apply each event in `seq` order, animating as it arrives.
4. On reconnect, the browser resends `Last-Event-ID` and the server replays what you missed. If you get a `resync` event, repeat step 2 and reopen the stream from the new `seq`.
5. Ignore any event with `seq <= lastSeq` (duplicates).

### Endpoints

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/health` | – | `{ok:true}` (no auth) |
| GET | `/api/office` | – | floor plan (below) |
| GET | `/api/office/state` | – | snapshot (below) |
| GET | `/api/live?since=&token=` | – | SSE stream |
| POST | `/api/desks/{employee_id}/prompt` | `{text}` (1–8000 chars) | `202 {task_id}` · `403` if not Atlas or a Lead · `404` unknown id |
| POST | `/api/tasks/{task_id}/reply` | `{text}` | `202 {ok}`: answer a question or change direction (new contract version, back to approval) · `404` |
| POST | `/api/approvals/{approval_id}` | `{approve, reason?, memory_ticks?[], action_hash?}` | `202 {ok}` · `404` · `409` no longer pending, or G3 `action_hash` mismatch |
| GET | `/api/approvals?status=pending` | – | list of approvals |
| GET | `/api/tasks` | – | last 100 tasks (summary) |
| GET | `/api/tasks/{task_id}` | – | full task (below) |
| POST | `/api/commands` | `{text}` | `{text}`: `pause-all` · `pause <dept\|employee_id>` · `resume <all\|dept\|employee_id>` · `status` · `gc` |

The POST endpoints return right away. The result shows up as live events.

#### `GET /api/office`

```json
{
  "company": "<COMPANY NAME>",
  "owner": {"id": "owner"},
  "monthly_budget_usd": 20.0,
  "core": {
    "chief_of_staff": Employee, "verifier": Employee, "librarian": Employee
  },
  "departments": [
    {"id": "studio", "channel": "#studio", "lead": Employee, "specialists": [Employee, ...]},
    ...
  ]
}
```

`Employee`:

```json
{"id": "sales_lead", "name": "Sam", "kind": "lead", "department": "sales",
 "model": "claude-sonnet-5-5", "role": ["turn requests into contracts", "..."],
 "does_not": ["..."], "voice": ["direct", "confident"],
 "signoff": "— Sam", "promptable": true}
```

`kind` is one of `router` (Atlas), `verifier`, `librarian`, `lead`, `specialist`. Only `promptable: true` desks get a prompt box.

#### `GET /api/office/state`

```json
{
  "seq": 42,
  "presence": {
    "sales_lead": {"state": "supervising", "task_id": "task_ab12", "phase": null, "since": "2026-09-29T01:27:46Z"},
    "sales_script_writer": {"state": "working", "task_id": "task_ab12", "phase": "execute", "since": "..."},
    "...": "one entry per employee id"
  },
  "open_tasks": [Task],
  "pending_approvals": [Approval],
  "month_spent_usd": 3.12,
  "month_budget_usd": 20.0,
  "pauses": [{"scope": "dept:sales", "reason": "owner"}]
}
```

`Task` (summary):

```json
{"id": "task_ab12", "parent_id": null, "department": "sales", "status": "IN_PROGRESS",
 "size": "M", "request": "write a launch caption", "objective": "Write a launch caption",
 "holder": "sales_script_writer", "contract_version": 1, "revisions": 0, "cost_usd": 0.41,
 "created_at": "...", "updated_at": "..."}
```

`holder` says who has the note: an employee id, `"owner"`, or `null` if unknown. `department: "hq"` means Atlas owns the task. `parent_id` is set on department sub-tasks Atlas created.

`Approval`:

```json
{"id": "apr_9f", "task_id": "task_ab12", "gate": "G4", "tier": null, "action": null,
 "action_hash": null, "contract_version": 1, "status": "pending", "employee_id": null,
 "preview": {"artifacts": ["caption.md"]}, "created_at": "..."}
```

| gate | Meaning | Button → body |
|---|---|---|
| G1 | Approve the contract (the Lead's written understanding of the task) | `{approve}`. Reject cancels the task |
| G2 | Approve the plan (big tasks only: who does which step) | `{approve}` |
| G3 | Approve one external action (publish, send, move a stage). `preview.params` shows exactly what will run | `{approve, action_hash}`. Echo the approval's `action_hash` |
| GM | Save your "always/never" instruction as a standing rule | `{approve}` |
| G4 | Accept the delivery | `{approve:true, memory_ticks:[ids]}` or `{approve:false, reason}`. Reject sends it back for revision |

For readable previews, use the `approval.requested` event's `title` and `summary` (Markdown-ish, Slack format: `*bold*`, `•` bullets).

#### `GET /api/tasks/{id}`

The summary fields, plus:

```json
{
  "contract": {"objective": "...", "deliverables": [{"id": "D1", "description": "...", "format": "md"}],
               "acceptance_criteria": [{"id": "1", "text": "...", "check": "automatic"}],
               "size": "S", "deadline": null, "questions": ["..."]},
  "plan": [{"step": "T1", "from": "sales_lead", "to": "sales_script_writer", "task_type": "general_copy", "objective": "..."}],
  "delivery": {"note": "Caption is ready.", "artifacts": ["caption.md"]},
  "subtasks": [Task],
  "timeline": [{"at": "...", "actor": "sales_lead", "from": "RECEIVED", "to": "CONTRACT_DRAFTED", "reason": ""}],
  "events": [LiveEvent, "... last 200 for this task (in memory, lost on restart)"]
}
```

If `contract.questions` is non-empty, the Lead needs answers. Show a reply box that posts to `/reply`.

### Live events (SSE)

Each SSE frame looks like this:

```
id: 17
event: handoff
data: {"seq":17,"at":"2026-09-29T01:27:46.6Z","type":"handoff","task_id":"task_ab12","data":{...}}
```

| `type` | `data` | Show |
|---|---|---|
| `hello` | `{seq}` | Connected (no `id:`). |
| `resync` | `{}` | Reload the snapshot, then reconnect. |
| `task.created` | `department, assignee, request, parent_id` | A new note appears at the owner's spot (or at Atlas's desk if `parent_id` is set). |
| `handoff` | `from, to, kind, note` + extras | **Walk the note** from `from` to `to`. `from`/`to` = employee id or `"owner"`. |
| `employee.state` | `employee_id, state, previous, phase` | Change the character's pose (sleeping to working means a wake-up animation). |
| `task.status` | `from, to, actor, reason` | Update the note's status badge. |
| `approval.requested` | `approval_id, gate, employee_id, title, summary, action_hash` | Add it to my inbox. The employee shows `waiting_owner`. |
| `approval.decided` | `approval_id, status` (`approved`, `rejected`, `expired`) | Remove it from my inbox. |
| `message` | `employee_id` (null = system), `text` | Speech bubble plus a feed line. |
| `artifact.created` | `employee_id, name, step` | A small "file made" pop at the desk. |
| `run.finished` | `employee_id, phase, cost_usd, error` | Feed line. On `error: true`, a small failure puff. |
| `cost` | `task_cost_usd, month_spent_usd, month_budget_usd` | Update the budget bar. |

`handoff.kind` values, and what each walk means:

| kind | from → to | Meaning | Extras |
|---|---|---|---|
| `request` | owner → Atlas/Lead | I gave a task | – |
| `subtask` | Atlas → Lead | Atlas split a cross-department task | – |
| `approval_request` | Lead/Atlas → owner | Contract (G1) or plan (G2) needs me | `gate, approval_id` |
| `approved` / `rejected` | owner → Lead (or specialist for G3) | My decision goes back | `gate` |
| `assign` | Lead → specialist | Lead wakes a specialist with a job | `step` (T1…), `attempt`, `task_type` |
| `return` | specialist → Lead | Work handed back | `step, attempt, checks_passed` (false = automatic checks failed; a retry `assign` follows, up to 3 attempts) |
| `for_factcheck` | Lead → Proof | Sent for fact-checking (every task) | – |
| `factcheck_result` | Proof → Lead | `note` summarises the claims | `passed` |
| `for_verification` | Lead → Vera | Sent for independent checking | – |
| `verdict` | Vera → Lead | Result: `note` is "PASS" or "N criteria failed" | `passed` (false = a revision round follows) |
| `delivery` | Lead/Atlas → owner | Finished work for me to accept | `approval_id, artifacts[], memory_candidates[{id,text}]` |
| `escalation` | holder → owner | Stuck: retries or budget used up, or no valid plan | `note` = reason |
| `subtask_done` | Lead → Atlas | A department finished its part | `parent_id` |

### Presence rules (computed by the backend)

The first matching state wins: `paused` > `working` > `blocked` > `waiting_owner` > `supervising` > `sleeping`.

- `working`: a Claude session is running for this employee right now. `phase` is one of `contract`, `plan`, `execute`, `verify`, `deliver`.
- `supervising`: a Lead or Atlas owns a task that is approved and not finished yet.
- Specialists are only ever `sleeping`, `working`, `waiting_owner` (their G3 action is waiting on me), or `paused`.
- Lex (librarian) runs as background code today, so he is usually `sleeping`.

### A typical task, event by event

Small Sales task (auto-starts, no contract approval):

```
task.created      sales, assignee sales_lead
handoff           owner → sales_lead (request)
employee.state    sales_lead working (contract)
task.status       RECEIVED → CONTRACT_DRAFTED → CONTRACT_APPROVED
employee.state    sales_lead supervising
employee.state    sales_lead working (plan)
task.status       → PLANNED → IN_PROGRESS
handoff           sales_lead → sales_script_writer (assign, T1)
employee.state    sales_script_writer working (execute)        ← wakes up
artifact.created  sales_script_writer caption.md
employee.state    sales_script_writer sleeping                  ← back to sleep
handoff           sales_script_writer → sales_lead (return, checks_passed true)
handoff           sales_lead → fact_checker (for_factcheck)
employee.state    fact_checker working (factcheck)
handoff           fact_checker → sales_lead (factcheck_result)
task.status       → VERIFYING
employee.state    sales_lead working (deliver)
task.status       → DELIVERED
approval.requested G4
handoff           sales_lead → owner (delivery)
employee.state    sales_lead waiting_owner
… I click Accept →
approval.decided  approved
task.status       → ACCEPTED → CLOSED
employee.state    sales_lead sleeping
```

Medium and large tasks add `approval_request` (G1) before planning. Large ones also add G2. Both add `for_verification`/`verdict` walks to Vera.

Cross-department: `owner → chief_of_staff (request)`, then after G1 one `subtask` walk per department (`chief_of_staff → studio_lead`, `→ sales_lead`…). Each department runs the flow above, then `subtask_done` back to Atlas, and Atlas does the final `delivery` to the owner.

### Task statuses

`RECEIVED, CONTRACT_DRAFTED, CONTRACT_APPROVED, PLANNED, IN_PROGRESS, AWAITING_APPROVAL, VERIFYING, REVISION, DELIVERED, ACCEPTED, REJECTED, ESCALATED, CANCELLED, CLOSED`. The last two are final: remove the note.

### Limits to design around

- Event history lives in memory only (last 2000). After a server restart, `/api/office/state` still returns correct tasks and approvals, but presence restarts from the DB and in-flight work stops. The backend has no durable job queue yet.
- Agent runs take seconds to minutes. Events arrive in bursts with gaps, so animations should queue and take their time.
- Slack keeps working alongside the office. Tasks given in the office are mirrored to the department's Slack channel, and approvals work in either place.
- Connectors (CRM, email, social…) aren't wired yet. Approved G3 actions report "no connector configured" as a `message`.
