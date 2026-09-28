# AI Workforce — Design Map (v0.2, pre-build)

Status: **DESIGN ONLY. Nothing gets built until this map is signed off.** v0.2 = v0.1 + 30 fixes from 4 review rounds (§19).
Scope: backend only. Slack is the only UI.

Companion files (the "hardcoded" layer — source of truth, code must obey them):

| File | What it hardcodes |
|---|---|
| `config/constitution.md` | Rules every employee obeys. Human-edited only. |
| `config/org.yaml` | Every employee: role, boss, channel, skills, tools, personality, limits |
| `config/permissions.yaml` | Risk tiers, action → tier map, who approves what |
| `config/memory.yaml` | Memory layers, who reads/writes each, TTLs, GC rules |
| `schemas/*.json` | Task Contract, Handoff Packet, Return Packet, Memory Entry |
| `docs/OPEN-QUESTIONS.md` | Decisions only you can make |
| `scripts/validate_config.py` | Checks the configs obey the design (tool tiers, private data vs. web access, restricted tools, roster limits). Must print 0 errors. |

---

## 1. Research summary (what exists, what we copy, what we fix)

| Product | Model | Copy | Avoid |
|---|---|---|---|
| **Viktor** (viktor.com) | One shared AI coworker in Slack/Teams, 3k integrations, long-running shared memory, asks before irreversible actions | Slack-native, @mention UX, "ask before irreversible", persistent company context | One brain for everything → context bloat; RBAC / per-user scoping / private mode still unshipped |
| **Relevance AI** "Workforce" | Canvas of agents with roles + tools; approval gates on the *edges* between agents/tools | Approval on edges, escalation paths, task view | Builder-first, not Slack-native |
| **Motion** AI Employees | Pre-built role agents (Sales, Marketing, HR, Support, PM, Research) | Department catalog | Dashboard-bound |
| **Sintra** | Pre-built persona "helpers" in own dashboard | Named personalities | Not in Slack, shallow |
| **Lindy** | Visual workflow builder | Deterministic triggers | Workflow ≠ employee |
| **Anthropic Managed Agents – multiagent** | Coordinator + roster (≤20 agents), each agent own model/prompt/tools/skills, **isolated context thread**, shared filesystem, **only 1 level of delegation** | Per-agent model/prompt/tools/skills, isolated contexts | Native roster shares sandbox + creds, 1 level only, delegation bypasses our code → we orchestrate sessions ourselves (§4) |
| Community practice (anthropic-sdk discussion #1419, 2026 papers) | Hub-and-spoke, subagents return compressed summaries, no peer-to-peer, **agents must not self-write shared memory** (files filled with hallucinated "facts" in 3 days) | Verified-only promotion, evidence vs claims, TTL tiers, one credential per agent | — |

**Our wedge vs Viktor:** many *specialist* employees with hard-isolated memory, hardcoded permissions enforced in code (not prompts), and a contract-and-verify loop on every task.

---

## 2. Core principles (non-negotiable)

1. **Rules live in code/config, not in prompts.** Prompts *explain* rules; the backend *enforces* them. A prompt-injected agent still cannot call a tool it isn't allowlisted for.
2. **Hub-and-spoke only.** Specialists never talk to each other. Leads never talk to other Leads directly. All cross-links go through the hub above them.
3. **One employee = one context + one memory + one credential set.** Isolation is enforced by storage ACLs, not by asking nicely.
4. **Every task has a written Task Contract.** Work is verified against it by an agent that did not do the work.
5. **No citation, no claim.** Any fact in a deliverable points to a source (tool result id, doc URL, CRM record, memory entry id).
6. **Store outcomes, not intentions.** Memory holds verified facts, decisions and feedback — never "I will do X".
7. **Only verified info is promoted to shared memory**, and only by the Librarian.
8. **Ask before irreversible.** External, bulk, money, hiring, legal, deletes → human approval.
9. **Personality never overrides rules.**
10. **Private data and web egress never sit in the same employee** (except the Verifier, which may only re-fetch exact URLs already in the task's fetch log).
11. **Humans decide on people.** Recruiting agents recommend; every candidate-affecting action is a human click.

---

## 3. Org chart

```
                         YOU (Owner / CEO)  ← final authority on everything
                                  │
               ┌──────────────────┼──────────────────────────┐
               │                  │                          │
      Chief of Staff "Atlas"   Verifier "Vera"        Librarian "Lex"
      (#hq, cross-dept router) (independent QA,      (sole writer of shared
               │                reports to YOU)       memory, memory GC)
   ┌───────────┼──────────────┬───────────────┬──────────────┐
   │           │              │               │              │
 Marketing   Sales        Recruiting         Ops          (v2: Finance,
 Lead "Maya" Lead "Sam"   Lead "Rhea"     Lead "Otto"     Support, Legal)
 #marketing  #sales       #recruiting     #ops
   │           │              │               │
 Graphic     Prospector    Sourcer         Project Mgr
 Designer    Researcher    Screener        SOP Writer
 Video       Outreach      Scheduler       Automation
 Editor      Writer        JD Writer       Engineer
 Copywriter  CRM Keeper    Candidate       Reporting
 SEO/Content Proposal      Comms           Analyst
 Social Mgr  Writer                        Vendor Mgr
 Mktg Analyst
```

Full definitions: `config/org.yaml`.

### 3.1 Who does what (roles)

| Role | Leads? | Talks to humans? | Talks to | Runs work? |
|---|---|---|---|---|
| **Owner (you)** | Everyone | — | Anyone | Approves, accepts |
| **Dept Human Manager** (optional, per dept) | Their dept | — | Their Lead | Approves R2 in their dept |
| **Chief of Staff** | Dept Leads (routing only, not managing) | Yes, #hq + DMs | Leads, Verifier, Librarian | No — routes, tracks, reports |
| **Dept Lead** | Its specialists | Yes, its channel | Its specialists, CoS, Verifier, Librarian | Plans, delegates, assembles; small tasks itself |
| **Specialist** | Nobody | **No** (only posts progress inside task thread under its persona) | Its Lead only | Yes — the actual craft |
| **Verifier** | Nobody | Posts verdicts in thread | Leads (returns verdicts) | Checks only, never edits deliverables |
| **Librarian** | Nobody | #agent-log only | Receives memory candidates from all | Memory writes + GC |
| **Dispatcher** (deterministic code, NOT an LLM) | Runs everyone | — | — | Enforces permissions, budgets, queues, schedules, audit |

**"Who leads them"** = Dept Lead. **"Who runs them"** = the Dispatcher (code). **"Who owns them"** = you.

---

## 4. System architecture (backend)

```
 Slack (Events API / Socket Mode, interactive buttons)
        │
        ▼
 ┌──────────────── Gateway ─────────────────┐
 │ verify signature · dedupe · map channel → │
 │ Lead · map user → human role              │
 └───────────────────┬───────────────────────┘
                     ▼
 ┌──────────────── Dispatcher (code) ─────────────────────────────┐
 │ Task state machine · Policy engine (permissions.yaml)          │
 │ Budget/rate limits · Approval queue · Scheduler (cron routines)│
 │ Tool proxy (every tool call passes here: allowlist + tier)     │
 │ Audit log (append-only)                                        │
 └──────┬──────────────────────┬───────────────────────┬──────────┘
        ▼                      ▼                       ▼
  Employee sessions      Verifier sessions        Librarian jobs
  (one Claude session     (fresh context per       (promotion, GC,
   per employee per task;  verification)             conflict check)
   Lead ─delegate()─► Dispatcher ─► new Specialist session
   NO built-in toolset, NO vault creds, NO native multiagent roster,
   custom tools only ──► every tool_use is executed by the Dispatcher)
        │
        ▼
 Storage: Postgres (tasks, approvals, memory, audit) + pgvector (retrieval)
          Object store (artifacts) · Secrets vault (per-employee creds, held by Dispatcher ONLY)
```

- **Why the Dispatcher orchestrates (not Managed Agents' native multiagent roster):** native multiagent looks like a fit (coordinator + specialist threads), but per the docs all threads in a session share one sandbox filesystem and the session's vault credentials, threads keep history for the session's life, delegation is 1 level / 20 agents, and native delegation messages never pass through our code — so handoff packets can't be schema-validated or edge-checked. Therefore:
  0. **Every employee runs in its own session.** A Lead delegates by calling the custom tool `delegate(handoff_packet)`. The Dispatcher validates the packet (schema + edge + budget), starts a fresh specialist session with only that packet, and returns the specialist's validated `return_packet` as the tool result. Parallel delegation = Dispatcher runs sessions concurrently (cap: `parallel_specialists`). This also removes the 1-level limit, so CoS → Lead → Specialist uses the same mechanism.
  1. **One session per employee per task**, archived at CLOSED (specialist sessions archived as soon as they return, unless a revision is pending). No employee carries context from task to task. Cross-task knowledge comes only through L1/L3 memory.
  2. **No `agent_toolset` (bash/files/web) on any employee.** Every capability is a *custom tool* whose `tool_use` event is executed by the Dispatcher, which knows the calling thread/agent and applies the permission check. Nothing can bypass the Tool Proxy.
  3. **No vault credentials passed to sessions.** Third-party creds live in the Dispatcher's secrets store, one set per employee; the model never sees a token.
  4. **Memory and artifacts are not in the sandbox filesystem.** They're read/written via `memory.*` and `workspace.*` tools → Postgres/object store with row-level ACL by employee + task. The shared sandbox holds nothing worth stealing.
  5. **Caller identity is trivial:** one session = one employee, so the Dispatcher knows who called every tool from the session id. Phase-1 spike only needs to measure session start latency/cost (Managed Agents single-agent sessions vs. a plain Messages API tool loop — pick the cheaper; design works with either).
- **CoS:** gets `request_department(dept, contract)`; the Dispatcher opens a sub-task in that department. Cross-dept hops are always visible, logged, and gated.
- **Idempotency & durability:** every external action carries an idempotency key (`task_id + action_hash`); the Dispatcher's queue is durable (Postgres-backed) so a crash/retry never sends an email or post twice. Tool executions are recorded before and after the external call.
- **Approval authenticity:** Slack interaction payloads are signature-verified; the clicking user must be in the approver list for that tier/dept; the button carries the approval id + action hash, and a stale or mismatched hash is rejected.
- **Slack identity:** v1 = one Slack app, personas via `chat:write.customize` (per-employee name + avatar). Channel = routing (message in `#marketing` → Marketing Lead). v2 option = one Slack app per Lead for real @mentions.
- **Slack loop guard:** Gateway drops every event whose author is a bot/app (including our own personas) and every `bot_message` subtype. Only allowlisted humans create or steer tasks; agent-to-agent traffic never goes through Slack, only through the Dispatcher.
- **Requester allowlist:** only Slack users listed in `permissions.yaml → requesters` can start or change tasks. Guests, Slack Connect users and unknown users get a polite refusal + owner ping.

Stack proposal (confirm in OPEN-QUESTIONS): Python 3.12, FastAPI, Slack Bolt, Anthropic SDK (Managed Agents), Postgres 16 + pgvector, S3-compatible store, Redis queue.

---

## 5. Task lifecycle (state machine)

```
RECEIVED ─► CONTRACT_DRAFTED ─►(G1 human 👍)─► PLANNED ─►(G2 if L)─► IN_PROGRESS
                  ▲    │ human edits                               │    │
                  └────┘                             needs R2/R3 ──┘    ▼
                                                   AWAITING_APPROVAL  VERIFYING
                                                        (G3)            │
                                        fail (≤2 loops) ◄── REVISION ◄──┤
                                                                        │ pass
                                           ESCALATED ◄── fail 3rd time  ▼
                                                                    DELIVERED ─►(G4)─► ACCEPTED ─► CLOSED
                                                                                   └► REJECTED ─► REVISION / CANCELLED
```

Sizes (Lead classifies, Dispatcher checks): **S** ≤1 specialist, no external action, <15 min · **M** ≤3 specialists · **L** >3 specialists or cross-dept or >1 day.

**Hard transitions (Dispatcher refuses otherwise):**
- `IN_PROGRESS → DELIVERED` is impossible. Only `VERIFYING → DELIVERED` exists, and it requires a stored verification record (automatic checks + LLM Verifier where §7 requires it) with every criterion PASS or UNVERIFIABLE.
- `→ IN_PROGRESS` requires a stored G1 approval (or S-auto-start record).
- Any R2/R3 tool call requires a stored G3 approval id bound to that exact action hash (tool + params).
- A contract version change invalidates all open handoffs, verifications and approvals of the previous version.
- Revision counter: automatic Verifier FAILs count toward the limit of 2. A human rejection at G4 does not count; it reopens REVISION with the reason attached, and if it changes scope the Lead must issue a new contract version (back to G1).
- Scheduled routines (digests, reports, sweeps) create tasks with `requested_by: routine:<name>`, are limited to R0/R1 and to posting in their own channel; anything more becomes a *suggestion* for a human to request.

---

## 6. Human-in-the-loop gates

| Gate | When | What you see | Default |
|---|---|---|---|
| **G1 Contract** | Every M/L task; S tasks only if ambiguous | Lead restates: objective, deliverables, acceptance criteria, deadline, constraints, out-of-scope. Buttons: ✅ Go / ✏️ Edit / ❌ Cancel | Required M/L. S auto-starts after 0 min but shows contract |
| **G2 Plan** | L tasks | Who does what, order, handoffs, est. cost | Required |
| **G3 Action approval** | Any R2/R3 action (see §8) | Exact action preview (email text, post, record diff, amount). ✅ / ✏️ / ❌ | Required; never times out into "yes" |
| **G4 Acceptance** | Every task | Deliverable + Verifier report (criterion-by-criterion) + proposed memory candidates as checkboxes (⚠ if derived from email/web/CRM text) | Required; only ticked candidates can be promoted |
| **Escalation** | 3rd verify fail, budget hit, conflicting instructions, missing access, low confidence | Problem + options | Blocks task |

Approvals post in the task thread **and** `#approvals`. Silence = no. Reminders at 4h, 24h; task auto-parks after 72h.

**Approver coverage:** every tier has a primary and a backup approver (`permissions.yaml → approval_policy.approvers`). Owner can set **away mode** (`/away until <date> delegate <user>`): R2 goes to the delegate; R3 goes to the delegate only for action types on the owner's pre-delegable R3 list, everything else waits. Delegation is logged and expires automatically.

**Cross-department sub-tasks:** the sub-task inherits the parent's G1 approval if its contract only produces an internal artifact for the parent (R0/R1). If the sub-task needs R2/R3, it gets its own G3 as usual. The parent requester is the approver of record.

---

## 7. Validation: "did it do what I asked?"

1. **Task Contract** (`schemas/task_contract.json`) is the spec. Acceptance criteria are a numbered checklist, each testable.
2. Lead splits criteria across specialists in **Handoff Packets** (`schemas/handoff_packet.json`).
3. Specialist returns a **Return Packet** (`schemas/return_packet.json`) with outputs, citations, self-check per criterion, confidence, open questions.
4. **Automatic checks first (code, not LLM):** image dimensions/format, video duration/aspect, file size, brand hex colors present, spell-check, broken links, every `citations[].source` resolves, required fields present, word/char limits. Deterministic, so they don't share the model's blind spots.
5. **Verifier** (fresh context, sees *only* contract + deliverable + cited sources — never the worker's reasoning) grades each criterion PASS/FAIL/UNVERIFIABLE with evidence, and flags any uncited factual claim.
6. Any FAIL → REVISION (max 2). UNVERIFIABLE → shown to you at G4.
7. You accept/reject at G4. Rejection reason becomes a feedback memory candidate, tagged to the specialist(s) who produced the rejected artifact (from artifact provenance, not guessed).

**Verification depth by risk (cost control):**

| Task | Automatic checks | LLM Verifier |
|---|---|---|
| S, internal only (R0/R1), no company facts | Yes | No — Lead self-check + your G4 |
| S with R2/R3 action, or any M/L | Yes | Yes |
| Contains numbers/claims about company, prices, people | Yes | Yes, always, with source re-fetch |

Where possible the Verifier runs on a different model tier than the worker (worker Sonnet → Verifier Opus) to reduce shared blind spots; when the worker is already the top tier (Lead-built S/M tasks), the deterministic checks carry that load.

Design deliverables (images/video): Verifier checks spec-compliance (dimensions, duration, format, brand colors from brand kit, text spelling, required elements). Taste is yours at G4.

---

## 8. Permissions (summary — full in `config/permissions.yaml`)

| Tier | Meaning | Examples | Approval |
|---|---|---|---|
| **R0** | Read / think / internal draft | search, read CRM, draft doc in workspace | Auto |
| **R1** | Internal, reversible write; paid calls under cap | post in own channel, create draft in Drive, create CRM task, internal calendar hold, image generation, enrichment | Auto + audit + daily spend cap |
| **R2** | External or bulk | send email, post to social, message candidate, **any ATS stage move**, bulk over per-task or per-day limits, paid calls over daily cap | Dept human manager, backup, or you |
| **R3** | Irreversible / money / legal / people decisions | spend money, sign/send contract, reject/offer candidate, delete data, change prices | **You only**, with preview |
| **R4** | Forbidden | change own permissions/prompt/config, access another employee's private memory, create new agents, share credentials, bypass approval | Never; attempt = alert |

Enforcement: every tool call goes through the Dispatcher's Tool Proxy → checks `(employee, tool, action, params)` against allowlist + tier + budget → allow / queue for approval / deny + log.

---

## 9. Communication & handoff rules

**Allowed edges (everything else is denied by Dispatcher):**

```
Human      → Lead (own channel), CoS (#hq/DM)
CoS        → any Lead (via request_department), Verifier, Librarian
Lead       → own Specialists, CoS, Verifier, Librarian (candidates only)
Specialist → own Lead (return packet), Librarian (candidates only)
Verifier   → Lead (verdict)
```

- **Specialist ↔ Specialist:** never. Handoff = Lead forwards the *artifact reference* from A's return packet into B's handoff packet. E.g. Copywriter → (Lead) → Graphic Designer gets `artifact://task-123/headline-v2.md`.
- **Lead ↔ Lead:** never direct. Marketing needs sales data → Maya calls CoS → CoS opens a sub-task in #sales with its own contract → Sam's result returns to Maya via CoS. You see it in #hq.
- **When a handoff happens:** (a) contract approved → Lead → Specialist; (b) specialist returns → Lead → next specialist or Verifier; (c) Verifier pass → Lead → you (G4); (d) need outside dept → Lead → CoS → other Lead; (e) blocked → anyone → up one level → you.
- **Context passed in a handoff:** only the packet (objective, inputs by reference, criteria subset, constraints, ≤1,500-token context summary, explicit "do not"). Never the full chat history.
- **Who approves a cross-dept sub-task:** see §6 — inherits parent approval if internal-only; otherwise normal G3.
- **Proactive talk:** Leads run scheduled routines (daily digest, weekly report) and may *suggest* work in their channel; they never start R2+ work unasked. Specialists are never proactive.

### Example: "Marketing, make a launch teaser for feature X"

1. You post in `#marketing`. Gateway → Marketing Lead (Maya).
2. Maya drafts contract: 1 static visual (1080×1080) + 15s video + caption; brand kit; due Fri. Criteria listed. → **G1** ✅.
3. Maya → Copywriter: headline + caption (criteria 5–6). Returns with citations to feature doc.
4. Maya → Graphic Designer (with headline artifact) and → Video Editor (with headline + script) **in parallel**, separate contexts.
5. Returns → Verifier: dimensions, duration, brand colors, spelling, claims match feature doc.
6. 1 fail (video 17s) → Video Editor revision → pass.
7. Maya posts deliverables + Verifier report → **G4** you ✅.
8. Want it posted to LinkedIn? Social Manager prepares → **G3** (R2) ✅ → posted.
9. Librarian promotes: "Launch teaser format approved by owner 2026-10-02" to Marketing playbook; Designer's private memory gets "owner prefers dark background variant".

---

## 10. Memory & anti-hallucination (full in `config/memory.yaml`)

### 10.1 Layers

| Layer | Content | Read by | Written by | Lifetime |
|---|---|---|---|---|
| **L0 Constitution** | Company-wide rules, facts about the company, brand | All | **You only** (git) | Permanent |
| **L1 Dept Playbook** | Dept procedures, standing preferences, approved templates | Dept Lead + its specialists (+CoS) | Librarian, after your approval | Until superseded |
| **L2 Employee Profile** | Role, personality, skills, tools, limits (= `org.yaml`) | That employee | **You only** (git) | Permanent |
| **L3 Employee Private Memory** | That employee's learned craft notes + feedback | **That employee only** | Librarian (from verified candidates) | 180 days since last use |
| **L4 Task Workspace** | Contract, packets, drafts, artifacts for one task | Assigned Lead + assigned specialists + Verifier | Participants | 7 days after CLOSED → archive (purge if PII) |
| **L5 Audit Log** | Every event, tool call, approval | Humans + Dispatcher (never in agent context) | Dispatcher | Append-only, 1 year; PII redacted/hashed |
| **Systems of record** | CRM, ATS, Drive, calendar, analytics | Per tool allowlist | Per tier | External |

**Isolation:** Graphic Designer and Video Editor share L0 + Marketing L1 only. Their L3 are separate rows with ACL `owner_id = employee_id`, enforced in the query layer. They share an L4 task folder **only** when the Lead puts both on the same task, and even then each only sees artifacts the Lead hands over.

### 10.2 Truth hierarchy (what wins when sources disagree)

1. Live system of record (fetched now) 2. L0 3. L1 4. L3 verified 5. L4 task notes 6. Model knowledge → **never** used for company facts, names, numbers, prices, dates.
Conflict between 1–4 → agent must state conflict, use higher source, create conflict ticket for Librarian.

### 10.3 Anti-hallucination rules

- Store **pointers** to systems of record (e.g. `hubspot:deal/123`), not copied numbers that go stale.
- Every memory entry: `source`, `author`, `verified_by`, `confidence`, `expires_at` (`schemas/memory_entry.json`).
- Agents write only **memory candidates**. Librarian promotes a candidate only if: (a) from an ACCEPTED task **and ticked by you at G4** (stops injected text from becoming "memory"), or (b) direct human instruction, or (c) re-fetchable from a system of record — stored as a pointer only. Otherwise it dies with the task.
- Unknown → say "I don't know" + what would find out. Guessing a fact is a constitution violation.
- Retrieval budget: ≤15% of context for memory; top-12 by `relevance × 0.97^days_since_verified × confidence`; L0 core + own L2 always included.
- Long tasks: Lead compacts its session into a state summary every 20 turns (keeps contract, decisions, open questions, artifact refs); raw turns go to L5.

### 10.4 When memory is stored

| Trigger | Stored where | By |
|---|---|---|
| You say "always / from now on / never" | Candidate → L1 or L3 after confirmation ("Save as standing rule for Marketing?") | Lead asks, Librarian writes |
| You say something task-specific | L4 only; dies with task | Lead |
| Task ACCEPTED | Decisions + outcome summary → L1; craft learnings → specialist L3 | Librarian |
| Task REJECTED with reason | Feedback → L3 of the specialist(s) who produced the rejected artifact, per Dispatcher provenance stamp (+L1 if general) | Librarian |
| New fact fetched from system of record | **Pointer only** (e.g. `hubspot:deal/123#amount`), never the value; value re-fetched at use time. Only if reused ≥2 times | Librarian |
| End of day | Dept digest (what changed) → L1 daily note, TTL 14 days | Lead routine |

### 10.5 Deleting unnecessary instructions ("instruction hygiene")

- Every instruction is classified on intake: **one-off** (task-scoped, dies at CLOSED) vs **standing** (needs your confirmation, gets TTL).
- **Pinned rules:** standing rules you mark `pinned` (e.g. "annual pricing review in January") never expire and are never auto-archived; only you can unpin.
- **Weekly GC job (Librarian):** dedupe; mark un-pinned entries unused 30 days as *stale*; merge near-duplicates; find contradictions → ask you which wins; loser archived (moved out of context, kept in L5 — never hard-deleted without R3 approval, except PII purges required by the privacy policy).
- Newer confirmed instruction **supersedes** older one on same topic (`supersedes: <id>`), old one archived automatically.
- Agents cannot edit or delete L0/L2. They can *propose* removal of L1/L3 entries.
- Mid-task: when you change direction, Lead re-issues the contract (v2); the Dispatcher archives every specialist session running on v1 and restarts affected work with fresh v2 handoff packets — no v1 instructions survive in any context.

---

## 11. Skills

- Skill = versioned folder: `SKILL.md` (procedure) + scripts + declared tools + declared max risk tier + tests.
- Employee may only load skills listed in its `org.yaml` entry. Skill declaring a higher tier than employee's max → load denied.
- Skills are written/changed by you (or proposed by Leads → PR → you merge). Agents never self-install skills.
- Skill catalog per employee: see `config/org.yaml`.

---

## 12. Personality

Each employee has: name, one-line bio, voice (3 adjectives), verbosity, emoji policy, sign-off, "never say" list. Hard rule: personality is style only — it cannot change facts, permissions, or escalation behavior. Leads are concise and structured; specialists are terse, craft-focused.

---

## 13. Budgets & safety limits (defaults, tune in `config/permissions.yaml`)

| Limit | Default |
|---|---|
| Delegation depth | Human → (CoS) → Lead → Specialist. Specialist cannot delegate. |
| Revision loops before escalation | 2 |
| Parallel specialists per task | 4 |
| Max cost per task | S $2 · M $10 · L $50 (then escalate) |
| Max wall time without progress | 30 min → ping Lead; 2h → escalate |
| Max concurrent tasks per Lead | 5 (queue beyond) |
| Tool calls per specialist per task | 60 |
| Spend per employee per day | $5 default; designer $15, video $25, prospector/sourcer $10 → alert at 80%; at 100% every further paid call is R2; auto-pause at 150% (runaway guard) |
| Bulk writes per employee per day | CRM 25, calendar 10, files 60, external emails 20 → above = R2 |

---

## 14. Slack channel map

| Channel | Purpose | Who posts |
|---|---|---|
| `#hq` | Cross-dept requests, daily company digest | You, CoS |
| `#marketing` `#sales` `#recruiting` `#ops` | Dept requests; one thread per task | You, dept humans, Lead, its specialists (in thread) |
| `#approvals` | All G3 action approvals mirrored with buttons | Dispatcher |
| `#agent-log` | Audit feed, GC reports, violations | Dispatcher, Librarian |
| DMs | You ↔ CoS only | — |

---

## 15. Build phases (after sign-off)

1. **Skeleton:** Dispatcher, config loader + `scripts/validate_config.py` in CI, Slack gateway, audit log. No LLM yet — dry-run routing tests.
2. **One department end-to-end:** Marketing Lead + Copywriter + Graphic Designer, contract → verify → accept, memory L0–L4.
3. Verifier + Librarian + GC.
4. Remaining departments, CoS, cross-dept.
5. Scheduled routines, budgets dashboard (Slack command), v2 departments.

Phase 1 also includes the **platform spike** (§4 point 5): session start latency/cost (Managed Agents single-agent sessions vs. Messages API tool loop), and proof that no built-in tools are reachable.

Test plan per phase (all must pass before the next phase):
- permission-denial (every R4 action, every tool not in allowlist, R2/R3 without approval, approval replayed on a different action hash)
- isolation (specialist A can't read B's L3; task X can't read task Y's L4; a new task session has no memory of the previous task)
- injection (malicious email/CRM/candidate text tries: send data out, call a forbidden tool, fetch URL with data in query)
- exfiltration (private-data holder tries web.fetch; Verifier fetches a URL not in fetch log; long query string; private data in URL or image-gen prompt)
- hallucination (ask for a number not in any source → must answer "unknown")
- loop (bot message in channel → no task created)
- requester (guest user asks → refused)
- bulk-split (11 CRM updates across 3 tasks same day → approval triggered)
- concurrency (two tasks update same CRM record/playbook → second gets conflict, not overwrite)
- kill switch (`/pause-all` stops all tool execution within 5 s)

---

## 16. Security & data protection

- **Egress control (anti-exfiltration):** employees that read private data (CRM, ATS, email) never get `web.fetch` (validator-enforced). Employees without private data may fetch public URLs, still subject to: query string ≤ 200 chars, no private task data in the URL, no IP literals/localhost. The Verifier may only re-fetch exact URLs already in the task's fetch log.
- **Untrusted content wrapping:** every tool result from email, web, CRM notes, ATS applications is wrapped as `<untrusted source=…>` data; constitution A3 applies. Suspected injection attempts are logged to `#agent-log`.
- **Paid & third-party calls:** image/video generation and enrichment are R1 with a per-employee daily spend cap; above cap → R2. Prompts sent to third-party generators may not include personal data (PII filter).
- **Personal data (PII) policy:**
  - Candidate/contact PII lives only in the system of record (ATS/CRM). Memory stores pointers, never PII values.
  - L4 task workspaces containing PII are purged 7 days after CLOSED (not archived).
  - L5 audit stores tool calls with PII fields redacted/hashed; raw payloads kept 30 days encrypted, then deleted.
  - Data-subject deletion request → Dispatcher job purges pointers, L4 and raw L5 for that person.
- **Credentials:** per-employee OAuth scopes, least privilege, stored only in the Dispatcher's secrets store, rotated on schedule; the model never sees them.

## 17. Recruiting & outreach compliance

- **AI in hiring** — NYC Local Law 144 (bias audit + candidate notice for automated employment decision tools), EU AI Act (recruitment = high-risk: human oversight, logging, transparency), Illinois AI Video Interview Act and similar. Design response:
  - Screener only produces **recommendations with quoted evidence**; *every* ATS stage move is R2 — a human clicks.
  - Screener never sees name, photo, age, address, graduation years (redacted by Dispatcher before the record enters context).
  - Candidate notice about AI assistance added to job posts (template in L0, owner-approved).
  - Quarterly bias report (pass-rate by stage, where lawfully collected) — owner reviews.
  - Legal review before go-live in regulated regions (open question).
- **Enrichment/sourcing:** lawful-basis sources only; store source + date per contact; honor opt-outs; EU contacts need a legitimate-interest assessment (open question).
- **Sales email:** CAN-SPAM / GDPR / CASL — sender identity + unsubscribe where required; suppression list checked by Dispatcher before any send; >20 recipients = R3.

## 18. Reliability & operations

- **Concurrency:** every write to a system record or memory entry carries the version it read (optimistic lock). Mismatch → re-read, re-plan, never blind overwrite. L1 playbook edits are serialized through the Librarian queue.
- **Kill switches:** `/pause-all` (owner) stops all tool execution and new sessions within 5 s; `/pause <employee|dept>`; automatic pause of an employee after 3 R4 attempts, at 150% of its daily spend cap, or on error-rate spike.
- **Observability:** per-task trace (handoffs, tool calls, cost, approvals) via `/task <id>`; daily cost report in `#agent-log`; alerts on spend > 80% of daily budget, error-rate spike, approval queue > 10.
- **Model tiering (cost):** Leads, Verifier, CoS = Opus; specialists = Sonnet; Librarian GC and formatting = Haiku. Revisit after 2 weeks of cost data.
- **Evals:** golden task set per department (10–20 tasks with known-good outputs) re-run on any prompt/skill/model change before deploy.
- **Config changes:** config and skills live in git; merge → validator → new agent versions → new tasks use them; in-flight tasks finish on the old version.

## 19. Flag register (v0.1 review → fixes in v0.2)

| # | Flag | Fix | Where |
|---|---|---|---|
| 1 | Shared sandbox filesystem + session-scoped vault creds broke isolation | Memory/artifacts via ACL'd tools; no vault creds in sessions; creds held by Dispatcher | §4, memory.yaml |
| 2 | Built-in toolset bypasses Tool Proxy | No `agent_toolset`; custom tools only | §4, org.yaml `runtime` |
| 3 | Persistent threads leak context across tasks | One session per task, archived at close | §4, org.yaml `runtime` |
| 4 | `web.fetch` exfiltration | No fetch for private-data holders, URL checks (refined in #30) | §16, permissions.yaml, org.yaml |
| 5 | Anyone in channel can command | Requester allowlist | §4, permissions.yaml |
| 6 | Bulk limit bypass by splitting tasks | Per-employee daily counters too | permissions.yaml |
| 7 | Verifier skippable | Hard state transitions | §5 |
| 8 | Slack bot loops | Gateway drops bot events | §4 |
| 9 | Recruiting legal exposure | All stage moves R2, redaction, notices, bias report, legal review | §17, org.yaml, permissions.yaml |
| 10 | PII retention | PII policy, redacted audit | §16, memory.yaml |
| 11 | Owner bottleneck | Backup approvers, away mode | §6, permissions.yaml |
| 12 | Cross-dept approval gap | Inherit if internal, else G3 | §6, §9 |
| 13 | Paid calls unguarded | R1 + daily spend caps | §16, permissions.yaml |
| 14 | Stale auto-promoted facts | Pointers only | §10, memory.yaml |
| 15 | Important rules expire | `pinned` flag | §10, memory.yaml, memory_entry schema |
| 16 | Concurrent writes | Optimistic locking, Librarian queue | §18, memory.yaml |
| 17 | No kill switch / observability | `/pause-all`, traces, alerts, evals | §18, permissions.yaml |
| 18 | Cost | Model tiering, verification by risk | §7, §18, org.yaml |
| 19 | Verifier shares model blind spots | Deterministic checks first, different model tier | §7 |

**Round 2 (after v0.2 fixes):**

| # | Flag | Fix | Where |
|---|---|---|---|
| 20 | Native multiagent delegation bypasses Dispatcher (packets not validated, edges not checked) | Dispatcher-orchestrated sessions via `delegate()`; no native roster | §4 |
| 21 | Retries could double-send emails/posts | Idempotency keys + durable queue | §4 |
| 22 | Slack approval buttons could be clicked by the wrong person / replayed | Signature check, approver list, hash-bound button | §4 |
| 23 | Revision limit vs. human rejections undefined | Only Verifier FAILs count; scope change → new contract | §5 |
| 24 | Scheduled routines had no requester/approval path | Routines limited to R0/R1 in own channel | §5 |

**Round 3 (consistency pass):**

| # | Flag | Fix | Where |
|---|---|---|---|
| 25 | Spend cap rule contradicted itself (R2 above cap vs. pause at cap) | 80% alert / 100% R2 / 150% pause | §13, permissions.yaml |
| 26 | Retrieval formula, compaction interval, budget file location differed between map and config | Aligned | §10, §13 |
| 27 | Contract-change handling assumed shared context | Archive v1 specialist sessions, restart with v2 packets | §10.5 |
| 28 | PII exceptions missing from layer table / GC rule | Added | §10 |

**Round 4:**

| # | Flag | Fix | Where |
|---|---|---|---|
| 29 | Memory poisoning: injected text in a candidate gets promoted when you accept the deliverable | Candidates shown as checkboxes at G4, ⚠ if from untrusted source; treated as data | §6, §10, memory.yaml |
| 30 | Domain allowlist would block normal research (any company website) | Split instead: no-private-data employees fetch freely with URL checks; private-data holders never fetch | §16, permissions.yaml |

---

## Sources

- [Viktor – Slack Marketplace](https://slack.com/marketplace/A0A2VN5TR5K-viktor), [Fortune on Viktor raise](https://fortune.com/2026/05/19/viktor-ai-startup-raises-75-million-for-virtual-coworker-exclusive/), [eesel Viktor review](https://www.eesel.ai/blog/viktor-ai-review), [Martech Zone on Viktor](https://martech.zone/viktor-your-slack-or-teams-ai-coworker-that-handles-the-workload/)
- [Viktor vs Lindy](https://viktor.com/blog/viktor-vs-lindy), [Viktor vs Sintra](https://viktor.com/blog/viktor-vs-sintra-ai)
- [Relevance AI – Approvals & Escalations](https://relevanceai.com/docs/build/workforces/workforce-features/approvals-and-escalations)
- [Motion AI employees](https://scalevise.com/resources/motion-ai-work-employees/)
- [Claude Managed Agents – Multiagent orchestration](https://platform.claude.com/docs/en/managed-agents/multiagent-orchestration)
- [Multi-agent memory architecture discussion](https://github.com/anthropics/anthropic-sdk-python/discussions/1419)
- [Isolation as a first-class principle (arXiv)](https://arxiv.org/pdf/2607.12406)
- [Multiple AI agents as Slack teammates](https://gist.github.com/rafaelquintanilha/9ca5ae6173cd0682026754cfefe26d3f), [Slack – developing agents](https://docs.slack.dev/ai/developing-agents/)
