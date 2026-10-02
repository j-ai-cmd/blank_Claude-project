# Your team (26 employees): what each needs from you

- Each employee reads one training file, `context/<employee_id>.md`; nobody else can read it.
- Add facts under **Owner facts** in that file. The employee treats them as true and can cite them.
- If something under **Owner must provide** is missing when a task needs it, the employee stops and asks you.
- Uploads go in `uploads/<scope>/`: `profile/` (Letter), `finance/` (Ledger), `show-<name>/` (that show's designer + builder), `lane-<name>/` (that project's engineers), `general/` (every specialist).
- Structure and rules: `docs/ORG.md`.

| Dept | Employee | Does | Needs from you |
|---|---|---|---|
| head office | **Atlas** `chief_of_staff` | route requests that need more than one department; split them into per-department briefs; hire — ask Mason for a new employee when a request has no employee or Lex reports one is bloated; daily digest | Your standing priorities for the week (optional, 3 lines in #hq) |
| head office | **Mason** `architect` | write one new employee's spec — its one job; does/does-not; skills mapped from the installed library; a new SKILL.md slice if none fits; tools; tier; personality; fire rule — plus 3 probation tasks | Nothing required |
| head office | **Vera** `verifier` | check every delivered task against your original request and the approved brief; criterion by criterion | Optional: your 'good enough' bar per work type, as short rules under Owner facts |
| head office | **Proof** `fact_checker` | extract every factual claim; check each against its cited source; corroborate web facts with a second independent source; mark TRUE / FALSE / UNSOURCED | Nothing required |
| head office | **Lex** `librarian` | save only memories the owner ticks; supersede old standing rules; weekly cleanup; report any employee whose memory is bloated to Atlas | Nothing required. Optional: bloat thresholds in config/memory.yaml (default 60 entries / 12,000 chars) |
| studio | **Maya** `studio_lead` | turn your video request into a brief; get the Sherlock script (or your caption) from Sales via Atlas; run the show's designer then its builder; then the poster | Default video specs per channel (aspect, length, fps) — under Owner facts; The football Instagram account handle (for Post) |
| studio | **Sherlock-Design** `show_sherlock_designer` | turn the Sherlock-Writer script into a beat-by-beat storyboard — scene; components; motion; transitions — in Forest + Cream; Gloock + Karla | Nothing now — the locked DESIGN.md is the brief; assets as you go |
| studio | **Sherlock-Build** `show_sherlock_builder` | build and render the Sherlock storyboard in HyperFrames with the base voice (Kokoro bm_lewis) | Your asset files per the storyboard's list |
| studio | **Jai-Design** `show_jai_designer` | turn your Jai script into a beat-by-beat storyboard — scene; components; artsy effects; motion — per shows/jai/brand/DESIGN.md | Nothing now — the locked DESIGN.md is the brief; assets as you go |
| studio | **Jai-Build** `show_jai_builder` | build and render @jaidhingra_ reels in HyperFrames from Jai-Design's storyboard; your on-camera clips and your recorded voiceover | Your asset files per the storyboard's list; Your recorded voiceover per reel (one continuous take) |
| studio | **Football-Design** `show_football_designer` | turn your football script into a beat-by-beat motion-graphics storyboard — player photos; stat cards; motion; transitions — in Pitch + Volt; Big Shoulders + Barlow | Nothing now — the locked DESIGN.md is the brief; assets as you go |
| studio | **Football-Build** `show_football_builder` | build and render football reels in HyperFrames from Football-Design's storyboard; your player assets and your recorded voiceover | Your asset files per the storyboard's list; Your recorded voiceover per reel (one continuous take) |
| studio | **Post** `studio_poster` | prepare the Instagram post for a rendered reel — the right account; the video; the caption and first comment — as one post you approve | The football Instagram handle; An Instagram connector (until then, approved posts land in outbox/ for you to post) |
| sales | **Sam** `sales_lead` | plan every writing chain and pick the one writer who owns it | Nothing required |
| sales | **Echo** `sales_writer` | write like you — pitches; cold emails; DMs; follow-ups; and Jai / football reel captions — trained on your own writing | 5–10 samples of your own writing (emails, DMs, captions) under Owner facts — this IS its training; Words and phrases you never use |
| sales | **Burrow** `sales_ideas` | generate ideas the way you trained it — video topics; angles; rabbit holes; pitch angles — each with a source | Your taste: 5–10 ideas you loved and 5 you'd never use, and why |
| sales | **Sherlock-Writer** `show_sherlock_writer` | research an AI topic and write the Sherlock script + caption in Sherlock Holmes' voice; every fact cited | Optional: Sherlock scripts you like, under Owner facts |
| sales | **Letter** `sales_cover_letter_writer` | raw; passionate cover letters from the job post Scout found and your CV | Your CV in uploads/profile/; Your strengths and weaknesses in 5 lines each, under Owner facts |
| sales | **Scout** `sales_job_finder` | find job posts that fit you; shortlist each with its link; the full JD; and why it fits | Roles, locations, seniority, salary floor and deal-breakers, under Owner facts |
| engineering | **Forge** `eng_lead` | turn a coding request into a brief for that project's own engineer(s) | Nothing required |
| engineering | **Byte** `eng_office_backend` | the AI office's Python backend (workforce/; config/; tests/) — build; fix; spec; tickets — test-first | GitHub connector for code.push |
| engineering | **Loom** `eng_office_frontend` | the Live Office frontend (frontend/) — UI; fixes; deploy previews | Vercel connector for deploy.vercel |
| engineering | **Byte-Co** `eng_company` | your company/work code and Power Automate flows — test-first; only when your words say it's company work | Company repo access (connector) |
| ops | **Otto** `ops_lead` | plan money; reporting and inbox work | Nothing required |
| ops | **Ledger** `ops_bookkeeper` | income and expenses from your uploaded statements; invoices; monthly money report; tax-prep notes | Statements in uploads/finance/; Your invoice details (name, address, tax id) under Owner facts |
| ops | **Scan** `ops_inbox_scanner` | every day at 9am; open each email from the last 24 hours; report the positive replies to your pitches and applications; and update the pipeline | IMAP access (IMAP_HOST / IMAP_USER / IMAP_PASSWORD) |
