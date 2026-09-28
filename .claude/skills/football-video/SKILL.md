---
name: football-video
description: Makes Jai's football reels end to end (ISL + Europe players, clubs, stories) - research, script, /ui-ux-pro-max design, asset request, HyperFrames build with heavy motion graphics and real player photos in Pitch + Volt, sentence captions with a word tracker, click SFX, tests, render, Instagram post caption. Use when Jai says "football video", or "generate a video on <player / club / match / transfer>".
---

# Football video

Heavy-motion 9:16 football reels in the Pitch + Volt design, built in HyperFrames from Jai's own assets. Reference episode (the build this skill was captured from): `/Users/jaidhingra/Jdotai- videos/rising-isl-talents/hrithik-tiwari-ep1/`.

Read before step 3: [DESIGN.md](references/DESIGN.md) (the locked look) and [FEEDBACK.md](references/FEEDBACK.md) (Jai's rules, each with its reason). Use [PROCESS.md](references/PROCESS.md) for the exact commands per step, and [GOTCHAS.md](references/GOTCHAS.md) whenever a check fails or a frame looks wrong.

## Hard rules

1. **HyperFrames only.** Video work goes through `/hyperframes` and its domain skills (`hyperframes-core`, `hyperframes-animation`, `hyperframes-cli`, `hyperframes-audio`, `media-use`). Remotion, Chatterbox and every other video stack stay out.
2. **Jai supplies every asset**: player photos, crests, trophies, voiceover, music, crowd noise. Ask for each file specifically and build only from what he sends. The one pre-approved exception is HyperFrames' bundled SFX (`click.mp3`, `click-soft.mp3`, `chime.mp3`, `sparkle.mp3`, `riser.mp3`). When a file is missing, stop and ask.
3. **Jai records the voiceover himself** from plain script text you give him: correct spelling, no pronunciation guides. Cloning or imitating a real commentator is off the table for you.
4. **Every stat has a source.** Research on the web; quote numbers exactly as the source gives them.
5. **Approval gate**: build only after Jai approves the script, the beat plan and the asset list.

## Steps

1. **Research** the topic with web search. Done when every claim planned for the script has a source URL.
2. **Script**: 35–45s of VO at hype pace (about 95–110 words). Shape: hook contrast → "now" payoff → series intro → who (bio facts) → the struggle → the breakout stats → caveat → what it got him → the line → CTA "Follow for more. We find the best rising talents, so you don't have to." Done when each sentence maps to one beat.
3. **Design pass**: run `/ui-ux-pro-max` and apply the result through DESIGN.md. Give each beat a scene treatment from the DESIGN.md catalogue. Done when every beat names a real photo or a motion-graphic element; no beat is text alone.
4. **Asset request**: one list, one line per file: what, framing, which beat. Include photos of every named player (rivals in the hook too), crests, trophy, music bed, crowd bed (45s+). Done when every scene element that is not type has a named file.
5. **Approval message** (format in PROCESS.md): beats with scene per beat, the script text for Jai to voice, stats with sources, the asset list, expected run time. **STOP** until Jai approves and sends the files.
6. **Build**: new HyperFrames project, copy `template/` in, stage Jai's files, cut out and crop photos, transcribe his VO, fill `SCENES`/`BEATS` from the transcript, write the scenes, build, apply treatments, carve music under VO. Done when `npx hyperframes check` shows 0 errors.
7. **Review every frame**: contact sheet of every beat; fix overlaps, covered faces, clipped accents, dead frames, captions touching content. Done when a fresh contact sheet shows none of those.
8. **Test**: render the draft and the captions-only test render, rewrite the per-scene goal tests for this episode, run `tests/test_episode.py`. Done when every test passes and the proof sheet shows each goal.
9. **Post caption**: write `renders/<slug>.description.md` (format in PROCESS.md): Instagram caption (3–5 hashtags max: Instagram caps posts at 5), a `## First comment` section (sources + one question), chapters from `SCENES`, cover frame, alt text, sources, notes. The caption is published as Jai: if `~/.claude/skills/my-writing-style/SKILL.md` exists, follow it; otherwise write plain and direct, run `/humanizer` over it. Done when the caption is under 2,200 characters and every stat in it matches the script and its source.
10. **Deliver**: send the MP4, proof sheet, `tests/REPORT.md` and the description file, and name what is still weak. Jai decides when it is final.
11. **Publish** (only after Jai says the video is final): posts to @popeye_talks_football through the Instagram API. Run from `/Users/jaidhingra/JAI_INSTA` (the token lives in its `.env` as `INSTAGRAM_ACCESS_TOKEN_FOOTBALL`):
    ```bash
    python3 core/publish.py --account football --expect popeye_talks_football \
      --mp4 "<project>/renders/<final>.mp4" --desc "<project>/renders/<slug>.description.md" \
      --title "<episode title>" --series "<series name>" --cover <seconds of the cover frame>
    ```
    That is a dry run. Show Jai the summary (account, cover, audio name, caption, first comment) and ask "Post it to @popeye_talks_football now?". Only on a clear yes, re-run with `--yes` (add `--trial` only if Jai asks), then send the permalink. Never post without that yes; approving the video is not approval to post. Reach settings and token refresh: `~/.claude/skills/sherlock/PROCESS.md` § 6. Done when `<slug>.published.json` sits next to the description and Jai has the link.
