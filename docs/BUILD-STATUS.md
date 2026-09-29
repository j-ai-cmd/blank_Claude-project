# Build status — Phase 1 (core)

Run tests: `python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]' && pytest` → **140 passing** (one test per flag in `docs/FLAGS-CODE.md`, one per original request in `tests/test_requirements.py`, org v2 isolation/Proof/Talent in `tests/test_v2.py`).
Tests use a scripted agent (no Claude calls). The real agent path (`SDKRunner`) has **not** been run yet — it needs your `CLAUDE_CODE_OAUTH_TOKEN`.

## Built and tested
| Area | Where | Tested |
|---|---|---|
| Config loader (6 design files) + validator at boot | `workforce/config.py`, `scripts/validate_config.py` | ✅ |
| Permission engine: allowlists, tiers, R4 + 3-strike auto-pause, restricted kinds, private-data vs web split, URL exfiltration guards, verifier fetch-log rule, bulk limits per task **and** per day, spend caps + 150% runaway pause, kill switches, hash-bound single-use approvals | `workforce/policy.py` | ✅ |
| Task state machine with hard transitions (no delivery without verification, no work without G1, only humans accept) | `workforce/states.py` | ✅ |
| Deterministic skill routing (task_type → skills, disabled routes, brand-kit gating, modifiers) | `workforce/routing.py` | ✅ |
| Memory: row ACL per employee, candidates only, promotion rules (ticked at G4, no intentions/PII/secrets), GC with pinned rules | `workforce/memory.py` | ✅ |
| agent-harness loop (real `loop_controller.py`), plan built from handoffs, checks from `config/checks.yaml` only, retries with failure notes, escalation after 3 attempts | `workforce/harness.py`, `workforce/dispatcher.py` | ✅ end-to-end |
| Deterministic checks: packet schema, criteria coverage, PII, AI tells, spelling, length limits, JSON, citations, links, image spec | `workforce/checks.py` | ✅ (links need network) |
| Dispatcher flow: Slack → contract with assignee + task_type per deliverable (G1, S auto-start) → plan must match contract, cover all criteria, fit size → harness passes each specialist's real output to the next → LLM Verifier (§7 + numbers/claims + verifier criteria) → revisions (≤2, archived rounds) → delivery from real summaries (G4 with grades + memory ticks) → G3 (R3 double-confirm); steering stops running loops; cross-dept via Chief of Staff with resume; standing rules; sweep for reminders/parking/restarts | `workforce/dispatcher.py` | ✅ incl. cross-dept |
| Monthly plan-credit guard ($20): pauses everything at 100% | `workforce/dispatcher.py` | ✅ |
| Slack: signature check, bot/edit filtering, owner-only requests, dedupe, persona posts, approval buttons, `/wf` commands | `workforce/slack.py`, `workforce/app.py` | ✅ |
| Claude Agent SDK runner on your plan: all built-in tools off except gated WebSearch/WebFetch, only Dispatcher tools, settings/skills dirs ignored, API key stripped | `workforce/agents.py` | ⚠ written against SDK 0.2.161 docs, **not yet run live** |
| Docker image, compose (API + Postgres), Slack manifest, AWS runbook | `Dockerfile`, `docker-compose.yml`, `deploy/` | ⚠ package install + server boot verified; Docker build not run (no Docker daemon here) |
| **Org v2**: 36 employees, 5 departments. Show isolation (one show per task, memory/voice/bible per show, per-show capacity). Proof fact checker before Vera. Talent proposals (never live). `upstream_from` research → writing → production chains. `context/<id>.md` training per employee | `config/*.yaml`, `context/`, `workforce/*` | ✅ |
| Live Office API for the animated frontend: presence per employee, note handoffs, SSE stream with replay, prompt-a-desk (Atlas + Leads), approvals/replies/commands over HTTP, CORS. Spec + Stitch prompt: `docs/STITCH-HANDOFF.md` | `workforce/live.py`, `workforce/app.py` | ✅ |
| Live Office frontend: 3D office (Three.js), sleeping/working/walking employees, note handoffs, approvals, prompt-a-desk, demo mode + live backend connection | `frontend/` | ⚠ typecheck + build + headless screenshots of the demo; not yet run against a live backend |

## Not built yet / needs you
- **Deploy**: AWS server, Slack tokens, Modal runtime (`modal deploy deploy/modal_app.py`), Vercel for the Live Office — steps in `deploy/AWS-FREE-PLAN.md`.
- **Voices** run only on the Modal runtime (Chatterbox/Kokoro can't be downloaded in the build sandbox); locally an espeak stand-in proves the pipeline.
- **Connectors** you add as you go: email (IMAP read + SMTP send are built in, need your app password), GitHub push, Vercel deploy, Make — `workforce/connectors.py` `register()`.
- **Your material**: rabbit-hole taste (Burrow), strengths/weaknesses/CV (Letter, Apply), show assets per reel.
