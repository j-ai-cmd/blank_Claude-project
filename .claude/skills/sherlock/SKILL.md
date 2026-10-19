---
name: sherlock
description: Runs Jai's full sherlock_teaches_ai Instagram reel pipeline end to end - research, script in Sherlock Holmes' voice, /ui-ux-pro-max design pass, component scouting (smoothui.dev, amicro.vercel.app, bencho.dev, inspora.design, bestdesignsonx.com), asset request, approval gate, voiceover, click sound effects, 2D or 3D Holmes (lip-synced 3D figure), HyperFrames build, checks, render, and caption. Use when Jai says "sherlock" (any session, any folder) - "sherlock, build a video on X", "hey sherlock", "sherlock make a reel about X" - or asks for a new AI reel.
---

# Sherlock

Project: `/Users/jaidhingra/JAI_INSTA` (run every command from there, with the venv on PATH:
`export PATH="$PWD/.venv/bin:$PATH"`). Show: `shows/sherlock/`.
Full step detail, commands, and the approval-message template: [PROCESS.md](PROCESS.md).

No topic given ("hey sherlock")? Read the newest file in `shows/sherlock/ideas/` (written by
`/sherlock-ideas`) and offer its pitches; if there is none, offer to run `/sherlock-ideas`.

## Hard rules

1. Nothing is voiced, built, or rendered before Jai approves the script.
2. Every asset comes from Jai: character art, photos, logos, video, and sound files. Never draw, generate, download, scrape, screenshot, or reuse media of your own, not even placeholders. Work out exactly what's needed, ask, and use only Jai's files. Holmes' art: `shows/sherlock/character/` (idle.png, talk.png, blink.png): the basic Holmes Jai approved on 2026-09-26. The one exception is **3D Holmes** (`shows/sherlock/character3d/`): a CAD figure traced from that art, which Jai asked for and approved on 2026-10-13. Don't make other 3D or generated media. Episode media (logos, screenshots, photos) still comes only from Jai.
3. Style is locked: `shows/sherlock/brand/DESIGN.md` (Forest + Cream, Gloock + Karla). Never change it.
4. Every episode invokes `/ui-ux-pro-max` and scouts the five component sources.
   All video work goes through `/hyperframes` (existing project: skip its intent interview).
5. Clicks everywhere: every interaction cues a sound from `core/sfx/` (Pixabay pack, approved by Jai).
6. Voice: Kokoro `bm_lewis` (British), speed 1.0, Jai's pick. The voice mangles short unusual names (it said "Jeff" for Jev), so put new names in `shows/sherlock/voice/PRONOUNCE.json` before building. ≈150 words/min: 30s ≈ 75 words, 45s ≈ 110, 60s ≈ 150. Never clone a real actor.
7. **Holmes is 2D or 3D, per episode.** `script.json` `"character": "2d"` (default: Jai's PNG art) or
   `"3d"` (the jointed 3D figure, lip-synced to the narration by `reel.py`). Ask Jai which one in the
   approval message (step 6); default 2D. 3D can also walk in (`"holmes_entrance": "walk"`) and
   gesture per beat (`"holmes_move": "wave" | "think" | "point"`): propose them with the script.
   Details: PROCESS.md § 4 "3D Holmes" and `shows/sherlock/character3d/README.md`.
8. **Ending (permanent, every video):** the last spoken words are always
   `Elementary [pause 0.6] isn't it?` (a real 0.6s pause; `[pause N]` works in any `say` line).
   Everything else follows Holmes' own voice in `brand/CHARACTER.md`.

## Checklist (copy into the task list and tick off)

- [ ] 1. Read `shows/sherlock/brand/CHARACTER.md`, `core/COMPONENTS.md`, `core/SOURCES.md`
- [ ] 2. Research (WebSearch if news; keep sources)
- [ ] 3. Write the beats in Holmes' voice (mystery → method → verdict), ending with rule 8.
        Length from rule 6; 60s reels: 7–9 beats.
- [ ] 4. Design pass: invoke `/ui-ux-pro-max`; pick a kit component per beat (≥ half the beats,
        2+ kinds); scout the five sources for a better/new component; run ux/gsap searches
- [ ] 5. Asset list: who/what, framing, format, which beat
- [ ] 6. Send ONE message: script + visuals + assets + sources + Holmes 2D or 3D (rule 7). **STOP and wait.**
- [ ] 7. After approval: port any approved new component into `core/components/`
- [ ] 8. `python3 core/reel.py sherlock new <slug>`; write `script.json` (with `"character"`) + `VISUALS.md`; put Jai's files in `assets/media/`
- [ ] 9. `python3 core/reel.py sherlock assets <dir>` until every box is ticked
- [ ] 10. `python3 core/reel.py sherlock build <dir>` (voice, 3D Holmes if `"character": "3d"`, timings, mouth, sound effects).
        Load `/hyperframes` before touching the composition (existing project: skip its intent interview).
        Then: captions always show the script's words; Whisper only times them. If the build prints `CHECK PRONUNCIATION (script -> heard)`, the voice said a word wrong (e.g. Jev -> Jeff): add it to `shows/sherlock/voice/PRONOUNCE.json` (respelling, or IPA in slashes like `"Jev": "/dʒˈɛːvː/"`), re-run build, repeat until the line is gone or only lists harmless number/spelling variants. Never ship a video with a mispronounced name.
- [ ] 11. `npx hyperframes@0.8.76 check` + snapshot; review against /ui-ux-pro-max; fix.
        3D Holmes: confirm he is visible in every snapshot (a blank Holmes box means the GLB didn't load).
- [ ] 12. Render, copy to `shows/sherlock/output/`.
- [ ] 13. Write `output/<slug>.description.md` (caption, `## First comment`, chapters, glossary, alt text,
        trending-audio ideas, sources, notes; full spec in PROCESS.md § 5), set `"cover": <seconds>` in
        `script.json`, re-run `python3 core/brandkit.py sherlock`. Send the MP4 + description.
- [ ] 14. **Publish (only after Jai approves the finished video):** run the dry run, show Jai the
        plan, ask "Post it to @sherlock_teaches_ai now?", and only on a clear yes run with `--yes`:
        `python3 core/publish.py sherlock <slug> --expect sherlock_teaches_ai` → then `… --yes`. Send Jai the permalink.
        Details and reach settings: PROCESS.md § 6.

Brand kit (profile photo, wordmarks, colours, fonts, voice…): `shows/sherlock/brand-kit/BRAND.md`.

## Quick example

Jai: "sherlock, build a 30s video on vector databases"
→ steps 1–6, then a message like:

```
EP. 07 · Vector databases · ~30s · 72 words · Holmes: 2D (or 3D?)
1. THE MYSTERY  [hero · quote]      SAYS: "Observe. Your AI finds 'dog' when you type 'puppy'. How?"
2. THE METHOD   [corner · sources]  SAYS: "Every sentence becomes a point in space..."
3. THE VERDICT  [hero · counter]    SAYS: "...Elementary [pause 0.6] isn't it?"
VISUALS: beat 2 kit `sources`; beat 3 NEW `magnet-select` (bencho.dev/blocks/magnet-select)
ASSETS I NEED: 1. pinecone-logo.png: Pinecone logo, transparent PNG (beat 2)
Sources: <links>
Approve, pick 2D or 3D Holmes, and send the assets when ready.
```
→ wait → steps 7–12.
