# What you need to give each employee

Every employee has one training file: `context/<employee_id>.md`. That file goes **only** into that employee's own sessions. Nobody else reads it. Each file has these sections:

| Section | What it holds | Who writes it |
|---|---|---|
| Role · Serves · Inputs · Outputs | What the employee is for and who it works with | Already written; edit if wrong |
| **Fire when** | The exact trigger (for example "only when your message says *jai reel*"). The Dispatcher enforces it | Already written |
| **Skills** | Each task type, when to use it, which skills load, which checks must pass, and whose output it must start from | Written from `config/skills.yaml`. The validator fails if a route is missing |
| **Never** | Hard limits. Most are enforced in code | Already written |
| **Owner must provide** | Your to-do list for that employee. If an item is still missing when a task needs it, the employee stops and asks | **You tick these** |
| **Owner facts** | Facts you state as true: rates, results, dates, your background. The employee can cite them as `context:<id>`, and Proof accepts them | **You write these** |

There are three other places your input goes:

- **Show bibles** (`shows/<show>/brand/CHARACTER.md` and `DESIGN.md`). They are loaded only into that show's own writer, designer and producer.
  - All four are still placeholders.
  - A placeholder counts as missing, so show work stops and asks instead of inventing a voice or a look.
- **Standing rules.** Say "from now on …" in a channel and approve the card.
  - A rule given on a show task is stored for that show only.
  - Otherwise it applies to the whole department, or to everyone if you said it in #hq.
- **Secrets never go in these files.** Tokens and keys go into the server's environment settings.

---

## Do these first (they block whole teams)

| # | Give this | Unblocks | Where |
|---|---|---|---|
| 1 | Your offer: services, rate card, payment terms, results you can prove | Hook, Pitch, Ledger (invoices), Proof | `context/sales_lead.md` → Owner facts. Copy the rates into `sales_outreach_writer.md` and `sales_proposal_writer.md` |
| 2 | Master CV, portfolio links, work authorisation, notice period, salary rule | Apply (job applications) | `context/sales_application_writer.md` → Owner facts. Paste your CV into the request until the upload store exists |
| 3 | Jai bible: how you talk, topics, words you never use, colours, fonts, caption style | Jai, Jai-Writer, Jai-Design | `shows/jai/brand/CHARACTER.md` + `DESIGN.md` |
| 4 | Your voice reference recording + signed consent | Jai's voiceover (OpenVoice clone) | `shows/jai/voice/reference/` (see `RECORD.md`) |
| 5 | Sherlock, Peter and Striker bibles | Each show's writer, designer and producer | `shows/sherlock|brainrot|striker/brand/` |
| 6 | Targeting: roles you want, clients you pitch, regions, exclusions | Scout, Intel | `context/sales_scout.md` |
| 7 | Trusted sources per topic (AI, football, companies) | Proof, Intel | `context/fact_checker.md` |

---

## Team by team

### Core (you talk to Atlas in #hq; the others run on their own)
| Employee | Fires when | Skills | Give it |
|---|---|---|---|
| **Atlas** · Chief of Staff | You post in #hq or DM; a Lead asks another department | to-questionnaire (contract phase) | Weekly priorities (optional) |
| **Vera** · Verifier | M and L tasks; S tasks with a `verifier` criterion or an external action | — | Your "good enough" bar per work type. It keeps no memory, so this file is where the bar lives |
| **Proof** · Fact checker | Any text with numbers, dates, prices or citations; every M/L task; every Sales task. Runs **before** Vera | — | Trusted sources per topic |
| **Lex** · Librarian | When you accept work (G4), approve a standing rule, and weekly | — (plain code) | Nothing |

### Studio (#studio, lead **Maya**)
| Employee | Fires when | Skills | Give it |
|---|---|---|---|
| **Maya** · lead | You post in #studio | to-questionnaire, handoff | Video specs per channel (aspect, length), posting cadence, faceless channel name |
| **Reel** · faceless videos (no show) | Message names **no** show; works from Script's script | ui-ux-pro-max → hyperframes → product-launch / faceless-explainer / music-to-video / general-video | Channel niche, 3 reference videos, music library |
| **Pixel** · visuals (no show) | Message names no show | ui-ux-pro-max | Personal brand kit |
| **Jai** · producer | "jai reel / jai video / show: jai"; works only from Jai-Writer's script | jai (+ hyperframes set, media-use) | Jai bible, voice + consent, your on-camera clips per reel |
| **Jai-Design** | Same trigger | ui-ux-pro-max | Jai DESIGN.md, 3 thumbnails you like |
| **Sherlock** · producer (AI topics only) | "sherlock reel …"; only from Sherlock-Writer's script | sherlock | Sherlock bible, which base voice |
| **Sherlock-Design** | Same | ui-ux-pro-max | Sherlock DESIGN.md |
| **Peter** · producer (captions, no voice) | "peter reel / peter story / show: peter". A person called Peter doesn't count | peter | Brainrot bible, licensed gameplay footage |
| **Peter-Design** | Same | ui-ux-pro-max | Brainrot DESIGN.md |
| **Striker** · producer | "football video / football reel / striker reel" | football-video | Striker bible, player assets you have rights to |
| **Striker-Design** | Same | ui-ux-pro-max | Striker DESIGN.md |

### Sales (#sales, lead **Sam**): all research and all writing
| Employee | Fires when | Skills | Give it |
|---|---|---|---|
| **Sam** · lead | You post in #sales; Studio asks for a script | to-questionnaire, handoff | Rate card, who you pitch, roles you want, what you never promise |
| **Scout** | `find_opportunities` | research | Targeting rules, job boards, exclusions |
| **Intel** · researcher (the only helper allowed on shows) | T1 of every research → writing chain | research | Preferred sources, brief length |
| **Hook** · pitches, emails, DMs | Only after Intel/Scout (`pitch_email`, `dm`); `follow_up` on a thread you paste | humanizer | 2–3 emails that got replies, signature, provable results |
| **Apply** · job applications | Only after Intel's `job_brief` | humanizer | Master CV, portfolio, work authorisation, salary rule |
| **Pitch** · proposals and decks | Only after Intel | ui-ux-pro-max → slides → humanizer | Case studies, rate card, a proposal you liked |
| **Script** · scripts and captions (no show) | Message names no show | humanizer | Faceless channel tone + 2 sample scripts |
| **Jai-Writer / Sherlock-Writer / Peter-Writer / Striker-Writer** | Only their own show; after Intel | humanizer + that show's bible | Each show's CHARACTER.md + 5 scripts you like |

### Talent (#talent, lead **Rhea**)
| Employee | Fires when | Skills | Give it |
|---|---|---|---|
| **Rhea** · lead | You post in #talent. It never auto-starts, even via Atlas | to-questionnaire, handoff | Your rule for when to hire and when to train an existing employee |
| **Architect** | `design_employee` after your G1 | writing-for-agents, write-a-skill | Nothing. Its spec is checked by `employee_spec`. When you accept it, it is filed to `proposals/` and never goes live by itself |

### Engineering (#engineering, lead **Forge**)
| Employee | Fires when | Skills | Give it |
|---|---|---|---|
| **Forge** · lead | You post in #engineering | to-questionnaire, handoff | Repos in scope, stack, definition of done |
| **Byte** · code + planning docs | 11 task types (implement, fix_bug, write_spec, tickets …) | implement/tdd, diagnosing-bugs, to-spec, to-tickets, wayfinder, … | Repo access (GitHub connector), test commands |
| **Loom** · frontend | `build_ui`, `deploy_preview` | ui-ux-pro-max → ui-styling → components → vercel-react-best-practices; deploy-to-vercel | Vercel project, portfolio content |
| **Audit** · QA | review, triage, web/SEO/speed audits | best-practices, triage, web-quality-audit, seo, core-web-vitals | URLs, minimum scores |
| **Gear** · automations | `make_automation`, `human_setup_steps` | make-scenario-building, wizard | Make account + the automations you want |

### Ops (#ops, lead **Otto**)
| Employee | Fires when | Skills | Give it |
|---|---|---|---|
| **Otto** · lead | You post in #ops | to-questionnaire, handoff | Currency, tax year, accounts, report cadence |
| **Ledger** · bookkeeping, invoices | `bookkeeping`, `invoice` | none yet (add xlsx/docx/pdf on the server — they are Anthropic-licensed, so not committed) | Statements as CSV, categories, invoice details (legal name, tax ID, bank, terms) |
| **Gauge** · dashboards, reports | `dashboard`, `weekly_report` | none yet (xlsx) | The metrics you want + the export files |

---

## What doesn't work yet (you'll be asked, never guessed)
- **No upload store** for your CV or statements (`owner_profile.read`, `finance.read_uploads`). Until it exists, paste them into the request.
- **No Modal render or voice service yet.** Video and code tasks can't pass their render and test checks.
- **No connectors for email, GitHub, Make or Vercel.** Approved sends and deploys say "no connector configured" and nothing is sent.
