# Org v3 — proposal (not applied)

Status: **proposal only**. No code changed on this branch except: 7 skills copied into `.claude/skills/` and parked under `unassigned.v3_pending` in `config/skills.yaml` (the validator requires every skill on disk to be listed). Skill details: `docs/SKILLS-INVENTORY.md`.

Rule kept from v1/v2: **the Dispatcher stays in charge.** G1–G4 approvals, machine checks, budgets, memory ACLs, show/lane isolation and the audit log are all in Dispatcher code. Nothing in v3 lets one employee's session reach another except through a Dispatcher tool that runs `Policy.check` first.

---

## 1. Current state (branch `busy-franklin`, 2026-10-01)

| Area | Fact |
|---|---|
| Employees | **41** (not 36): core 4, Studio 11, Sales 15, Talent 2, Engineering 6, Ops 3. One `context/<id>.md` each |
| Models | Leads, Vera, Proof = `claude-sonnet-5-5`. Every specialist, Atlas, Lex = `claude-haiku-4-5` |
| Sessions | One fresh Agent SDK session per employee per step. No resume, no effort setting, no fallback model |
| Talk between employees | None. Output of step N is pasted into the prompt of step N+1 (`_upstream`) |
| Skills | Route's `SKILL.md` text is pasted into the system prompt. `references/` and `scripts/` are not readable by the session |
| Budget | $20/month plan credit, hard pause at 100 %; per task S $0.5 / M $2 / L $6 |
| Tests | `pytest`: **141 passed, 1 skipped** (BUILD-STATUS says 140). Needs Python ≥ 3.11; `pip install -e` fails on pip 21 (no `[build-system]`), `uv` works |
| Agent SDK | `claude-agent-sdk>=0.2.161`; resolves to **0.2.168**, which has `resume`, `session_id`, `fork_session`, `effort`, `fallback_model`, `thinking`, `agents`. `SDKRunner` still never run live |

## 2. Problems

| # | Problem | Where | Kind |
|---|---|---|---|
| A1 | `dispatcher.py` is 2,321 lines, ~95 methods: contract, plan, tool building, verification, delivery, routines, hiring in one class | `workforce/dispatcher.py` | too big |
| A2 | Haiku 4.5 on 34 employees. Haiku 5.5 costs **$0.10/$0.50 per MTok vs $1/$5** (10× cheaper) and is newer | `config/org.yaml:77,95,134`, `workforce/config.py:67` (`HIRE_DEFAULTS`), `frontend/src/lib/demoOffice.json` | outdated |
| A3 | One model per employee for every phase; no `effort`, no `fallback_model`. A Lead plans a 1-step S task at the same cost as an L task | `workforce/agents.py` | outdated |
| A4 | Every step re-reads the whole contract + upstream outputs in a fresh session. A Lead runs 3 cold sessions per task (contract, plan, delivery) | `dispatcher.py` `_run` | waste |
| A5 | A writer that lacks a fact cannot ask Intel. It guesses or fails; Proof catches it; a whole revision round follows | flow design | waste |
| A6 | Skills with references (new-claude, free-llm-apis, hyperframes, ui-ux-pro-max data) only reach the session as SKILL.md text | `routing.skill_text` | gap |
| A7 | Fixed monthly burn before any request: daily inbox scan (2 runs) + daily digest (1 run) ≈ 90 Haiku 4.5 runs ≈ **$5.40 = 27 % of the credit** (estimate, §5) | `org.yaml` routines | cost |
| A8 | Two runtimes with the same `/exec` + `/voice` API | `deploy/modal_app.py`, `deploy/runtime_server.py` | duplicated |
| A9 | Docs describe a stack that was dropped: HeyGen, OpenVoice, AWS, Managed Agents, "Haiku for specialists" | `docs/OPEN-QUESTIONS.md`, `docs/DESIGN-MAP.md` §hosting/§tiering | outdated |
| A10 | Tracked file in an ignored folder; stale skill copies (`sherlock` older than owner's 10-13 copy; `jai` vs `jai-insta`) | `outbox/*.eml`, `.claude/skills/` | dead |
| A11 | No repo `CLAUDE.md`, so cloud sessions working **on** the repo start cold | repo root | gap |
| A12 | Native multi-agent tools are off only by omission (`tools=[]`). Nothing tests that `SendMessage`/`ListAgents`/`Agent` stay unavailable | `agents.py` | risk |
| A13 | `live.py` events are in memory only; restart loses the feed (snapshot reloads) | `workforce/live.py` | acceptable now |

## 3. New design

### 3a. Dispatcher split (same behaviour, smaller files)
| New module | Moves from `dispatcher.py` | ~lines |
|---|---|---|
| `contracts.py` | `draft_contract`, `plan`, `validate_contract`, `validate_plan`, `validate_pending_actions`, `_show_problem` | 500 |
| `toolbox.py` | `_common_tools` … `_submit_return_tool` (all tool builders) | 450 |
| `verification.py` | `factcheck`, `verify*`, `_vera`, `_needs_proof`, `_needs_llm_verifier` | 300 |
| `delivery.py` | `deliver`, `accept`, `reject`, `run_approved_action`, `_child_finished` | 300 |
| `routines.py` | `due_routines`, `run_routine`, `sweep`, `digest`, `hire`, `end_probation` | 300 |
| `dispatcher.py` | message intake, `execute`, `_run`, `_guard`, budget | ~500 |

### 3b. Model ladder (from ECC `model-route` + Agent SDK `fallback_model` / `effort`)
| Tier | Model | Used for |
|---|---|---|
| T0 | none (code) | Lex, all checks, routing, show/lane triggers |
| F | free LLM via new `llm.free` tool (Groq `openai/gpt-oss-120b` first, Gemini Flash second) | Public-web text only: summarise fetched pages, rank job posts/rabbit holes, draft Reddit-story adaptations, chitchat/intent classification |
| T1 | `claude-haiku-5-5`, effort `low`–`medium` | Default specialist; routines; Atlas |
| T2 | `claude-sonnet-5-5`, effort `low`/`medium` | Leads, auditors, writers whose text goes out under the owner's name, engineers |
| T3 | `claude-opus-5-5`, effort `medium` | Only on attempt 3 of an L task, or Forge `architecture` route |
| Advisor | `claude-opus-5-5` as **advisor** to a T1/T2 executor (Claude Code 2.1.299 `/advisor`, setting `advisorModel`) | Hard routes only: Forge plans, Byte/Byte-Co/Loom `implement`, Architect, show producers' first build. The executor runs the whole step cheaply and consults Opus at key moments instead of the whole step moving to Opus |

Ladder rule: attempt 1 runs the employee's tier (with an advisor on hard routes); a failed machine check moves attempt 2 one tier up (`fallback_model` for API errors). Per-phase effort lives in `skills.yaml` routes (`effort: low`).

Advisor caveat: the binary warns that some advisor models "bill to usage credits", and this workforce runs with usage credits disabled. Before turning it on, run one live check: if Opus 5.5 as advisor bills to usage credits on the Pro plan, leave the advisor off (`CLAUDE_CODE_DISABLE_ADVISOR_TOOL=1`) and keep the plain ladder.

`llm.free` guard (Dispatcher-side, like `web.fetch`): refused for any employee holding a `private_data_tools` item; input must pass `pii.find_pii`; input must be only fetched public pages or the owner's request text marked public; output is wrapped as untrusted; never the final deliverable; on 429 fall back to T1. Reason: Gemini and Mistral free tiers may train on prompts.

### 3c. Session talk — Dispatcher-relayed, not native
Claude Code 2.1.299 lets live sessions on one machine message each other (`SendMessage` / `ListAgents` over a local socket, `notify_when_idle`, experimental agent teams). Every workforce session runs on the same server, so native messaging would let Jai's producer reach Sherlock's writer with no `Policy.check`, no budget and no audit. It stays **off**: `disallowed_tools=[SendMessage, ListAgents, Agent, Task]`, blank `CLAUDE_CODE_MESSAGING_SOCKET` / `CLAUDE_CODE_MESSAGING_TOKEN` and unset `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` in each session's `env`, plus a test (A12). The useful part — a session that stays open and can ask a peer — is built from SDK `resume`:

| Mode | How | Who |
|---|---|---|
| **Resumed lead** | One `session_id` per Lead per task; contract → plan → delivery are new turns in it (cached prefix) | Maya, Sam, Forge, Otto, Rhea |
| **Peer ask** | New tool `peer_ask(to, question)`. Dispatcher checks: same task, `to` is upstream/downstream in the plan, same show/lane, ≤ 3 asks per pair per task, budget left, PII + untrusted wrap. Answer = one new turn in the peer's resumed session, logged to audit and Live Office as a note handoff | Writers ↔ Intel/Burrow; show producer ↔ show designer; Apply ↔ Letter; Byte/Byte-Co/Loom ↔ Audit |
| **One-shot** | Unchanged | Everyone else, and always Vera + Proof (I7: auditors stay fresh and memoryless) |

Sessions close at task end (I8 still holds: nothing outlives the task). G1–G4, checks, budgets and memory ACLs are unchanged because `peer_ask` is a Dispatcher tool like every other.

### 3d. Caveman for internal text
| Text | Mode |
|---|---|
| Handoff `context_summary`, `submit_return.notes`, `peer_ask` questions/answers, plan rationale, Live Office notes | `caveman` full (system-prompt block) |
| Long, stable prompt files: `config/constitution.md`, `context/<id>.md` | `caveman-compress` once, owner reviews diff, original kept as `.original.md` |
| Owner-facing Slack posts, delivery notes, G-cards, any outbound email/CV/caption/script | **never** (normal prose; humanizer still applies) |

## 4. Employees (41 → 40)

Session: **R** resumed lead · **P** peer-ask enabled · **1** one-shot. Model: tier from §3b. Free = may call `llm.free`.

| # | Employee | Verdict | Model (effort) | Free | Skills added | Session |
|---|---|---|---|---|---|---|
| 1 | Atlas · chief_of_staff | keep | T1 Haiku 5.5 (low) | intent only | caveman | 1 |
| 2 | Vera · verifier | keep | T2 Sonnet 5.5 (medium) | no | — | 1 |
| 3 | Proof · fact_checker | keep | T2 Sonnet 5.5 (medium) | no | — | 1 |
| 4 | Lex · librarian | keep | **T0 code** (no model; today Haiku 4.5 is listed but unused) | no | — | — |
| 5 | Maya · studio_lead | keep | T2 Sonnet 5.5 (low plan / medium delivery) | no | caveman | R |
| 6 | Reel · studio_faceless_editor | keep | T1 → T2 on retry | no | — | 1 |
| 7 | Pixel · studio_designer | keep | T1 Haiku 5.5 | no | — | 1 |
| 8 | Jai · show_jai_producer | keep | T1 → T2 on retry | no | `jai-insta` (replaces `jai` after diff review) | P |
| 9 | Jai-Design | keep | T1 | no | — | P |
| 10 | Sherlock · producer | keep | T1 → T2 on retry | no | refreshed `sherlock` | P |
| 11 | Sherlock-Design | keep | T1 | no | — | P |
| 12 | Peter · producer | keep | T1 | no | — | P |
| 13 | Peter-Design | keep | T1 | no | — | P |
| 14 | Striker · producer | keep | T1 → T2 on retry | no | — | P |
| 15 | Striker-Design | keep | T1 | no | — | P |
| 16 | Sam · sales_lead | keep | T2 (low plan / medium delivery) | no | caveman | R |
| 17 | Scout · sales_scout | keep | T1 | **yes** (rank posts) | `pinloop` | 1 |
| 18 | Intel · sales_researcher | keep | T1 (+ free page summaries) | **yes** | caveman | P |
| 19 | Hook · outreach_writer | keep | **T2** Sonnet 5.5 (low) — outbound under your name | no | — | P |
| 20 | Burrow · rabbit_hole_finder | keep | T1 | **yes** (pre-filter) | `sherlock-ideas` (Sherlock tasks only) | P |
| 21 | Letter · cover_letter_writer | keep | **T2** (low) | no (private) | — | P |
| 22 | Track · pipeline_tracker | **merge into Scan** | — | — | — | — |
| 23 | Scan · inbox_scanner (+ pipeline) | keep, absorbs Track's `pipeline_update` route + tools | T1 (low) | no (private) | — | 1 |
| 24 | Apply · application_writer | keep | **T2** (low) | no (private) | — (docx/pdf on server) | P |
| 25 | Pitch · proposal_writer | keep | **T2** (low) | no | — | P |
| 26 | Script · script_writer | keep | T1 | no | — | P |
| 27 | Jai-Writer | keep | **T2** (low) — your own voice | no | — | P |
| 28 | Sherlock-Writer | keep + new route `topic_pitch` | T1 | no | `sherlock-ideas` | P |
| 29 | Peter-Writer | keep | T1 (+ free first draft) | **yes** | — | P |
| 30 | Striker-Writer | keep | T1 | no | — | P |
| 31 | Rhea · talent_lead | keep (idle costs $0) | T2 (low) | no | — | R |
| 32 | Architect · talent_architect | keep | T2 (medium) | no | `writing-for-agents` stays | 1 |
| 33 | Forge · eng_lead | keep | T2; `architecture` route T3 | no | `new-claude` (planner, architect agents) | R |
| 34 | Byte · eng_backend | keep | T2 (medium) | no | `new-claude` (tdd-guide, build-resolver) | P |
| 35 | Byte-Co · eng_backend_company | keep (lane isolation) | T2 (medium) | no | `new-claude` | P |
| 36 | Loom · eng_frontend | keep | T2 (medium) | no | `new-claude` | P |
| 37 | Audit · eng_qa | keep | T2 (medium) | no | `new-claude` (code-reviewer, security-reviewer) | P |
| 38 | Gear · eng_automation | keep | T1 | no | — | 1 |
| 39 | Otto · ops_lead | keep | T2 (low) | no | — | R |
| 40 | Ledger · ops_bookkeeper | keep | T1 (medium) | no (private) | — (xlsx on server) | 1 |
| 41 | Gauge · ops_reporting_analyst | keep | T1 | no (private) | — (xlsx on server) | 1 |

No new employees. New work goes to an existing owner as a route: `topic_pitch` (Sherlock-Writer). The daily Sherlock carousel stays outside the workforce (your decision). Track merges into Scan because both hold the same private data and always run back-to-back at 09:00 (saves 30 runs/month and one handoff).

## 5. Cost (estimates — measure from `AuditEvent.agent_run` costs after 2 weeks)

Assumed per run: 120 K cached input read, 20 K fresh input, 6 K output.

| Per run | Sonnet 5.5 | Haiku 4.5 | Haiku 5.5 | Free LLM |
|---|---|---|---|---|
| Cost | ~$0.12 | ~$0.06 | ~$0.006 | $0 |

| Workload | v2 | v3 | Main lever |
|---|---|---|---|
| Fixed routines/month (scan + track + digest) | ~$5.40 | ~$0.36 | Haiku 5.5, Track→Scan merge |
| M Sales task (Sam ×3, Intel, Hook, Proof, Vera) | ~$0.72 | ~$0.45 | Resumed lead, Haiku 5.5, Vera skipped when Proof passes on S/M |
| M video task | ~$0.90 | ~$0.55 | Haiku 5.5 first attempt, ladder only on failure |
| Tasks per $20 (M mix) | ~18 after routines | ~40 | — |

Caveman alone: internal text is roughly a third of tokens; published results cut that part by 8.5 % (output) to 33 % (input), so **~3–10 % of the bill ≈ $0.60–2/month**. Worth doing because it is cheap to add, but the model change is ~10× bigger. Free LLMs: removes the page-summary and ranking share of Intel/Scout/Burrow runs from the plan credit; expect a further ~5–10 %, limited by Groq's 1,000 requests/day.

## 6. Migration (in order, one PR each, tests green after each)

| Step | Change | Risk | Mitigation |
|---|---|---|---|
| 1 ✅ | Docs: repo `CLAUDE.md`; fix OPEN-QUESTIONS, DESIGN-MAP, BUILD-STATUS (41 employees, 141 tests); delete tracked `outbox/*.eml`; add `[build-system]` to `pyproject.toml` | none | — |
| 2 ✅ | Split `dispatcher.py` per §3a, no behaviour change (done: dispatcher 667 lines + 5 mixins + `dispatch_common.py`; every function and constant AST-identical to before) | merge conflicts with other branches (`hopeful-volta` has a 2,422-line dispatcher) | land `hopeful-volta` first or rebase it; move code verbatim; full suite must pass unchanged |
| 3 ✅ | Native session talk off: `disallowed_tools`, blank messaging env vars, agent teams unset, + test (A12) | none | — |
| 4 | Skills: refresh `sherlock`, choose `jai` vs `jai-insta`, adapters for `new-claude` (drop exclusive mode), `pinloop`; add read-only `skill_read` tool scoped to the route's skill folders | refreshed skills break existing adapters | diff each SKILL.md against `skills.yaml` adapters before swapping; `validate_config.py` |
| 5 | Models: Haiku 4.5 → Haiku 5.5 everywhere (`org.yaml`, `HIRE_DEFAULTS`, demo JSON); writers/engineers to Sonnet 5.5 per §4 | Haiku 5.5 thinking rules differ from 4.5 (no `budget_tokens`) | SDK sets thinking; run `scripts/live_check.py` on 3 scenarios first |
| 6 | `effort` per route + attempt ladder with `fallback_model` + Opus advisor on hard routes | higher tier on retry raises spend; advisor may bill to usage credits | ladder only on machine-check failure; task caps unchanged; advisor only after the step-7 billing check |
| 7 | **First live run** of `SDKRunner` (never done) | auth/SDK surprises | do it before steps 8–10 so new features don't mask base failures |
| 8 | Resumed lead sessions (`resume`/`session_id`) | context grows across phases | per-task budget still enforced in `_run`; close session at DELIVERED/CANCELLED |
| 9 | `peer_ask` tool with policy rules §3c + Live Office note events | sessions chatting in loops; cross-show leak | ≤ 3 asks per pair per task; same task + same show/lane only; tests per isolation rule I1–I7 |
| 10 | `llm.free` tool (Groq, Gemini) with §3b guard | provider trains on prompts; free tier disappears | refused for private-data holders; PII check; T1 fallback; keys in `.env` only |
| 11 | Caveman blocks for internal text; `caveman-compress` the constitution + context files (owner reviews) | compressed rule changes meaning | owner reviews diff; Auto-Clarity rules keep security/irreversible text in full |
| 12 | Track → Scan merge; `topic_pitch` route | the merged 09:00 run now also writes the pipeline | same private-data tools as today; tests for both old routes |

Owner answers (2026-10-17): (1) session talk and the model picker are the new Claude Code 2.1.299 features — covered in §3b and §3c; (2) the Sherlock carousel stays separate from the workforce; (3) yes to sending public-web text to Groq/Gemini free tiers.
