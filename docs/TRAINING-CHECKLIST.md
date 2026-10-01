# Your team (41 employees): what each does, when it works, what it needs from you

**The basics:**
- Each employee reads one training file, `context/<employee_id>.md`, and nobody else can read it.
- Add facts under **Owner facts** in that file. The employee treats them as true and can cite them.
- If something listed under **Owner must provide** is missing when a task needs it, the employee stops and asks you.
- Files you upload go in `uploads/<scope>/`. Each scope is readable only by the employees below. You can upload through the API, the Live Office, or by dropping files in that folder.

| Scope | Holds | Who can read it |
|---|---|---|
| `profile/` | CV, strengths, weaknesses, past cover letters | Apply, Letter |
| `finance/` | statements | Ledger, Gauge |
| `show-<name>/` | that show's photos, clips, voiceover | that show's employees only |
| `lane-company/` | company material | company-lane employees only |
| `general/` | anything else | every specialist |

## Core (report to you)
| Employee | Does | Works when | Needs from you |
|---|---|---|---|
| Atlas · Chief of Staff | Routes work that needs two teams; daily/weekly digest | #hq or DM; a lead asks another team | Nothing |
| Vera · Verifier | Grades the work against what you asked | **Only when you say "verify"**, or on a new hire's tasks | Nothing |
| Proof · Fact checker | Checks every fact and number against its source | All Sales work; anything with numbers or sources | Optional: trusted sources |
| Lex · Librarian | Saves only the memories you tick | When you accept work; weekly | Nothing |

## Studio: Maya (#studio). Every video goes through /hyperframes
| Employee | Does | Works when | Needs from you (as you go) |
|---|---|---|---|
| Reel | Videos that belong to no show | Video request naming no show | Reference videos, music |
| Pixel | Visuals that belong to no show | Visual request naming no show | Brand kit (optional) |
| Jai + Jai-Design | @jaidhingra_ reels in your cloned voice (Chatterbox); the /jai skill is the style guide | "jai reel / jai video" | Voice recording + consent; clips per reel |
| Sherlock + Sherlock-Design | AI reels, Kokoro bm_lewis voice | "sherlock reel" | Assets per reel |
| Striker + Striker-Design | Football reels with the voiceover you record | "football video / striker reel" | Your voiceover; player assets |

## Sales: Sam (#sales). All research and all writing
| Employee | Does | Works when | Needs from you |
|---|---|---|---|
| Scout | Finds jobs, companies hiring, clients to pitch | "find me …" | Targeting (roles, industries, locations, salary floor) |
| Intel | Sourced research brief (client, job, topic) | First step of pitches, applications, scripts | Nothing |
| **Burrow** · Rabbit holes | Finds and **picks** the rabbit holes for your scripts | Script chains; "find rabbit holes on …" | **Your rabbit-hole taste (you'll send it)** |
| Hook | Pitch emails, DMs, follow-ups (sent only after your click) | After Intel/Scout | 2–3 emails that got replies; provable results |
| **Letter** · Cover letters | Raw, passionate cover letters from the job description + your strengths and weaknesses + every past pitch | Every application, after Intel | Upload strengths, weaknesses, CV, past letters to `profile/` |
| Apply | CV + application answers; attaches Letter's letter; submits only after your click | After Intel (and Letter) | CV in `profile/` |
| Pitch | Proposals and decks | After Intel | Case studies, rate card |
| Script | Scripts and captions for non-show videos | Reel's videos | Nothing |
| Jai/Sherlock/Striker-Writer | Each writes only its own show's script and captions (its show skill) | That show's reels, after Intel/Burrow | Nothing |
| **Track** · Pipeline | Every pitch/application you send is logged automatically; Track updates replies, interviews, offers and follow-up dates | Right after the 9am scan; "where are my pitches at" | Nothing |
| **Scan** · Inbox | Every day at **9:00** it opens every email from the last 24h and reports the positive replies | Daily 9:00 (Asia/Kolkata — change `owner_tz` if wrong) | Email connector: `IMAP_*` in the server env (Gmail app password) |

## Talent: Rhea (#talent)
| Architect | Designs a new employee as a proposal; `/wf hire <file>` puts it live on probation | You ask for a new role | Your hire-vs-train rule |

## Engineering: Forge (#engineering)
| Employee | Does | Works when |
|---|---|---|
| Byte | **Personal** projects: code (test-first), specs, tickets | Engineering work that isn't company work |
| **Byte-Co** | **Company/work** code + Power Automate flows | Your words name company work: "company/work/office" + code, repo, bug, API, flow, automation… (or "lane: company") |
| Loom | Web UI, portfolio, preview deploys (joins company work too) | UI tasks |
| Audit | Reviews, site/SEO/speed audits (joins company work too) | Review tasks |
| Gear | **Make.com only** automations + setup guides (joins company work too) | Automation tasks |

## Ops: Otto (#ops)
| Ledger | Bookkeeping + invoices from your uploaded statements | Money tasks | Statements (CSV) in `finance/`; invoice details |
| Gauge | Dashboards and weekly reports | Report tasks | Export files |

---

## How work stays separate (and never mixes)
1. **One lane per task.** A task belongs to at most one show (Jai, Sherlock, Striker) or lane (company). Only that lane's employees can be assigned. The code rejects anyone else (Sherlock can never get Jai's video; personal Byte never gets company work).
2. **Outsiders are barred.** Reel, Pixel and Script can't join show tasks. Only listed helpers may join a lane: Intel and Burrow for shows; Loom, Audit and Gear for company.
3. **Memory is kept per lane.**
   - Standing rules you give on a show or lane task apply only to that lane.
   - A shared helper's memory from a lane is stored under `<id>@<lane>` and only loads for that lane.
   - Vera and Proof keep no memory at all.
4. **Files are kept per lane.** A producer's sandbox contains only its own show's folder, its show's uploads, and the inputs it was handed. It can't run another show's pipeline (`reel.py <other-show>` is refused).
5. **Your cloned voice is locked to Jai.** The Dispatcher picks each show's voice; an employee can't ask for another show's voice.
6. **One owner per task type, one platform per deliverable.** When Gear and Byte-Co build one automation together, each gets only its own packet. Gear's output must be pure Make.com and Byte-Co's pure Power Automate (the `make_only` and `power_automate_only` checks reject any mix). Neither can read the other's work unless the plan hands it over.
7. **Handoffs carry only outputs, never context.** Each employee gets a fresh session and reads only what the plan passed it. Its own outputs are prefixed with its step (`T1-…`) and can't be overwritten.

## Commands (Slack `/wf …` or the Live Office)
`hire <proposal>` · `end-probation <id>` · `pause <employee|dept>` · `resume …` · `pause-all` · `status` · `gc` · `sweep`
