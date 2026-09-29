# Org v2 — APPLIED (see docs/TRAINING-CHECKLIST.md for what each employee needs from you)

> Applied with your answers: each show has its own writer + designer; Reel/Pixel/Script = work that belongs to no show; Jai is the only on-camera channel; writers write captions. Changes vs this proposal: Engineering planning docs run on Byte (a Lead never executes); find-skills stays forbidden (it installs skills itself); xlsx/docx/pdf are Anthropic-licensed, so install them on the server rather than committing them.

Your real work: **pitching clients**, **job applications**, **pitching companies for roles**, **videos** (faceless channels + your personal channel). You don't run a company, so employees built for company operations (hiring humans, CRM hygiene, vendors, SOPs) don't earn their place.

Rule used to judge every employee: *does it do a job you actually have, that no other employee does, and does its separate context/memory help it do that job better?* If not → remove or merge.

---

## 1. Verdict on all 29 current employees

| Dept (now) | Employee | Does today | Fired when | Verdict | Why |
|---|---|---|---|---|---|
| Core | **Atlas** (Chief of Staff) | Routes requests that span departments, daily digest | You post in #hq / DM, or a Lead needs another dept | **Keep** | Studio needs scripts from Sales; that hop goes through Atlas |
| Core | **Vera** (Verifier) | Grades work against your brief, criterion by criterion | After automatic checks on M/L tasks, numbers, or "verifier" criteria | **Keep** | "Did it do what I asked?" |
| Core | **Lex** (Librarian) | Saves/archives memory (code, no model) | When you accept work / weekly cleanup | **Keep** | Memory hygiene |
| Marketing | **Maya** (lead) | Plans marketing work | You post in #marketing | **Keep → Studio lead** | Your main work is video |
| Marketing | **Pixel** (graphic design) | Visuals via ui-ux-pro-max | Lead assigns `visual_design` / `diagram` | **Keep** | Thumbnails, carousels, covers, pitch visuals |
| Marketing | **Reel** (video editor) | Company videos via HyperFrames | `launch_promo_video`, `explainer_video`, `music_video`, `other_video` | **Keep → faceless explainer videos + client promo videos** | Faceless channel + client work |
| Marketing | **Frame** (personal reels) | jai + sherlock + peter + football in ONE context | `jai_reel`, `sherlock_reel`, … | **Split into 4 employees** | You asked; 4 shows sharing one memory = style bleed |
| Marketing | **Quill** (copywriter) | Captions, copy | `general_copy` | **Remove** | You want Sales to write all copy |
| Marketing | **Sage** (SEO / blog) | Keywords, blog, site audits | `seo_brief`, `blog_post`, `site_audit` | **Remove** (web audits → Engineering QA) | No blog/site work |
| Marketing | **Echo** (social) | Content calendar, posting | `linkedin_post`, `other_platform_post` | **Remove for now** | You post yourself; no social connector yet. Re-add when you want auto-posting |
| Marketing | **Metric** (analytics) | Campaign numbers | never (no skill) | **Remove → Ops reporting** | Dashboards live in Ops |
| Sales | **Sam** (lead) | Plans sales work | You post in #sales | **Keep** | Owns research → writing |
| Sales | **Scout** (prospector) | Lead lists, contact lookups | never (no skill) | **Keep, repurposed** → finds job posts, clients, companies to pitch | Top of your pipeline |
| Sales | **Intel** (researcher) | Account/competitor briefs | `account_brief`, `competitor_brief` | **Keep** → researches clients, companies, job posts, **video topics** | Research step you asked for |
| Sales | **Hook** (outreach writer) | Cold emails (drafts) | `outreach_draft` | **Keep** → emails, DMs, client pitches, follow-ups | Writing step |
| Sales | **Ledger** (CRM upkeep) | CRM notes/cleanup | never (no skill, no CRM) | **Remove** (tracking → Ops) | No CRM |
| Sales | **Pitch** (proposals) | Proposals, decks | `proposal_deck`, `proposal_doc` | **Keep** → client proposals, pitch decks, portfolio one-pagers | Pitching |
| Recruiting | **Rhea** (lead) | Hiring plans | You post in #recruiting | **Keep → Talent lead** (designs *AI* employees) | Your new idea |
| Recruiting | **Scribe, Radar, Lens, Slot, Herald** | Job descriptions, sourcing, screening, scheduling, candidate messages for **human** hiring | hiring tasks | **Remove all 5** | You don't hire people |
| Ops | **Otto** (lead) | Internal processes | You post in #ops | **Keep** → finance, accounting, dashboards, reporting | As you asked |
| Ops | **Gauge** (reporting) | KPI pulls | never (no skill) | **Keep** → dashboards + weekly reports (your pipeline, channel stats, money) | Reporting |
| Ops | **Tempo** (project manager) | Tickets, specs, sprints | `plan_with_open_decisions`, `write_spec`, `break_into_tickets`, `sprint_planning` | **Remove** → planning skills move to Engineering lead | Solo, no team to manage |
| Ops | **Manual** (SOPs) | SOPs, docs | `sop_for_agents`, `sop_for_humans` | **Remove** → `writing-for-agents` moves to Talent | No staff to write SOPs for |
| Ops | **Gear** (automation) | Make automations | `make_automation`, `human_setup_steps` | **Move → Engineering** | Automation is engineering |
| Ops | **Broker** (vendors) | Vendor quotes | `vendor_comparison` | **Remove** | No vendors |

**Result: 12 removed, 1 split into 4, 3 moved/repurposed.**

---

## 2. Proposed org v2 (32 employees, 6 groups)

### Core (reports to you) — `#hq`
| Employee | What it does | Fired when | Skills |
|---|---|---|---|
| **Atlas** · Chief of Staff | Routes cross-department work (e.g. Studio needs a script from Sales), daily digest | #hq/DM request, or a Lead's `cross_dept` | to-questionnaire, handoff |
| **Vera** · Verifier | "Did it do what you asked?" — grades each criterion | After machine checks, per §7 rules | web-quality-audit (web deliverables) |
| **Proof** · **Fact Checker** (NEW) | "Is every fact true?" — extracts every factual claim (names, numbers, dates, company facts, quotes, stats), checks each against the cited source (re-fetches it) and, for web facts, against a second independent source. Output: claim-by-claim TRUE / FALSE / UNSOURCED. **Any FALSE or UNSOURCED blocks delivery.** | **Every** deliverable that contains a factual claim — runs **before** Vera; deterministic claim detector decides | research |
| **Lex** · Librarian | Memory: saves only what you tick, archives old/superseded rules | Accept (G4), standing-rule approval, weekly | — (code) |

### Studio (lead **Maya**) — `#studio` — all video + visual work
| Employee | What it does | Fired when (task_type) | Skills |
|---|---|---|---|
| **Maya** · Studio lead | Turns your request into a brief; asks Sales (via Atlas) for the script; assigns the right show | You post in #studio | to-questionnaire, handoff |
| **Reel** · Faceless video editor | Faceless explainers, listicles, client promo videos, music videos | `explainer_video`, `launch_promo_video`, `music_video`, `other_video` | ui-ux-pro-max → hyperframes → faceless-explainer / product-launch-video / music-to-video / general-video (+ hyperframes-*, media-use) |
| **Jai** · Personal-channel producer | Your @jaidhingra_ reels in your cloned voice | You say **"jai"** | jai (+ hyperframes set, media-use, ui-ux-pro-max, humanizer) |
| **Sherlock** · AI-reel producer | sherlock_teaches_ai reels — AI topics only | **Only** when you say **"sherlock"** | sherlock (+ same support) |
| **Peter** · Brainrot producer | Reddit-story reels, captions only (no voice) | You say **"peter"** | peter (+ hyperframes set) |
| **Striker** · Football producer | Football reels (ISL + Europe) | You say **"football"** | football-video (+ support) |
| **Pixel** · Designer | Thumbnails, carousels, covers, pitch visuals | `visual_design`, `diagram` | ui-ux-pro-max |

**Script rule (your request):** every video script comes from **Sales** (Intel researches → Script writes). The show pipelines (jai/sherlock/peter/football) get an adapter: *skip your own research/script step, use the supplied script*. The Script writer reads each show's `CHARACTER.md` so Jai sounds like you and Sherlock sounds like Sherlock.

### Sales (lead **Sam**) — `#sales` — all research + all writing
| Employee | What it does | Fired when | Skills |
|---|---|---|---|
| **Sam** · Sales lead | Plans every research → write chain | You post in #sales, or Atlas relays a script request | to-questionnaire, handoff |
| **Scout** · Opportunity finder | Finds job posts, companies hiring, clients worth pitching; builds a shortlist with links | `find_opportunities` | research |
| **Intel** · Researcher | Researches a client / company / job post / **video topic**; cited brief (feeds the writers + Proof) | `account_brief`, `job_brief`, `topic_research` | research |
| **Hook** · Pitch & email writer | Client pitches, cold emails, DMs, follow-ups | `pitch_email`, `follow_up`, `dm` (always `inputs_from` Intel) | humanizer |
| **Script** · Scriptwriter (NEW) | Video scripts per show voice (Jai casual, Sherlock, Peter story, football, faceless) + hooks + captions | `video_script`, `caption` (always `inputs_from` Intel) | humanizer |
| **Apply** · Job-application writer (NEW) | Tailored CV, cover letter, application answers per job; tracks what was sent | `job_application` (always `inputs_from` Intel) | humanizer + **docx, pdf** (to add) |
| **Pitch** · Proposal writer | Client proposals, pitch decks, portfolio one-pagers | `proposal_deck`, `proposal_doc` | ui-ux-pro-max → slides, humanizer |

Flow you asked for: **1 researches → hands to another who writes** = `Intel (T1) → Hook/Script/Apply/Pitch (T2, inputs_from T1)` → **Proof** checks facts → Vera checks the brief → you.

### Talent (lead **Rhea**) — `#talent` — designs new AI employees
| Employee | What it does | Fired when | Skills |
|---|---|---|---|
| **Rhea** · Talent lead | Decides whether a task needs a new employee or an existing one can be trained | You post in #talent, **or automatically when a task has no employee/route that fits** | to-questionnaire |
| **Architect** · Employee designer (NEW) | Writes the new employee's spec (role, does/doesn't, tools, permission tier, personality, skills to map or a new SKILL.md), 3 probation test tasks ("training"), and a one-page pitch: *"this is our new employee, this is the task, this is its training"* | Rhea assigns `design_employee` | write-a-skill, writing-for-agents, find-skills (search only) |

Safety: Architect **never** edits the live config (R4). Its output is a proposal → you approve (new owner gate "hire") → the validator must pass → the 3 probation tasks run → only then is the employee activated.

### Engineering (lead **Forge**, NEW dept) — `#engineering`
| Employee | What it does | Fired when | Skills |
|---|---|---|---|
| **Forge** · Eng lead | Specs, tickets, architecture decisions | You post in #engineering | to-spec, to-tickets, wayfinder, prototype, domain-modeling, code-to-prd, improve-codebase-architecture |
| **Byte** · Backend engineer | Writes/fixes code test-first | `implement`, `fix_bug` | implement, tdd, diagnosing-bugs, codebase-design, strict-api, resolving-merge-conflicts, setup-pre-commit, git-guardrails-claude-code, migrate-to-shoehorn |
| **Pixelate** · Frontend engineer | Web UI, portfolio/landing pages, deploys | `build_ui`, `deploy` | ui-styling, components, vercel-react-best-practices, vercel-composition-patterns, core-web-vitals, deploy-to-vercel |
| **Audit** · QA / code reviewer | Reviews diffs, security, web quality | `review_code`, `web_audit` | best-practices, web-quality-audit, seo, strict-api |
| **Gear** · Automation engineer (moved) | Make automations, setup wizards | `make_automation`, `human_setup_steps` | make-scenario-building, wizard |

### Ops (lead **Otto**) — `#ops` — money + numbers
| Employee | What it does | Fired when | Skills |
|---|---|---|---|
| **Otto** · Ops lead | Plans finance/reporting work | You post in #ops; Friday weekly report | to-questionnaire |
| **Ledger** · Bookkeeper (repurposed) | Income/expenses, invoices to clients, monthly summary, tax-prep notes | `bookkeeping`, `invoice` | **xlsx** (to add) |
| **Gauge** · Reporting analyst | Dashboards: pitches sent/replied, applications status, channel growth, money in/out | `dashboard`, `weekly_report` | **xlsx** (to add) |

---

## 3. How it fits the current system (what changes in code/config)
- **Engine unchanged**: Dispatcher, permissions, harness loop, memory, gates, all 46 flag fixes stay.
- **config/org.yaml**: departments become `studio, sales, talent, engineering, ops`; channels `#studio #sales #talent #engineering #ops` (+ #hq #approvals #agent-log); employees per tables above.
- **config/skills.yaml**: routes per table; 4 show employees each own one pipeline; show adapters: *"use the supplied script; skip your research/script steps"*.
- **Permissions**: Sales drops all CRM tools (no CRM); Scout/Intel get web fetch (no private data); `apply.submit` / `email.send_external` = R2 with exact preview (you click); code push/PR = R2, deploy = R2; finance files = private data (no web access for Ledger/Gauge); Architect gets no config rights (proposal only).
- **Proof (Fact Checker)**: new gate between machine checks and Vera; its verdict is mandatory whenever the claim detector fires; FALSE/UNSOURCED → revision (specialist sees the exact claims).
- **New owner gate "hire"** for Architect proposals.
- **Tests**: every test re-pointed to the new org; new tests for Proof, Script→video handoff, Architect proposal flow; live check scenarios updated (client pitch, job application, faceless video script).

## 3b. Isolation rule (your requirement): one employee's work never flows to another

**Allowed flow:** an employee's *output* can be another employee's *input* (Intel's research → Script; Script's script → Jai). **Forbidden:** an employee doing another employee's job, or reading another employee's work/memory it wasn't handed.

| # | Flag found | Today | Change |
|---|---|---|---|
| I1 | Only Sherlock is locked to its name; "jai", "peter", "football" are labels the code ignores | A Lead could give a Jai reel to Sherlock-style routes or to Reel | **Every show employee is explicit-only**: fires only when you say its name; a message naming two shows is sent back to you to pick one |
| I2 | Nothing stops two employees owning the same kind of task | Reel's `explainer_video` and Sherlock's AI reel overlap | **Each task type has exactly one owner org-wide** (validator enforces); Reel only gets faceless work that belongs to **no** named show |
| I3 | Department memory (L1) is shared by the whole department | A Jai style rule ("casual, first person") would reach Sherlock, Peter, Striker | Department memory keeps only department-wide rules; **show/style rules are stored per employee** (L3); a standing rule that names an employee is saved to that employee only |
| I4 | Shared helpers carry memory across shows (Script, Pixel, Intel, Maya) | Script's memory of Jai's voice leaks into Sherlock's scripts | Helpers' memory is **tagged per show/client** and only the matching tag is loaded for a task |
| I5 | Show assets (`shows/jai/…`, your cloned voice) are readable by any Studio employee | Sherlock could use your voice | **Each show folder and voice belongs to one employee**; `voice.synthesize` refuses any other employee's reference voice |
| I6 | Capacity is per department | Jai's task waits because Sherlock is busy | **Capacity per employee** (and a per-department cap) |
| I7 | Proof and Vera see every task | Their memory could carry one task's content into another | **Auditors keep no memory** (no candidates, no L3) |
| I8 | Every session and task workspace is already fresh and separate | ✅ already enforced (per employee per task, own CLI config, own files) | keep |

## 3c. Other flags in this proposal

| # | Flag | Change |
|---|---|---|
| P1 | **Apply** will hold your CV/contact details (private data) and also needs job-post pages | Apply gets **no web access**; Intel fetches the job post and hands it over (same split as Sales today) |
| P2 | **Engineering has nowhere to put code**: no GitHub connection, and runs happen only in the sandbox | Phase 1: code stays in task files + tests run in the sandbox; pushing to GitHub needs a connector (R2) later |
| P3 | **Ops has no money data source** (no bank/accounting connector) | You upload statements/CSVs; Ledger works from those only (private data, no web) |
| P4 | Auto-starting the Architect on every "no fit" task would spam you and burn credit | Rhea proposes; the Architect starts only after your 👍 |
| P5 | Proof re-checking every fact on the web doubles cost | Proof runs only when the deterministic claim detector fires; reuses URLs already fetched |
| P6 | A research → write → Proof → Vera chain costs ~2–4× a single step | Small tasks skip Vera when Proof passes and there are no "verifier" criteria |
| P7 | Striker's trigger word "football" is common in normal requests | Trigger = the employee's name ("striker") or an explicit "football video" |
| P8 | 32 employees but most are idle | Fine — idle employees cost nothing; cost is per task |

## 4. Recommendations
1. **Keep Vera and add Proof** (don't merge): "did it do what I asked" and "is it true" are different jobs; merging them makes both weaker.
2. **Scripts from Sales but voices from the shows**: the Script writer must read the show's CHARACTER.md, otherwise Jai/Sherlock lose their voice.
3. **Apply never auto-submits**: every application/pitch is an R2 preview you click — one bad auto-sent application costs more than the time saved.
4. **Add `docx`, `pdf`, `xlsx` skills** (available, not yet in the project) for CVs and finance.
5. **Architect probation**: new employees run 3 test tasks before going live; you see results.
6. **Echo later**: bring social posting back only when you want scheduled posting (needs an Instagram/LinkedIn connector).
7. **Budget**: 32 employees on a $20 Pro credit is fine — cost is per task, not per employee — but video + research chains are the most expensive; consider Max if you run many videos a week.
