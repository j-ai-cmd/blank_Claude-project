---
name: sherlock-carasoul
description: Builds and posts the daily "AI Case File" Instagram carousel for Jai's sherlock_teaches_ai page - takes today's date, searches what's new in the AI world in the last 24 hours, picks the top stories, writes slides in Sherlock Holmes' voice, lists the logos/screenshots Jai must send, waits for approval and files, renders 1080x1350 JPEG slides in the locked Sherlock brand, writes the caption, and publishes the carousel after Jai's yes. Use when Jai says "sherlock-carasoul", "sherlock carousel", "sherlock-carousel", "today's carousel", "daily AI carousel", or asks for a Sherlock AI-news carousel.
---

# Sherlock carousel (daily AI news)

Project: `/Users/jaidhingra/JAI_INSTA` (run every command from there; `export PATH="$PWD/.venv/bin:$PATH"`).
Show: `shows/sherlock/`. Today's folder: `shows/sherlock/carousels/<YYYY-MM-DD>/`; a second carousel the same day (e.g. a themed one) uses `<YYYY-MM-DD>-<slug>/` and that folder name is the `<DATE>` argument everywhere.
Renderer: `core/carousel.py`. Publisher: `core/publish_carousel.py`.

## Hard rules

1. Nothing is rendered before Jai approves the slide text. Nothing is posted before Jai approves the rendered slides with a clear yes for posting.
2. Every image comes from Jai: logos, screenshots, photos. Never download, scrape, screenshot, generate, or reuse media, not even placeholders. List exactly what each story needs; Jai sends the files; they go in `assets/`. Holmes' art (`shows/sherlock/character/idle.png`, `talk.png`) is Jai-approved and is placed by the renderer on the cover and closing slides.
3. Brand is locked (`shows/sherlock/brand/DESIGN.md`: Forest + Cream, Gloock + Karla, one brass accent). The renderer already applies it; never restyle.
4. Every fact has a source dated within the window. No source, no slide. Holmes' voice from `shows/sherlock/brand/CHARACTER.md` (calm, dry, plain words, no jargon without translation).
5. The closing slide headline is always `Elementary… isn't it?`

## Checklist (copy into the task list)

- [ ] 1. **Date.** Run `date +%F` and use that as `<DATE>`. Window = last 24 hours (Monday: since Friday morning).
- [ ] 2. **Research.** Several WebSearch calls in one turn ("AI news <date>", "OpenAI OR Anthropic OR Google DeepMind announcement <date>", "AI model release this week", "AI funding <date>", "AI policy regulation <date>", "open source AI model release <date>"). Open the primary source (company blog, paper, filing) for each candidate. Drop anything older than the window, rumours, and duplicates.
- [ ] 3. **Pick 4–6 stories** that a general Instagram audience cares about. Jai wants **controversy, not just updates**: at least half the picks should be debate-worthy (lawsuits, safety incidents, rogue agents, jobs and layoffs, privacy/surveillance, copyright, deepfakes, big-tech power plays, regulator clashes, public spats between AI leaders). Fill the rest with big launches, money, or a surprising research result. Research step 2 adds searches like "AI lawsuit <date>", "AI controversy <date>", "AI backlash <date>". Mix categories; at most two from one company. Cover hook and first-comment question should invite a take. Controversy never excuses rumours: sourced facts only.
- [ ] 4. **Write `carousel.json`** (`python3 core/carousel.py new <DATE>` makes the template). Slides: 1 `cover`, one `story` per pick, 1 `close`; 10 max.
      - cover: `kicker` "THE AI CASE FILE", `headline` ≤ 7 words teasing the biggest story (never the same words as that story's slide headline), `sub` one line naming the next-best clue.
      - story: `tag` (MODEL RELEASE / PRODUCT / FUNDING / MONEY / MARKETS / HARDWARE / POLICY / LAWSUIT / LEGAL / SAFETY / JOBS / CONTROVERSY / RESEARCH / OPEN SOURCE), `headline` ≤ 8 words,
        `body` ≤ 2 sentences / 200 chars, `verdict` ≤ 10 words in Holmes' voice,
        `image` filename Jai will send (or `null` for a text-only slide), `source` the outlets the facts came from.
      - Each story slide is a clue → evidence → deduction:
        - `headline` is the clue: one concrete fact with a number, name or date ("722 AI math papers. Three already withdrawn."), not a vague tease.
        - `body` sentence 1 is the evidence (who, what, when, how many). Sentence 2 is what it means for the reader. Lawsuits and accusations say "alleges"/"claims".
        - `verdict` is Holmes' deduction: a statement that takes a position. Never an "X, or Y?" question; questions belong in the caption.
        - No unsourced framing ("critics say", "experts warn") unless a named source says it. Numbers and dates must match the source exactly.
      - Order stories strongest first; no two slides in a row with the same tag.
      - close: `headline` "Elementary… isn't it?", `body` "One case file every day. Comment the story you want solved next.", `cta` "Save · Share · Follow".
- [ ] 5. **Design check.** Invoke `/ui-ux-pro-max` on the slide text (hierarchy, length, readability on a phone); trim anything that wraps past 3 headline lines.
- [ ] 6. **Write `description.md`**: `## Instagram caption` (hook line, numbered one-line summaries, "Elementary… isn't it?", comment/save/follow CTA, 3–5 hashtags from the brand set, under 2,200 chars), `## First comment` (sources as plain names + one question), `## Sources` (full URLs).
- [ ] 7. **Send ONE message and STOP:**
      ```
      AI CASE FILE · <DATE> · <N> slides
      01 COVER   <headline> / <sub>
      02 <TAG>   <headline> — <body> — VERDICT: <verdict>  [image: <file>]
      ...
      NN CLOSE   Elementary… isn't it?
      IMAGES I NEED (send as files, transparent PNG for logos, full-width PNG/JPG for screenshots):
        1. <file> — <what exactly: e.g. "Anthropic logo, transparent PNG"> (slide 02)
      CAPTION: <caption>
      SOURCES: <urls>
      Approve, and send the images.
      ```
- [ ] 8. After approval: save Jai's files into `assets/` with the listed names. Logos often arrive with a fake (baked-in) checkerboard instead of real transparency: check `sips -g hasAlpha`; if `no`, run `python3 core/carousel.py clean <DATE> <file>` (makes near-white/light-grey background transparent, keeps the original as `<file>.orig.png`) and tell Jai about any watermarks you see. `python3 core/carousel.py assets <DATE>` until every box is ticked. If Jai skips an image, set that slide's `image` to `null` (text-only layout); if Jai sends a screenshot that should fill the card, set `"image_fit": "cover"`.
- [ ] 9. `python3 core/carousel.py render <DATE>`. Look at every `slides/NN.jpg` (Read tool); fix overflow, awkward wraps, empty space; re-render.
- [ ] 10. Send Jai the slides (SendUserFile, all JPEGs) + final caption. Ask: "Post it to @sherlock_teaches_ai now?"
- [ ] 11. **Publish, only on a clear yes:** `python3 core/publish_carousel.py <DATE> --expect sherlock_teaches_ai` (dry run), then the same with `--yes`. Send Jai the permalink.
      Token: `INSTAGRAM_ACCESS_TOKEN_SHERLOCK` in `.env`, the same one the `sherlock` reel skill uses (long-lived, has `pages_manage_posts`; details in ~/.claude/skills/sherlock/PROCESS.md § token). If the dry run reports a token or permission problem, stop and tell Jai; never print the token.

## How publishing works

Instagram's API takes carousel photos only as public URLs. The publisher uploads each slide as an unpublished, temporary photo on the Facebook Page linked to @sherlock_teaches_ai (nothing shows on the Page), uses its Facebook CDN URL as `image_url`, publishes the carousel, posts the first comment, then deletes the Page photos. `published.json` blocks double posts.
