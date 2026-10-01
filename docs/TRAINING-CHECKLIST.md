# Your team (22 employees): what each does, when it works, what it needs from you

**The basics:**
- Each employee reads one training file, `context/<employee_id>.md`, and nobody else can read it.
- Add facts under **Owner facts** in that file. The employee treats them as true and can cite them.
- If something listed under **Owner must provide** is missing when a task needs it, the employee stops and asks you.
- Files you upload go in `uploads/<scope>/`. Each scope is readable only by the employees below. You can upload through the API, the Live Office, or by dropping files in that folder.
- See exactly what any employee remembers: `GET /api/memory/<employee_id>` (one block per show for Studio's three); delete a line with `DELETE /api/memory/entry/<id>`.

| Scope | Holds | Who can read it |
|---|---|---|
| `profile/` | CV, strengths, weaknesses, past cover letters | Apply |
| `finance/` | statements | Ledger, Gauge |
| `show-<name>/` | that show's script, voiceover, photos, clips | Pixel, Frame and Post — only on that show's task |
| `lane-<project>/` | one coding project's material | that project's engineer only |
| `general/` | anything else | every specialist |

## Head office (reports to you)
| Employee | Does | Works when | Needs from you |
|---|---|---|---|
| Atlas · Chief of Staff | Routes work that needs two teams; **recruits** when no employee fits or Lex reports a full memory | #hq / Atlas desk; a lead asks another team; Lex's monthly report | Nothing |
| Mason · Architect | Writes a new employee's spec, skill, personality and 3 probation tasks — a proposal you hire with `/wf hire` | Atlas sends a recruit brief, or a lead finds nobody on the team fits your request (after your G1) | Nothing |
| Vera · Verifier | Grades **every** delivery against your original words and the brief | Every task, before it reaches you | Nothing |
| Proof · Fact checker | Checks every fact and number against its source | Anything with numbers or sources; all Sales work | Optional: trusted sources |
| Lex · Librarian | Saves only what you tick; replaces near-duplicates instead of piling up; reports any employee whose memory is 80% full | When you accept work; weekly | Nothing |

## Studio: Maya (#studio). Three channels, three employees; every video goes through /hyperframes
| Employee | Does | Works when | Needs from you (as you go) |
|---|---|---|---|
| Pixel · Design | Thumbnails, covers, graphics in each channel's locked design | Any visual for Sherlock, Jai or Football | 3 thumbnails you like per channel (optional) |
| Frame · Build | Builds + renders the reel. Sherlock: Sherlock-Writer's script in the Kokoro voice. **Jai + Football: your script and your recorded voiceover** — never synthesized | Every reel | Your script + voiceover (upload to `show-jai/` / `show-striker/`) |
| Post · Posting | Prepares file, caption, cover, hashtags, time; posts only after your click (outbox until Instagram is connected) | After every finished reel | Handles + posting times (optional) |

Name the channel in your message: "sherlock, …", "jai reel …", "football video …" (or `show: <name>`).

## Sales: Sam (#sales)
| Employee | Does | Works when | Needs from you |
|---|---|---|---|
| **Voice** · Your style | Pitches, cold emails, DMs, follow-ups, Jai/Football captions and posts — written like you; sends only after your click | Any writing in your voice | **5–10 samples of your writing**; words you never use |
| **Spark** · Ideas | Topics, angles, hooks, rabbit holes — picked the way you trained it, each with a source | "give me ideas on …"; before a Sherlock script | **Your idea taste: 5–10 you loved, 5 you'd never use** |
| Sherlock-Writer | Researches and writes Sherlock scripts + captions, AI topics only | "sherlock …" | Nothing |
| **Apply** · CV + cover letters | Holds your CV; raw, passionate cover letters and application answers; submits only after your click | A job you paste, or one Scout found | CV, strengths, weaknesses, past letters in `profile/` |
| Scout · Jobs | Finds jobs that fit you, with links and why | "find me jobs …" | Targeting (roles, locations, remote, salary floor) |

## Engineering: Forge (#engineering) — one engineer per project
| Employee | Project | Works when |
|---|---|---|
| Byte-Co | Your company/work code + Power Automate flows | Your words name company work ("company/work" + code, repo, bug, API, flow…) |
| Loom | This AI office (dispatcher + Live Office website) | "office app", "live office", "workforce app" |

A new project gets its own engineer: ask Atlas to recruit one.

## Ops: Otto (#ops)
| Employee | Does | Works when | Needs from you |
|---|---|---|---|
| **Scan** · Inbox | Every day at **9:00** opens every email from the last 24h, reports positive replies, marks the pipeline rows replied | Daily 9:00 (Asia/Kolkata — change `owner_tz` if wrong) | Email connector: `IMAP_*` in the server env |
| Ledger | Bookkeeping + invoices from your statements | Money tasks | Statements (CSV) in `finance/` |
| Gauge | Dashboards and weekly reports | Report tasks | Export files |

---

## How work stays separate (and never mixes)
1. **One show or project per task.** A task belongs to at most one show (Jai, Sherlock, Football) or project. Each route is bound to its show; the code rejects anything else (a Sherlock route never runs on a Jai task).
2. **One employee, separate memory per show.** Pixel, Frame and Post keep a separate memory block per show (`studio_builder@jai`, `@sherlock`, `@striker`); only that show's block loads on its task. Department rules never load on a show task.
3. **Small memory by design.** Each block has a 3,000-character budget; a prompt carries at most 4,000 characters of memory and 5 standing rules; only memory that shares a word with the task loads. Vera and Proof keep no memory at all.
4. **Files are kept per show.** Frame's sandbox holds only the task's show folder and its uploads; `reel.py <other-show>` is refused.
5. **Voices belong to the show.** Sherlock: Kokoro. Jai and Football: only your recorded voiceover — synthesis is refused.
6. **Handoffs carry only outputs, never context.** Each employee gets a fresh session, its own training file and only the files the plan passed it. Every step also gets your original words.

## Commands (Slack `/wf …` or the Live Office)
`hire <proposal>` · `end-probation <id>` (until then a new hire's tasks always wait for your G1) · `pause <employee|dept>` · `resume …` · `pause-all` · `status` · `gc` · `sweep`
