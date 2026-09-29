# Code audit — logic, permissions, hand-offs, hallucination (Phase 1 backend)

Status column is updated as each flag is fixed and covered by a test (`tests/test_flags.py`).

| # | Area | Flag | Why it matters | Fix | Status |
|---|---|---|---|---|---|
| C1 | Permissions | `submit_*`, `workspace_*`, `memory_read` tools skipped the Tool Proxy (only `act` was checked) | "Every tool call is permission-checked" was false; kind restrictions (e.g. `submit_plan` lead-only) not enforced; no audit of those calls | One guard wraps every tool handler: policy check + audit before it runs | fixed ✅ |
| C2 | Hand-offs | A specialist could only read artifacts whose exact name the Lead guessed in advance | Work couldn't flow A → B (B never saw A's output) | Handoffs declare `inputs_from: ["T1"]`; Dispatcher grants B read access to T1's actual outputs and passes T1's summary | fixed ✅ |
| C3 | Hand-offs | All specialists wrote into one shared folder; same file name = silent overwrite | One employee could clobber another's work | Artifacts are namespaced per plan task (`T2-caption.md`); outputs must be your own | fixed ✅ |
| C4 | Hand-offs | Plan could silently drop acceptance criteria | Owner-approved requirements never assigned to anyone | Plan must cover every non-`owner_taste` criterion | fixed ✅ |
| C5 | Hand-offs | Plan size could exceed contract size (an "S" auto-started task could fan out to 5 specialists) | Bypasses G1 | Plan > size limit is rejected | fixed ✅ |
| C6 | Rules | Owner never saw which specialist/skill each deliverable goes to (task_type chosen after G1) | Skill choice not human-validated (§11 promise) | Contract deliverables carry `assignee` + `task_type`, shown on G1; plan must match them | fixed ✅ |
| C7 | Rules | `explicit_only` routes (sherlock) could be picked without you saying "sherlock" | Violates your decision | Route needs its trigger word in your message | fixed ✅ |
| C8 | Hallucination | A specialist that was blocked / low-confidence burned 3 retries and its open questions were dropped | Guessing instead of asking; wasted credit | `blocked`, `out_of_scope` or confidence < 0.6 → stop and escalate with the questions | fixed ✅ |
| C9 | Hallucination | Citations like `crm:deal/1` passed without ever being observed | Invented sources looked verified | Sources registry: only URLs actually fetched, memory ids actually read, and existing artifacts count | fixed ✅ |
| C10 | Hallucination | S tasks skipped the Verifier even when the output contained numbers / prices / dates without citations | §7 says company facts always get the Verifier | Deterministic claims detector forces the Verifier | fixed ✅ |
| C11 | Hallucination | Owner request was wrapped as `<untrusted>` | Tells the Lead to treat your instructions as data | Owner text uses a trusted `<owner_request>` tag; only external content is untrusted | fixed ✅ |
| C12 | Hallucination | Lead wrote the delivery note from file names only | Note could describe work that doesn't exist | Lead gets each specialist's summary + Verifier grades; G4 card shows grades; text artifacts posted in thread | fixed ✅ |
| C13 | Hallucination | Memory candidates flagged "untrusted" only if citations existed | Web/upstream-derived claims could be promoted unflagged | Flag set if the session fetched the web or read another employee's artifact | fixed ✅ |
| C14 | Permissions | `pending_actions` accepted any action name, even ones the employee isn't allowed | Owner asked to approve impossible/R4 actions | Validated at submit: must be in the employee's allowlist and R2/R3 | fixed ✅ |
| C15 | Permissions | G2 plan approval allowed managers/backup; you decided only you | Wrong approver | G1/G2/G4 owner-only | fixed ✅ |
| C16 | Permissions | R3 "double confirm" not implemented | Irreversible actions one click away | R3 needs Approve then Confirm | fixed ✅ |
| C17 | Permissions | Two fast clicks could both approve (race) | Double execution | Atomic claim (`UPDATE … WHERE status='pending'`) | fixed ✅ |
| C18 | Workflow | Owner steering mid-run didn't stop the running loop | Old contract kept executing | Loop checks status + contract version every step; stops if changed | fixed ✅ |
| C19 | Workflow | Revision rounds reused old files and plan-task folders | Verifier/owner saw stale output | Each round archived to `rounds/rN/` | fixed ✅ |
| C20 | Workflow | Leads had no way to ask another department (`cos.request` unwired) | Cross-dept flow missing | Plan may include `cross_dept` → sub-task via Chief of Staff; parent waits (`WAITING_ON_DEPT`), resumes with the other dept's artifacts; one level only | fixed ✅ |
| C21 | Workflow | No reminders / expiry / stall detection / restart recovery | Tasks stuck forever after a restart | `sweep()` every 15 min + at boot: reminders 4h/24h, park 72h, interrupted tasks → escalate; reply "resume" to continue | fixed ✅ |
| C22 | Budget | Monthly credit pause never lifted | Team stays off after the month rolls over | Sweep auto-resumes a budget pause in a new month | fixed ✅ |
| C23 | Memory | "always / from now on / never" instructions weren't captured | Standing rules lost; design §10.4 | Detected → "Save as standing rule?" card → L1 standing entry | fixed ✅ |
| C24 | Memory | Owner rejection feedback saved without PII/secret checks | Personal data could enter memory | Same rejection rules as candidates | fixed ✅ |
| C25 | Permissions | `workspace.write` uncounted | Unlimited file writes | Counted as `files_created` | fixed ✅ |
| C26 | Hallucination | Verifier (an LLM) could FAIL/PASS criteria that are your taste call | Model overrides the owner | `owner_taste` criteria must be graded UNVERIFIABLE; G4 lists them as "your call" | fixed ✅ |
| C27 | Permissions | `act` accepted internal actions (e.g. `workspace.write`) | Side door around dedicated, guarded tools | `act` only for business-tool actions | fixed ✅ |
| C28 | Permissions | A specialist could queue R2/R3 actions on a task whose contract declared none (incl. auto-started S tasks) | External work you never saw at G1 | Pending actions must be in the contract's approved tiers | fixed ✅ |
| C29 | Hallucination | Criteria marked `check: verifier` on S tasks were only self-assessed | Model grading its own homework | Any `verifier` criterion forces the Verifier | fixed ✅ |
| C30 | Workflow | Re-contracting a parent left its cross-dept sub-tasks running | Orphaned work + spend | Children cancelled when the parent changes direction | fixed ✅ |
| C31 | Rules | A Lead could write "sherlock" into a sub-task request to unlock an explicit-only route | Bypasses your explicit-call rule | Only the root owner's words count as triggers | fixed ✅ |
| C32 | Memory | Standing rules given in #hq/DMs were stored where no employee reads | Company-wide rules silently ignored | `L1/hq` readable by everyone | fixed ✅ |
| C33 | Permissions | No artifact size limit | Runaway writes | 2 MB text cap | fixed ✅ |
| C34 | Workflow | Stall detection assumes one process | Multiple workers would mis-flag running tasks | Image pinned to `--workers 1` | fixed ✅ |
| C35 | Hallucination | Reject button had no reason → Lead re-planned by guessing | Invented fixes | Reject without a reason pauses and asks you; your reply becomes the revision brief | fixed ✅ |

**Round 3 — found by running real Claude (live) + re-reading against your original request:**

| # | Area | Flag | Why it matters | Fix | Status |
|---|---|---|---|---|---|
| L1 | Workflow | (live) Specialist's return form was only checked after submission, by the harness — 3 attempts burned on field names | Good work escalated for formatting | Return packet validated at submit time; model fixes it in the same session | fixed ✅ |
| L2 | Workflow | (live) Model used numeric ids (`1`) vs strings (`"1"`) | Criteria "missing" though covered | Ids normalized everywhere | fixed ✅ |
| L3 | Workflow | Tool schemas said "object" with no fields | Model had to guess field names | Exact field-level schemas on every submit tool | fixed ✅ |
| C36 | Isolation | Claude CLI could load user-level skills/CLAUDE.md/memory from the server's home dir; temp dirs never cleaned | Context leaking between employees; disk fill | Fresh `CLAUDE_CONFIG_DIR` per session, deleted after | fixed ✅ |
| C37 | Workflow | Harness iteration cap fixed at 12 — any plan > ~4 handoffs escalated even when all work passed | L tasks could never finish | Cap scales with plan size | fixed ✅ |
| C38 | Budget | One run could overshoot the monthly credit | Spend past your $20 | Each run's budget = min(task left, month left) | fixed ✅ |
| C39 | Rules | Your one-off instructions/notes only reached specialists if the Lead copied them | Your words silently dropped | Dispatcher adds them verbatim to every specialist's prompt | fixed ✅ |
| C40 | Budget | "thanks!" in a department channel started a paid task | Wasted credit | Acknowledgements don't create tasks | fixed ✅ |
| C41 | Workflow | `concurrent_tasks_per_lead: 5` not enforced | Overload | Extra tasks queue and start automatically | fixed ✅ |
| C42 | Memory | New standing rule didn't replace the old one on the same topic | Conflicting rules both active | Same-topic rule is superseded (old one archived) | fixed ✅ |
| C43 | Routines | Daily/weekly digests (who runs them) didn't exist | No overview | Deterministic digest (no model, no credit), daily + Friday weekly | fixed ✅ |
| C44 | Hallucination | (live) Citing your request or the handoff counted as "unverifiable source" → good work failed 3× | Honest citations punished | `owner:request`, `contract`, `handoff:Tn` are citable; bad citations bounced at submit time | fixed ✅ |

**Known limits (not code bugs, tracked for later):**
- Spend for paid actions uses the agent's own cost estimate until real connectors report actual cost.
- Monthly budget uses the SDK's client-side cost estimate; your real plan usage may differ slightly.
- Replying in the thread of a *delivered* task doesn't reject it — use the Reject button (you'll then be asked why).
