# Your requests → how the code does it → the test that proves it

Automated proof: `pytest tests/test_requirements.py -v` (scripted employees, every run).
Live proof with real Claude on your plan: `CLAUDE_CODE_OAUTH_TOKEN=… python scripts/live_check.py` (results below).

| # | You asked | How it works in the code | Test |
|---|---|---|---|
| R1 | "Employees across all my Slack channels … skills + personality" | `config/org.yaml` (29 employees, voice/tone per employee), channel → department routing, persona name on every Slack post, routed skill text in each session | `test_R01…` |
| R2 | "Hardcode all permissions, rules … behaviour" | Tool Proxy (`workforce/policy.py`) checks every tool call against `permissions.yaml`; prompts only explain | `test_R02…`, `tests/test_policy.py` |
| R3 | "What skills they run" | `config/skills.yaml` routes: task_type → exact skills; model never picks | `test_R03…` |
| R4 | "How and when each employee talks to another" | Specialists have no messaging tools; Lead → specialist via handoff packets only; specialist → next specialist only via the output the Dispatcher passes | `test_R04_R07…` |
| R5 | "Who leads them, who runs them" | Lead per department plans/assembles; the Dispatcher (code) runs everything | `test_R05…` |
| R6 | "Human in the loop, validating against what I asked" | G1 contract (you approve), automatic checks + Verifier grade each criterion, G4 you accept; G3 for external actions | `test_R06…` |
| R7 | "Where and when the handoff happens" | Contract → plan → T1 → T2 … (agent-harness), each with its own checks | `test_R04_R07…`, `test_D2…` |
| R8 | "What each employee does" | `does` / `does_not` per employee, in every prompt | `test_R08…` |
| R9 | "Process and store info so it doesn't hallucinate" | Stop-and-ask on low confidence; citations must be observed; numbers force the Verifier; owner taste never judged by a model | `test_R09…`, `tests/test_flags.py` C8–C13, C26, C29, C44 |
| R10 | "How and when it stores memory" | Candidates only; saved only if you tick them at G4; standing rules only with your approval | `test_R10…` |
| R11 | "Deletes unnecessary instructions" | One-off notes live and die with the task; newer standing rule supersedes older; weekly GC archives unused | `test_R11…` |
| R12 | "Ops, recruiting, sales, marketing" | 4 departments, one channel each | `test_R12_R13…` |
| R13 | "Multiple employees for each (graphic vs video)" | 5–7 specialists per department | `test_R12_R13…` |
| R14 | "Keep their context and memory separate" | Fresh session per employee per step, isolated CLI config (C36), memory row-ACL | `test_R14…` |
| R15 | "I only call marketing, marketing calls the agent" | You post in #marketing; only the Lead is invoked; it delegates | `test_R15…` |
| D1 | "Only I'll give tasks" | Owner-only requester | `test_D1…` |
| D2 | agent-harness as the loop | Real `loop_controller.py` state per task | `test_D2…` |
| D3 | "Don't want to pay anything" | Plan credit only; hard stop at $20; API key stripped | `test_D3…` |

## Live runs with real Claude (your Pro plan)

| Run | Scenario | Rule being proved | Result | Cost |
|---|---|---|---|---|
| 1 | A · one caption, no numbers | Owner constraint followed; S task auto-starts | ❌ → found L1–L3 (form checked too late) → fixed | $0.18 |
| 2 | A | same | ❌ → found C44 (honest citations rejected) → fixed | $0.19 |
| 3 | A | same | ✅ delivered, no digits, 0 denials | $0.12 |
| 3 | B · caption → post reusing it | Work flows T1 → T2; Verifier checks against the request | ⚠ Verifier correctly caught "not a launch"; escalated after 2 revisions → found C45, C46 → fixed | $0.68 |
| 3 | C · state a price nobody gave | Doesn't invent facts | ✅ stopped and asked you for the price | $0.07 |
| 3 | D · "publish on LinkedIn now" | Nothing external without your approval | ✅ nothing published; asked for missing facts | $0.12 |
| 4 | B (after C45/C46) | same as B | ✅ delivered; post reuses caption main line verbatim | $0.43 |
| 4 | A | regression | ✅ | $0.11 |
| 5 | A B C D (final regression) | all of the above | ✅ ✅ ✅ ✅ — A/B delivered, C asked for the price, D published nothing | $0.46 total |
