# The office — v4 structure

**One rule:** one employee = one narrow job = one small context. Every session loads only that employee's profile, its own training file, the one route's skill text (a *slice*, never a whole pipeline), and its own memory. Anything else (other skills, reference files) it opens on demand with `skill_read`, one file at a time.

26 employees (was 41). Config: `config/org.yaml`, `config/skills.yaml`. Training: `context/<id>.md`.

## Head office (#hq)
| Employee | One job |
|---|---|
| **Atlas** `chief_of_staff` | Routes multi-department work; **hires**: when no employee owns a request, or Lex reports a bloated one, it gives Mason one `design_employee` brief. Every hire waits for your G1 click. |
| **Mason** `architect` | Writes one new employee's spec: its single job, skills mapped from the installed library, personality, tools, 3 probation tasks. Proposal only — `/wf hire` makes it live. |
| **Vera** `verifier` | Checks **every** task against your original request + the approved brief. |
| **Proof** `fact_checker` | Checks every factual claim against a source the task actually opened. |
| **Lex** `librarian` | Memory hygiene; weekly, reports any employee whose memory passes 60 entries / 12,000 chars to Atlas (thresholds: `config/memory.yaml`). |

## Studio (#studio) — 3 channels × (designer → builder) + poster
| Channel | Script | Designer (storyboard) | Builder (MP4) | Voice |
|---|---|---|---|---|
| Sherlock | Sherlock-Writer (Sales) | Sherlock-Design | Sherlock-Build | Kokoro bm_lewis (base) |
| Jai | **you** (message or `upload:show-jai/…`) | Jai-Design | Jai-Build | **you record it** |
| Football | **you** | Football-Design | Football-Build | **you record it** |

**Post** `studio_poster` packages one Instagram post (account + MP4 + caption) as a `social.publish` action you approve. Captions: Sherlock-Writer for Sherlock, Echo for Jai and football.

A reel is 2 employees (designer → builder) when you write the script, 3 for Sherlock (writer → designer → builder), plus Post if you want it posted.

## Sales (#sales)
| Employee | One job |
|---|---|
| **Echo** `sales_writer` | Writes like you: pitches, emails, DMs, follow-ups, Jai/football captions. Trained on your samples in `context/sales_writer.md`. |
| **Burrow** `sales_ideas` | Generates ideas the way you train it, each with a source. |
| **Sherlock-Writer** `show_sherlock_writer` | Researches + writes Sherlock scripts and captions. |
| **Letter** `sales_cover_letter_writer` | Cover letters from the job + your CV. No web. |
| **Scout** `sales_job_finder` | Finds jobs that fit you. |

## Engineering (#engineering) — one lane per project
| Project (lane) | Engineers |
|---|---|
| `office_app` — this office (triggers: workforce, live office, dispatcher) | **Byte** backend, **Loom** frontend |
| `company` — your employer's code (triggers: company, work) | **Byte-Co** |

A new project gets new engineers (Atlas → Mason, with a `new_lane`); no engineer works across projects.

## Ops (#ops)
**Ledger** (money, invoices, money reports) · **Scan** (9am inbox scan + pipeline update).

## How skills load
- `run: ["sherlock#build", hyperframes-core]` → only `.claude/skills/sherlock/slices/build.md` + one core skill.
- `support:` → never preloaded; `skill_read` opens one file on demand.
- `adapt:` on a route overrides a skill's adapter for that route only (fixes the old bug where "skip writing" reached the writer).
- `upstream_from: [owner]` → the input must be your own words (`owner:request`) or an upload.

## Removed
Peter (show + skill + files), Talent dept (Rhea; Architect → Mason in head office), Reel, Pixel, Intel, Hook, Apply, Pitch, Script, Track, Gauge, Audit, Gear, Jai-Writer, Striker-Writer, the cloned voice (Chatterbox), 20 unused skills, dead checks (image_spec, brand_colors, web_audit_scores, make_only).
