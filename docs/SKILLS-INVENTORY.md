# Skills inventory (2026-10-16)

Where skills live on the owner's Mac, what each does, and which employee should use it. Employees only ever see the skills in this repo's `.claude/skills/` (the Dispatcher pastes a route's `SKILL.md` into the session prompt; `setting_sources=[]` hides everything else).

Legend: **in repo** = already in `.claude/skills/` · **copied** = copied in on this branch (parked under `unassigned.v3_pending` in `config/skills.yaml` until v3 is approved) · **owner** = stays on the owner's machine, no employee needs it.

## 1. The five skills asked about

| Skill | Found? | What it does | Employees | Status |
|---|---|---|---|---|
| `/new-claude` | `~/.claude/skills/new-claude` (7.8 MB, 906 files) | ECC toolkit (MIT): 311 skill guides, 71 agent prompts, 97 commands, language rules. Its `commands/model-route.md` is a 3-tier model router (haiku = mechanical, sonnet = default, opus = architecture/ambiguous; always name a fallback). "Exclusive mode" forbids other skills while active | Forge, Byte, Byte-Co, Loom, Audit (code review, TDD, security review, build-fix agents); the Dispatcher's model ladder borrows `model-route` | **copied**. Needs an adapter: drop "exclusive mode" (routing already loads one route's skills only) and add a `skill_read` tool so the session can open `references/…` |
| `/free-llm-apis` | `~/.claude/skills/free-llm-apis` (CC0, snapshot `cf97c32`, 2026-10-11) | Catalogue of permanent free tiers: Gemini Flash (1,500 RPD, prompts may train Google models), Groq `openai/gpt-oss-120b` (30 RPM, 1,000 RPD), Mistral free mode ($10/mo credit, trains unless opted out), Cloudflare Workers AI, OpenRouter/Kilo `:free` models, Cohere (non-commercial) | Dispatcher (new `llm.free` tool); Scout, Burrow, Intel pre-filters; Peter-Writer drafts | **copied** |
| `/caveman:caveman` | caveman plugin 2.7.0 (`skills/` is MIT) | Terse output mode, keeps technical content. Measured: −8.5 % output tokens on 86 real coding tasks (JetBrains, quality flat); −50 % median output on short Q&A; −33 % input with its wrap layer | Every employee for **internal** text (handoff `context_summary`, return notes, plans); never for owner-facing or outbound copy | **copied** (`caveman` + `caveman-compress` with its `scripts/`) |
| Session-talk skill | **Not installed.** No SKILL.md on disk, in plugins, or in claude.ai skills matches. Session-to-session messaging is a built-in Claude Code feature (`SendMessage` / `ListAgents` cross-session, `start_session`), not a skill | Design in ORG-V3 §3 uses the Agent SDK's `resume`/`session_id` instead, with the Dispatcher as the only message bus | nothing to copy — **owner: tell me the skill name if you installed one** |
| Model-picker skill | **Not installed** as its own skill. Closest: ECC `commands/model-route.md` + `skills/cost-aware-llm-pipeline` (inside new-claude) and `maps-skill` (picks a *skill*, not a model) | Dispatcher model ladder (ORG-V3 §4) | covered by new-claude copy — **owner: tell me the name if it is a different skill** |

## 2. Other new skills since org v2 (2026-10-01)

| Skill | Where | What | Employee | Status |
|---|---|---|---|---|
| `pinloop` | ~/.claude/skills | Job-posting search CLI (counts first, then pull) | Scout (`find_opportunities`) | **copied**; needs a `pinloop` command in the runtime allowlist + owner's Pinloop account |
| `sherlock-ideas` | ~/.claude/skills | 5 AI-topic pitches in 3 proven reel formats, with sources | Sherlock-Writer (new route `topic_pitch`) | **copied** |
| `sherlock-carasoul` | ~/.claude/skills | Daily "AI Case File" carousel; posts after owner's yes | Sherlock-Design (new route `daily_carousel`) + new routine | **copied**; adapter must strip the Instagram publish step (owner posts, as today) |
| `jai-insta` | ~/.claude/skills | Newer Jai reel pipeline (2026-10-03) | Jai producer / Jai-Writer | **copied** next to the older project `jai`; pick one in migration step 4 |
| `sherlock` (updated 2026-10-13) | ~/.claude/skills | Newer than the project copy (SKILL.md + PROCESS.md differ) | Sherlock | **not overwritten** — adapters in `skills.yaml` reference its steps; refresh in migration step 4 |
| `final-skill` | ~/.claude/skills | Conducts brainstorming → ui-ux-pro-max → humanizer → components → artsy → motion-director | Pixel, show designers (later) | owner — calls superpowers:brainstorming, which needs a live human |
| `motion-director`, `artsy-components`, `design-motion-principles`, `genjutsu`, `gsap-*`, `threejs-*` | ~/.claude/skills | Motion/3D/texture craft | Reel, show producers (later) | owner — add per route when a show bible asks for it |
| `end-code` | ~/.claude/skills | Review → fix → verify → delete dead code loop | Byte, Loom | owner (new-claude covers it) |
| `popeye` | ~/.claude/skills | Older football pipeline (2026-09-25) | — | owner; `football-video` (09-26) stays Striker's skill |
| `maps-skill` | ~/.claude/skills | Matches a task to installed skills | — | owner; routing is deterministic by design |
| `opendots`, `text-to-cad`, `superdesign`, `remotion-best-practices`, `linkedin-marketing`, `hallmark`, `grilling`, `excalidraw-diagram`, `banner-design`, `brand`, `design*` | ~/.claude/skills | Various | — | owner |

## 3. Project skills already in `.claude/skills/` (57)

| Group | Skills | Employees |
|---|---|---|
| Engine | `agent-harness` (loop_controller.py) | Dispatcher only |
| Video | `hyperframes*` (9), `media-use`, `faceless-explainer`, `general-video`, `music-to-video`, `product-launch-video`, `jai`, `sherlock`, `peter`, `football-video` | Reel, show producers |
| Design | `ui-ux-pro-max`, `ui-styling`, `components`, `slides` | Pixel, show designers, Pitch, Loom |
| Writing | `humanizer`, `writing-for-agents`, `write-a-skill` | Writers, Architect |
| Research | `research` | Intel, Scout, Burrow, Proof |
| Planning | `to-questionnaire`, `handoff`, `to-spec`, `to-tickets`, `wayfinder`, `triage`, `prototype`, `domain-modeling`, `code-to-prd`, `improve-codebase-architecture`, `agile-product-owner`, `setup-matt-pocock-skills` | Leads, Forge |
| Code | `implement`, `tdd`, `diagnosing-bugs`, `codebase-design`, `strict-api`, `resolving-merge-conflicts`, `setup-pre-commit`, `git-guardrails-claude-code`, `migrate-to-shoehorn` | Byte, Byte-Co |
| Web | `best-practices`, `web-quality-audit`, `seo`, `core-web-vitals`, `vercel-*` (2), `deploy-to-vercel` | Loom, Audit |
| Automation | `make-scenario-building`, `wizard` | Gear |

Overlap to resolve in v3: ECC (new-claude) duplicates `tdd`, `implement`, `diagnosing-bugs`, `best-practices`. Keep the small Matt Pocock skills as the routed default; use ECC agent prompts (`code-reviewer`, `security-reviewer`, `<lang>-build-resolver`) where nothing smaller exists.

## 4. Plugin and claude.ai skills (owner tools, not for employees)

| Source | Skills | Note |
|---|---|---|
| superpowers 6.4.1 | brainstorming, writing-plans, TDD, debugging, subagent-driven-development, … | Need a live human; owner sessions only |
| caveman 2.7.0 | caveman, cavecrew, caveman-compress/-review/-commit/-stats, investigate-first, lean-build, migration, safe-refactor, surgical-patch, verify-and-stop | `caveman` + `caveman-compress` copied |
| ui-craft, posthog (~120), text-to-cad, claude-reflect, karpathy-guidelines | — | Not workforce work |
| Cowork plugins (sales, marketing, legal, finance, engineering, design, data, HR, ops, PM, support, search, Adobe, pdf-viewer) | ~150 | Built for company teams + connectors the workforce lacks |
| claude.ai (Anthropic) | docx, pdf, xlsx, pptx, skill-creator, deep-research, docs, … | `docx`/`pdf`/`xlsx` still planned for Apply/Letter/Ledger/Gauge (install on the server; Anthropic licence, not committed) |
