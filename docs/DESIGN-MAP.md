# AI Workforce — Design Map (v0.1, pre-build)

Status: **DESIGN ONLY. Nothing gets built until this map is signed off.**
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

---

## 1. Research summary (what exists, what we copy, what we fix)

| Product | Model | Copy | Avoid |
|---|---|---|---|
| **Viktor** (viktor.com) | One shared AI coworker in Slack/Teams, 3k integrations, long-running shared memory, asks before irreversible actions | Slack-native, @mention UX, "ask before irreversible", persistent company context | One brain for everything → context bloat; RBAC / per-user scoping / private mode still unshipped |
| **Relevance AI** "Workforce" | Canvas of agents with roles + tools; approval gates on the *edges* between agents/tools | Approval on edges, escalation paths, task view | Builder-first, not Slack-native |
| **Motion** AI Employees | Pre-built role agents (Sales, Marketing, HR, Support, PM, Research) | Department catalog | Dashboard-bound |
| **Sintra** | Pre-built persona "helpers" in own dashboard | Named personalities | Not in Slack, shallow |
| **Lindy** | Visual workflow builder | Deterministic triggers | Workflow ≠ employee |
| **Anthropic Managed Agents – multiagent** | Coordinator + roster (≤20 agents), each agent own model/prompt/tools/skills, **isolated context thread**, shared filesystem, **only 1 level of delegation** | Exact fit for "Dept Lead → Specialists" | Can't nest (CoS → Lead → Specialist) → our backend handles the top level |
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
  Dept sessions         Verifier sessions        Librarian jobs
  (Claude Managed Agents:  (fresh context per       (promotion, GC,
   coordinator = Lead,     verification)             conflict check)
   roster = specialists,
   isolated threads)
        │
        ▼
 Storage: Postgres (tasks, approvals, memory, audit) + pgvector (retrieval)
          Object store (artifacts: images, videos, docs) · Secrets vault (per-agent creds)
```

- **Why Managed Agents for departments:** coordinator + isolated specialist threads + per-agent tools/skills is native. Limit: 1 delegation level and 20 roster agents — fits one department.
- **Why CoS is outside that:** CoS → Lead → Specialist is 2 levels. CoS gets a custom tool `request_department(dept, contract)`; the Dispatcher opens a task in that department. Cross-dept hops are therefore always visible, logged, and gated.
- **Slack identity:** v1 = one Slack app, personas via `chat:write.customize` (per-employee name + avatar). Channel = routing (message in `#marketing` → Marketing Lead). v2 option = one Slack app per Lead for real @mentions.

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

---

## 6. Human-in-the-loop gates

| Gate | When | What you see | Default |
|---|---|---|---|
| **G1 Contract** | Every M/L task; S tasks only if ambiguous | Lead restates: objective, deliverables, acceptance criteria, deadline, constraints, out-of-scope. Buttons: ✅ Go / ✏️ Edit / ❌ Cancel | Required M/L. S auto-starts after 0 min but shows contract |
| **G2 Plan** | L tasks | Who does what, order, handoffs, est. cost | Required |
| **G3 Action approval** | Any R2/R3 action (see §8) | Exact action preview (email text, post, record diff, amount). ✅ / ✏️ / ❌ | Required; never times out into "yes" |
| **G4 Acceptance** | Every task | Deliverable + Verifier report (criterion-by-criterion) | Required; acceptance triggers memory promotion |
| **Escalation** | 3rd verify fail, budget hit, conflicting instructions, missing access, low confidence | Problem + options | Blocks task |

Approvals post in the task thread **and** `#approvals`. Silence = no. Reminders at 4h, 24h; task auto-parks after 72h.

---

## 7. Validation: "did it do what I asked?"

1. **Task Contract** (`schemas/task_contract.json`) is the spec. Acceptance criteria are a numbered checklist, each testable.
2. Lead splits criteria across specialists in **Handoff Packets** (`schemas/handoff_packet.json`).
3. Specialist returns a **Return Packet** (`schemas/return_packet.json`) with outputs, citations, self-check per criterion, confidence, open questions.
4. **Verifier** (fresh context, sees *only* contract + deliverable + cited sources — never the worker's reasoning) grades each criterion PASS/FAIL/UNVERIFIABLE with evidence, and flags any uncited factual claim.
5. Any FAIL → REVISION (max 2). UNVERIFIABLE → shown to you at G4.
6. You accept/reject at G4. Rejection reason becomes a feedback memory candidate.

Design deliverables (images/video): Verifier checks spec-compliance (dimensions, duration, format, brand colors from brand kit, text spelling, required elements). Taste is yours at G4.

---

## 8. Permissions (summary — full in `config/permissions.yaml`)

| Tier | Meaning | Examples | Approval |
|---|---|---|---|
| **R0** | Read / think / internal draft | search, read CRM, draft doc in workspace | Auto |
| **R1** | Internal, reversible write | post in own channel, create draft in Drive, create CRM task, add internal calendar hold | Auto + audit |
| **R2** | External or bulk | send email, post to social, message candidate, update >10 CRM records, publish page | Dept human manager or you |
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
| **L4 Task Workspace** | Contract, packets, drafts, artifacts for one task | Assigned Lead + assigned specialists + Verifier | Participants | 7 days after CLOSED → archive |
| **L5 Audit Log** | Every event, tool call, approval | Humans + Dispatcher (never in agent context) | Dispatcher | Append-only, 1 year |
| **Systems of record** | CRM, ATS, Drive, calendar, analytics | Per tool allowlist | Per tier | External |

**Isolation:** Graphic Designer and Video Editor share L0 + Marketing L1 only. Their L3 are separate rows with ACL `owner_id = employee_id`, enforced in the query layer. They share an L4 task folder **only** when the Lead puts both on the same task, and even then each only sees artifacts the Lead hands over.

### 10.2 Truth hierarchy (what wins when sources disagree)

1. Live system of record (fetched now) 2. L0 3. L1 4. L3 verified 5. L4 task notes 6. Model knowledge → **never** used for company facts, names, numbers, prices, dates.
Conflict between 1–4 → agent must state conflict, use higher source, create conflict ticket for Librarian.

### 10.3 Anti-hallucination rules

- Store **pointers** to systems of record (e.g. `hubspot:deal/123`), not copied numbers that go stale.
- Every memory entry: `source`, `author`, `verified_by`, `confidence`, `expires_at` (`schemas/memory_entry.json`).
- Agents write only **memory candidates**. Librarian promotes a candidate only if: (a) from an ACCEPTED task, or (b) direct human instruction, or (c) re-fetchable from a system of record. Otherwise it dies with the task.
- Unknown → say "I don't know" + what would find out. Guessing a fact is a constitution violation.
- Retrieval budget: ≤15% of context for memory; top-k by `relevance × recency`.
- Long tasks: Lead compacts its thread into a state summary every N turns; raw turns go to L5.

### 10.4 When memory is stored

| Trigger | Stored where | By |
|---|---|---|
| You say "always / from now on / never" | Candidate → L1 or L3 after confirmation ("Save as standing rule for Marketing?") | Lead asks, Librarian writes |
| You say something task-specific | L4 only; dies with task | Lead |
| Task ACCEPTED | Decisions + outcome summary → L1; craft learnings → specialist L3 | Librarian |
| Task REJECTED with reason | Feedback → L3 of responsible specialist (+L1 if general) | Librarian |
| New fact fetched from system of record | Pointer only, if reused ≥2 times | Librarian |
| End of day | Dept digest (what changed) → L1 daily note, TTL 14 days | Lead routine |

### 10.5 Deleting unnecessary instructions ("instruction hygiene")

- Every instruction is classified on intake: **one-off** (task-scoped, dies at CLOSED) vs **standing** (needs your confirmation, gets TTL).
- **Weekly GC job (Librarian):** dedupe; mark entries unused 30 days as *stale*; merge near-duplicates; find contradictions → ask you which wins; loser archived (moved out of context, kept in L5 — never hard-deleted without R3 approval).
- Newer confirmed instruction **supersedes** older one on same topic (`supersedes: <id>`), old one archived automatically.
- Agents cannot edit or delete L0/L2. They can *propose* removal of L1/L3 entries.
- Mid-task: when you change direction, Lead re-issues the contract (v2) and the Dispatcher drops v1 packets from specialists' context.

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

## 13. Budgets & safety limits (defaults, tune in `org.yaml`)

| Limit | Default |
|---|---|
| Delegation depth | Human → (CoS) → Lead → Specialist. Specialist cannot delegate. |
| Revision loops before escalation | 2 |
| Parallel specialists per task | 4 |
| Max cost per task | S $2 · M $10 · L $50 (then escalate) |
| Max wall time without progress | 30 min → ping Lead; 2h → escalate |
| Max concurrent tasks per Lead | 5 (queue beyond) |
| Tool calls per specialist per task | 60 |

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

1. **Skeleton:** Dispatcher, config loader + validator (org/permissions/memory), Slack gateway, audit log. No LLM yet — dry-run routing tests.
2. **One department end-to-end:** Marketing Lead + Copywriter + Graphic Designer, contract → verify → accept, memory L0–L4.
3. Verifier + Librarian + GC.
4. Remaining departments, CoS, cross-dept.
5. Scheduled routines, budgets dashboard (Slack command), v2 departments.

Test plan per phase: permission-denial tests (R4 attempts), isolation tests (specialist A can't read B's L3), injection tests (malicious email content asking agent to send data), hallucination tests (ask for a number not in any source → must answer "unknown").

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
