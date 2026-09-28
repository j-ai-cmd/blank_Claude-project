---
name: sherlock
description: Runs Jai's full sherlock_teaches_ai Instagram reel pipeline end to end - research, script in Sherlock Holmes' voice, /ui-ux-pro-max design pass, component scouting (smoothui.dev, amicro.vercel.app, bencho.dev, inspora.design, bestdesignsonx.com), asset request, approval gate, voiceover, click sound effects, HyperFrames build, checks, render, and caption. Use when Jai says "sherlock" (any session, any folder) - "sherlock, build a video on X", "hey sherlock", "sherlock make a reel about X" - or asks for a new AI reel.
---

# Sherlock

Project: `/Users/jaidhingra/JAI_INSTA` (run every command from there). Show: `shows/sherlock/`.
Full step detail, commands, and the approval-message template: [PROCESS.md](PROCESS.md).

## Hard rules

1. Nothing is voiced, built, or rendered before Jai approves the script.
2. Every asset comes from Jai: character art, photos, logos, video, and sound files. Never draw, generate, download, scrape, screenshot, or reuse media of your own, not even placeholders. Work out exactly what's needed, ask, and use only Jai's files. Holmes' art: `shows/sherlock/character/` (idle.png, talk.png, blink.png): the basic Holmes Jai approved on 2026-09-26. Episode media (logos, screenshots, photos) still comes only from Jai.
3. Style is locked: `shows/sherlock/brand/DESIGN.md` (Forest + Cream, Gloock + Karla). Never change it.
4. Every episode invokes `/ui-ux-pro-max` and scouts the five component sources.
   All video work goes through `/hyperframes` (existing project: skip its intent interview).
5. Clicks everywhere: every interaction cues a sound from `core/sfx/` (Pixabay pack, approved by Jai).
6. Voice: Kokoro `bm_lewis` (British), speed 1.0, Jai's pick. The voice mangles short unusual names (it said "Jeff" for Jev), so put new names in `shows/sherlock/voice/PRONOUNCE.json` before building. ≈150 words/min: 30s ≈ 75 words, 45s ≈ 110, 60s ≈ 150. Never clone a real actor.
7. **Ending (permanent, every video):** the last spoken words are always
   `Elementary [pause 0.6] isn't it?` (a real 0.6s pause; `[pause N]` works in any `say` line).
   Everything else follows Holmes' own voice in `brand/CHARACTER.md`.

## Checklist (copy into the task list and tick off)

- [ ] 1. Read `shows/sherlock/brand/CHARACTER.md`, `core/COMPONENTS.md`, `core/SOURCES.md`
- [ ] 2. Research (WebSearch if news; keep sources)
- [ ] 3. Write the beats in Holmes' voice (mystery → method → verdict), ending with rule 7.
        Length from rule 6; 60s reels: 7–9 beats.
- [ ] 4. Design pass: invoke `/ui-ux-pro-max`; pick a kit component per beat (≥ half the beats,
        2+ kinds); scout the five sources for a better/new component; run ux/gsap searches
- [ ] 5. Asset list: who/what, framing, format, which beat
- [ ] 6. Send ONE message: script + visuals + assets + sources. **STOP and wait.**
- [ ] 7. After approval: port any approved new component into `core/components/`
- [ ] 8. `python3 core/reel.py sherlock new <slug>`; write `script.json` + `VISUALS.md`; put Jai's files in `assets/media/`
- [ ] 9. `python3 core/reel.py sherlock assets <dir>` until every box is ticked
- [ ] 10. `python3 core/reel.py sherlock build <dir>` (voice, timings, mouth, sound effects)
        Then: captions always show the script's words; Whisper only times them. If the build prints `CHECK PRONUNCIATION (script -> heard)`, the voice said a word wrong (e.g. Jev -> Jeff): add it to `shows/sherlock/voice/PRONOUNCE.json` (respelling, or IPA in slashes like `"Jev": "/dʒˈɛːvː/"`), re-run build, repeat until the line is gone or only lists harmless number/spelling variants. Never ship a video with a mispronounced name.
- [ ] 11. `npx hyperframes@0.8.76 check` + snapshot; review against /ui-ux-pro-max; fix
- [ ] 12. Render, copy to `shows/sherlock/output/`.
- [ ] 13. Write the detailed description: `output/<slug>.description.md`, detailed and ready to paste: Instagram caption (hook line,
        numbered takeaways, the ending line, comment/save/follow CTAs, 3–5 hashtags (Instagram caps posts at 5) from the brand set,
        under 2,200 characters), chapters with timestamps from `assets/episode.js`, a glossary of every
        term the reel uses, alt text, trending-audio ideas (re-checked with WebSearch), sources, and notes
        (what's illustrative, which assets Jai supplied, the cover frame). Then re-run
        `python3 core/brandkit.py sherlock` so the new cover lands in `brand-kit/covers/`.
        Also add a `## First comment` section (sources + one question) and set `"cover": <seconds>`
        in `script.json` (the frame with the hook headline + key visual).
        Send the MP4 + description.
- [ ] 14. **Publish (only after Jai approves the finished video):** run the dry run, show Jai the
        plan, ask "Post it to @sherlock_teaches_ai now?", and only on a clear yes run with `--yes`:
        `python3 core/publish.py sherlock <slug> --expect sherlock_teaches_ai` → then `… --yes`. Send Jai the permalink.
        Details and reach settings: PROCESS.md § 6.

Brand kit (profile photo, wordmarks, colours, fonts, voice…): `shows/sherlock/brand-kit/BRAND.md`.

Commands need the venv: `export PATH="$PWD/.venv/bin:$PATH"`.

## Quick example

Jai: "sherlock, build a 30s video on vector databases"
→ steps 1–6, then a message like:

```
EP. 07 · Vector databases · ~30s · 72 words
1. THE MYSTERY  [hero · quote]      SAYS: "Observe. Your AI finds 'dog' when you type 'puppy'. How?"
2. THE METHOD   [corner · sources]  SAYS: "Every sentence becomes a point in space..."
3. THE VERDICT  [hero · counter]    SAYS: "...Elementary [pause 0.6] isn't it?"
VISUALS: beat 2 kit `sources`; beat 3 NEW `magnet-select` (bencho.dev/blocks/magnet-select)
ASSETS I NEED: 1. pinecone-logo.png: Pinecone logo, transparent PNG (beat 2)
Approve, and send the assets when ready.
```
→ wait → steps 7–12.
