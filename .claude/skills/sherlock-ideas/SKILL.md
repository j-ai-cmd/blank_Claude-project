---
name: sherlock-ideas
description: Researcher for Jai's sherlock_teaches_ai reels. Finds 5 fresh, interesting, controversial AI/tech topics and pitches each in one of three proven Instagram formats (what-if scenario like @zenith.whatif, under-the-hood teardown like @speedy_devv, AI-coding sitcom bit like @canwebuildthis), with hook, comment trigger, beat sketch, and sources. Use when Jai says "sherlock-ideas", "sherlock ideas", "give me sherlock topics", "what should sherlock cover next", or asks for reel ideas for the Sherlock show.
---

# Sherlock Ideas

Research only. Never write a full script, build, or render here. When Jai picks an idea, hand it to the `sherlock` skill.

Formats and why they work: [FORMATS.md](FORMATS.md). Output template: [TEMPLATE.md](TEMPLATE.md).

## Checklist

- [ ] 1. Read `~/JAI_INSTA/shows/sherlock/brand/CHARACTER.md` and [FORMATS.md](FORMATS.md).
- [ ] 2. List what's already covered so nothing repeats:
      `ls ~/JAI_INSTA/shows/sherlock/episodes ~/JAI_INSTA/shows/sherlock/ideas`
      and skim the latest files in `ideas/` (past pitches).
- [ ] 3. Research what's hot right now (last 14 days). Run WebSearch calls in parallel across:
      AI model launches, AI lawsuits/regulation, AI + jobs, open-source releases (GitHub trending),
      AI drama (founders, leaks, safety), big-tech product teardowns, viral AI-coding moments.
      Keep the source URL for every fact.
- [ ] 4. Optional: check the three reference pages for their newest hits (logged-out Instagram via the
      built-in browser; fetch `/reel/<id>/` og:description for caption + likes). Steal the *angle*, never the content.
- [ ] 5. Pick 5 topics. Rules:
      - At least one of each format (what-if, under-the-hood, sitcom); the 5th goes to the strongest.
      - Each must have a real debate: two sides people will argue in the comments.
      - Controversial, not cruel: no attacks on private people, no gender/religion/caste bait,
        no medical or financial advice. Real public figures and companies are fine when the facts are sourced.
      - Every number and claim has a source. Mark speculation as speculation.
      - Fits Holmes: a mystery, clues, a verdict. Ends on "Elementary, isn't it?"
- [ ] 6. Score each: Hook (1-5), Debate (1-5), Freshness (1-5), Buildable with Jai's 2D kit (1-5).
      Order the five by total.
- [ ] 7. Write the pitch file `~/JAI_INSTA/shows/sherlock/ideas/<YYYY-MM-DD>.md` using [TEMPLATE.md](TEMPLATE.md).
- [ ] 8. Reply to Jai with the 5 pitches (short form: title, format, hook, why it'll argue, score)
      and the file path. Ask which one goes to `sherlock`.

## Hard rules

- Sherlock is 2D (Jai's art + UI kit). Zenith's 3D city and canwebuildthis' 3D characters are
  inspiration for structure only. Pitch visuals the kit can build: timelines, counters, diagrams, chat bubbles.
- No assets fetched or generated here. If an idea needs logos/screenshots, list them as "assets Jai would supply".
- Never repeat a topic already in `episodes/` or pitched in the last 30 days of `ideas/`
  unless there's real new news; say so if you do.

## Quick example

Jai: "sherlock-ideas"
→ 5 pitches, e.g.
1. **What if every AI model shut off tomorrow?** (what-if) Hook: "Observe. At 9:00 a.m. every AI goes dark. By noon, ..." Trigger: "What breaks first in your life?"
2. **How does ChatGPT remember you?** (under-the-hood) Trigger: "Comment MEMORY and I'll send the paper."
3. **Claude vs Codex: who's the better detective?** (sitcom) Trigger: "Which one are you working with?"
