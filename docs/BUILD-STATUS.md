# Build status — Phase 1 (core)

Run tests: `python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]' && pytest` → **34 passing**.
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
| Dispatcher flow: Slack → contract (G1, S auto-start) → plan → harness → LLM Verifier (§7 rule) → revisions (≤2) → delivery (G4 with memory ticks) → G3 approvals for R2/R3; owner steering → new contract version; cross-dept sub-tasks via Chief of Staff | `workforce/dispatcher.py` | ✅ (cross-dept path not yet covered by a test) |
| Monthly plan-credit guard ($20): pauses everything at 100% | `workforce/dispatcher.py` | ✅ |
| Slack: signature check, bot/edit filtering, owner-only requests, dedupe, persona posts, approval buttons, `/wf` commands | `workforce/slack.py`, `workforce/app.py` | ✅ |
| Claude Agent SDK runner on your plan: all built-in tools off except gated WebSearch/WebFetch, only Dispatcher tools, settings/skills dirs ignored, API key stripped | `workforce/agents.py` | ⚠ written against SDK 0.2.161 docs, **not yet run live** |
| Docker image, compose (API + Postgres), Slack manifest, AWS runbook | `Dockerfile`, `docker-compose.yml`, `deploy/` | ⚠ package install + server boot verified; Docker build not run (no Docker daemon here) |

## Not built yet (next phases)
- **Connectors**: CRM, recruiting system, email, calendar, social, project management. Every `act` call answers "no connector configured" and approved G3 actions send nothing. Needs your tool list.
- **Modal**: OpenVoice voice service (`voice.synthesize`), HyperFrames render sandbox (`sandbox.exec`), `ffprobe` / `hyperframes check`. Video tasks will fail their checks until this exists.
- **Scheduled routines** (daily digest, weekly reports, stalled-task sweep, weekly memory GC — GC runs manually via `/wf gc` for now).
- **Durable job queue**: work runs as in-process background tasks; a server restart mid-task leaves it where it stopped (state is saved, not resumed automatically).
- **Away mode / backup approver**, reminders at 4h/24h, auto-park at 72h.
- **Brand-colour check** (waits for the brand kit), Lighthouse web audits.
- Frontend (Vercel).
