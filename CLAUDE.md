# AI workforce — repo guide for Claude sessions

A personal AI workforce in Slack. 41 employees in 5 departments plus a core (Atlas, Vera, Proof, Lex). The **Dispatcher** (Python code) runs everything: every employee is one Claude Agent SDK session per task step, and every tool call goes through the Dispatcher's policy check.

Read first: `docs/BUILD-STATUS.md` (what is built and tested), `docs/ORG-V3-PROPOSAL.md` (the next design and its migration steps), `docs/DESIGN-MAP.md` (the original design and its reasons).

## Layout

| Path | What |
|---|---|
| `workforce/dispatcher.py` | The Dispatcher: message intake, task flow, `_run`, `_guard`, budget. Mixins in `contracts.py`, `toolbox.py`, `verification.py`, `delivery.py`, `routines.py` |
| `workforce/agents.py` | `SDKRunner` (real Claude sessions) and `FakeRunner` (scripted, used by tests) |
| `workforce/policy.py`, `states.py`, `memory.py`, `routing.py`, `harness.py`, `checks.py` | Permissions, task state machine, memory ACL, skill routing, agent-harness loop, machine checks |
| `workforce/live.py`, `app.py`, `slack.py` | Live Office event stream, FastAPI app, Slack client |
| `config/*.yaml`, `config/constitution.md` | The rules. Owner-edited. `scripts/validate_config.py` checks them at boot |
| `context/<id>.md` | One training file per employee |
| `.claude/skills/` | Skills employees may load. Every folder must be assigned in `config/skills.yaml` or listed under `unassigned` |
| `deploy/` | Runtime service (`runtime_server.py`, or `modal_app.py` on Modal), Slack manifest |
| `frontend/` | Live Office (Vite + Three.js) |

## Commands

```bash
uv venv -p 3.12 .venv && uv pip install -p .venv -e '.[dev]'
.venv/bin/pytest -q
.venv/bin/python scripts/validate_config.py
```

Python 3.11 or newer. Tests use `FakeRunner` and never call Claude.

## Rules

- The Dispatcher stays in charge of approvals (G1–G4), checks, budgets and memory ACLs. Never add a path where one employee's session reaches another, the web, memory or an external action without a Dispatcher tool that calls `Policy.check`.
- The one employee-to-employee path is `peer_ask`: a Dispatcher tool, policy-checked, finished upstream steps of the same task only, capped per pair (`tests/test_v3_peer_ask.py`).
- Native Claude Code multi-agent features (`SendMessage`, `ListAgents`, `Agent`, agent teams) stay off in employee sessions. `SDKRunner` enforces this; `tests/test_session_isolation.py` checks it.
- Change behaviour only with a test. A design rule in `docs/FLAGS-CODE.md` has a matching test in `tests/test_flags.py`.
- Model IDs, the retry ladder, effort and the advisor switch live in `config/org.yaml` (`models:`). Do not hard-code model names in code; `HIRE_DEFAULTS` in `workforce/config.py` is the one default (new hires start on Haiku 5.5).
- Skills reach a session as the route's SKILL.md text plus `skill_read` for that skill's other files. A new skill folder must be assigned or parked in `config/skills.yaml`.
- Docs, commit messages and owner-facing text are normal prose.
