---
name: jai
description: Runs Jai's personal @jaidhingra_ Instagram reel pipeline end to end - extensive research on an interesting general topic Jai gives, brainstorming, a script in Jai's own casual English voice (/humanizer, /hallmark on the words), /ui-ux-pro-max design pass, component scouting, /artsy-components effects per reel, asset request, approval gate, voiceover in Jai's cloned voice (Chatterbox), click sound effects, HyperFrames build, checks, render, and caption. Jai posts it himself. Use when Jai says "jai" (any session, any folder) - "jai, build a video on X", "hey jai", "jai make a reel about X".
---

# Jai (@jaidhingra_, general topics)

Project: `/Users/jaidhingra/JAI_INSTA` (run every command from there). Show: `shows/jai/`.
Follows `core/WORKFLOW.md` with `<show>` = `jai`. Read first: `shows/jai/brand/CHARACTER.md`
(voice, script shape, research rules) and `shows/jai/brand/DESIGN.md` (locked style).

## Hard rules

1. Nothing is voiced, built, or rendered before Jai approves the script.
2. Every asset comes from Jai: photos, clips, logos, screenshots, sound files. Never draw,
   generate, download, scrape, screenshot, or reuse media of your own, not even placeholders.
   Work out exactly what's needed, ask, and use only Jai's files.
3. Style is locked: `shows/jai/brand/DESIGN.md` (Jai's personal brand: Vermilion `#B8432B` +
   Ivory `#FBEFD5` + Ink `#2A1410`, saffron `#F4B658` labels, Rozha One + Mukta, handle
   `@jaidhingra_` top right, no series label). Every episode invokes `/ui-ux-pro-max`, scouts
   `core/SOURCES.md`, and picks effects with `/artsy-components`. All video work goes through
   `/hyperframes` (existing project: skip its intent interview).
4. Clicks everywhere: every interaction cues a sound from `core/sfx/`.
5. Voice: Jai's own voice, cloned by **Chatterbox** from `shows/jai/voice/reference/prompt.wav`
   (`shows/jai/voice/VOICE.json`: engine `chatterbox`, setting A = exaggeration 0.5, cfg 0.5,
   seed 7; Jai's pick 2026-09-28). No accents, no base voice, no other engine. Voicing is slow
   (~2 min per sentence on this Mac): tell Jai before a long build.
6. **English only. No Hindi words, ever** (Jai's rule), in the script, captions, or caption text.
7. On screen: faceless (kit components, typography, Jai's photos/clips) plus Jai on camera now
   and then. A camera beat is `"cam": "<asset id>"` (+ optional `"cam_in"` seconds into the clip):
   the clip plays full bleed and muted. Audio is always the cloned voice, never the clip's sound,
   so ask for camera clips where Jai is not talking to camera (reacting, walking, doing the thing,
   looking at something); lips would not match the voiceover.
8. Topic comes from Jai. Research is extensive and every fact has a source.
9. No fixed sign-off. Length varies by topic (≈150 words/min: 30 s ≈ 75 words, 60 s ≈ 150).
10. **Never publish.** Jai posts to @jaidhingra_ himself. Stop at MP4 + description.

## Checklist (copy into the task list and tick off)

- [ ] 0. Voice ready: `ls shows/jai/voice/reference/prompt.wav`. Missing → ask Jai to record
        (`shows/jai/voice/reference/RECORD.md`), then `python3 core/reel.py jai clone <file> <start> <secs>`.
- [ ] 1. Read `shows/jai/brand/CHARACTER.md`, `core/COMPONENTS.md`, `core/SOURCES.md`.
- [ ] 2. Research, extensive: WebSearch 5+ angles (what, why, history, numbers, surprising
        details, common myths), primary sources first, cross-check every number twice. Keep sources.
- [ ] 3. Brainstorm: invoke `superpowers:brainstorming` with the research in hand. Settle the angle
        (hook fact, payoff), the length, and where camera beats go. Ask Jai at most 1–2 quick
        questions; if his brief is clear, state the angle and move on.
- [ ] 4. Script: beats in Jai's voice (hook → context → rabbit hole → payoff), English only.
        Run the `say` lines through `/humanizer`, then `/hallmark` on the script text only
        (generic hooks, filler, stock phrasing). Hallmark never touches the visual design.
- [ ] 5. Design pass: invoke `/ui-ux-pro-max`; kit component per beat (≥ half the beats, 2+ kinds);
        scout the five sources (smoothui.dev, amicro.vercel.app, bencho.dev, inspora.design,
        bestdesignsonx.com; `core/SOURCES.md`); run the ux/gsap searches (`core/WORKFLOW.md` step 2).
        Then `/artsy-components`, chosen per reel (no fixed texture): from Jai's carousel language
        (paper grain, riso-offset headline, torn edge + tape on photos, rough-notation underline on
        his strongest line), only where it does a job. Max 1–2 artsy layers per frame, text stays
        readable, deterministic for video. No hand-rolled effects.
- [ ] 6. Asset list (like Sherlock): every photo, logo, screenshot, clip the reel needs, each with
        who/what, framing, format (transparent PNG for logos), which beat. For each camera beat, what
        Jai should be doing on camera (not talking to camera). Never source them yourself.
- [ ] 7. Send ONE approval message: script + length reason + visuals + artsy effects + assets +
        sources (format below). **STOP and wait.**
- [ ] 8. After approval: port any approved new component into `core/components/` (rules in
        `core/SOURCES.md`), add it to `core/COMPONENTS.md`.
- [ ] 9. Set up the episode:
        ```bash
        cd /Users/jaidhingra/JAI_INSTA && export PATH="$PWD/.venv/bin:$PATH"
        python3 core/reel.py jai new <slug>          # prints the episode folder
        ```
        Write the approved `script.json` (shape: `shows/jai/template/script.json`) and `VISUALS.md`
        into it. Put Jai's files in `assets/media/` under the requested names.
- [ ] 10. `python3 core/reel.py jai assets <dir>` until every box is ticked (build refuses otherwise).
- [ ] 11. `python3 core/reel.py jai build <dir>` (cloned voice, timings, captions, clicks; run it in
        the background, it's slow). Any `CHECK PRONUNCIATION` line → add a respelling to
        `shows/jai/voice/PRONOUNCE.json`, rebuild. Never ship a mispronounced word.
- [ ] 12. HyperFrames: load `/hyperframes` (existing project, skip its intent interview), then:
        ```bash
        cd <episode-dir>
        npx hyperframes@0.8.76 check                                  # must end with 0 errors
        npx hyperframes@0.8.76 snapshot --frames 6 --describe false   # snapshots/contact-sheet.jpg
        ```
        Read the contact sheet; review against /ui-ux-pro-max (`references/quick-reference.md`:
        contrast, hierarchy, one focal point per beat, motion that means something). Fix overlaps,
        clipped text, empty beats, bad crops. Headline too long → shorten in `script.json`, re-run
        `python3 core/reel.py jai data <dir>` + `sfx` (no re-voice). Repeat until clean.
- [ ] 13. Render and copy out:
        ```bash
        npx hyperframes@0.8.76 render -o renders/<slug>.mp4 && cp renders/<slug>.mp4 ../../output/
        ```
        Watch-check: voice/caption sync, camera clips on their beat, clicks audible.
- [ ] 14. Write `shows/jai/output/<slug>.description.md` (core/WORKFLOW.md step 5): Instagram caption
        (hook line, takeaways, comment/save/follow CTAs, 3–5 hashtags, under 2,200 chars), chapters
        with timestamps from `assets/episode.js`, alt text, sources, a `## First comment`, and the
        cover second. The caption is posted as Jai: follow `~/.claude/skills/my-writing-style/SKILL.md`
        if it exists, English only. Send the MP4 + description with SendUserFile. Done: Jai posts it.

## Voice upkeep

- Change the clip the voice copies: `python3 core/reel.py jai clone take-5.m4a 40 14`, then
  `python3 core/reel.py jai voices` (renders A/B/C into `shows/jai/voice/candidates/`).
- Voice runs from `.venv-chatterbox` (Python 3.11); `reel.py` calls it, no PATH change needed.
  Rebuild it with the command in `/Users/jaidhingra/JAI_INSTA/CLAUDE.md` (Setup).

## Approval message format

```
JAI · Three hearts · ~40s · 98 words (40s: one mechanism, 4 facts)
1. HOOK      [cam: you on camera]  SAYS: "Octopuses have three hearts. And one of them quits when they swim."
2. CONTEXT   [compare]             SAYS: "Two pump blood through the gills, one pumps it to the body..."
3. WHY       [counter]             SAYS: "Their blood runs on copper, not iron. That's why it's blue..."
4. PAYOFF    [quote]               SAYS: "So they'd rather crawl. Would you?"
VISUALS (/ui-ux-pro-max + scout): beat 2 kit `compare`; beat 3 kit `counter`; looked at … (not used: why)
ARTSY: paper grain (all beats), rough underline on "they'd rather crawl" (beat 4)
ASSETS I NEED: 1. hook-cam.mp4: you on camera, vertical, 3-5 s, looking at the sea, not talking (beat 1)
Sources: Smithsonian Ocean, Journal of Experimental Biology (Wells 1983).
Approve the script, and send the assets when ready.
```
