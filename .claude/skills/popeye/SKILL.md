---
name: popeye
description: Runs Jai's football Instagram reel pipeline (Europe + ISL) - Popeye hosts a 30-40s scouting-report style reel with heavy player assets and motion graphics in Pitch + Volt (Big Shoulders + Barlow), modelled on Jai's Hrithik Tiwari draft. Use only when Jai says "popeye" ("popeye, build a video on <player/club/story>", "hey popeye"); for other football video requests use football-video.
---

# Popeye (football)

Project: `/Users/jaidhingra/JAI_INSTA` (run commands from there). Show: `shows/football/`.
Read first: `shows/football/brand/CHARACTER.md` (script shape) and `brand/DESIGN.md` (locked style,
scene list). Scene code: `shows/football/template/components/fb.js`; shared UI kit: `core/COMPONENTS.md`.

## Hard rules

1. Nothing is voiced, built, or rendered before Jai approves the script.
2. Every asset comes from Jai: Popeye's art (`shows/football/character/` idle.png, talk.png, optional
   blink.png), player cutouts, crests, trophies, photos, sound files. Never draw, generate, download,
   scrape, screenshot, or reuse media of your own, not even placeholders. Ask; use only Jai's files.
   Jai's normal photos may be background-removed with `npx hyperframes remove-background` if he asks.
3. Style is locked (Pitch + Volt). Heavy motion: every beat is a scene, every number counts or slams.
4. Every stat has a source (league site, Transfermarkt, FBref, Sofascore, club). Never invent numbers.
5. Video work goes through `/hyperframes`; design decisions through `/ui-ux-pro-max` (it advises on
   motion, hierarchy, contrast only). Scout `core/SOURCES.md` for components that fit a beat.
6. Original voice only (`shows/football/voice/VOICE.json`); never clone a real actor.

## Checklist

- [ ] 1. Research the player/story (WebSearch). Collect stats with sources.
- [ ] 2. Script (30–40s, ~85–100 words): hook contrast → now → bio → 2–3 stat beats → caveat →
       what it got him → CTA. Pick a scene per beat (`hook`, `reveal`, `bio`, `stats`, `ring`,
       `grid`, `bignum`, `honours`, `transfer`, `split`, `panel`, `title`, `cards`, `cta`, or a kit
       component). Set `"popeye"`: `hero` on the first/last talk beats, `peek` on reactions.
- [ ] 3. `/ui-ux-pro-max` pass + source scout; write `VISUALS.md` in the episode.
- [ ] 4. Asset list, specific: "<Player> cutout, transparent PNG, waist up, <club> kit, facing camera
       (beats 2, 3, 6)", "<Club> crest, transparent PNG (beat 7)". Check `shows/football/library/` first
       and reuse what Jai already gave (use `"from"` to name the library file).
- [ ] 5. One message: beats (SAYS + SCENE), stats with sources, assets needed, run time. **STOP.**
- [ ] 6. After approval + files: `python3 core/reel.py football new <slug>`; write `script.json`
       (shape: `shows/football/template/script.json`; set `series`, `footer`); files into `assets/media/`.
- [ ] 7. `python3 core/reel.py football assets <dir>` until every box is ticked (incl. Popeye art).
- [ ] 8. `python3 core/reel.py football build <dir>`.
       Then: captions always show the script's words; Whisper only times them. If the build prints `CHECK PRONUNCIATION (script -> heard)`, the voice said a word wrong (e.g. Jev -> Jeff): add it to `shows/football/voice/PRONOUNCE.json` (respelling, or IPA in slashes like `"Jev": "/dʒˈɛːvː/"`), re-run build, repeat until the line is gone or only lists harmless number/spelling variants. Never ship a video with a mispronounced name.
- [ ] 9. `cd <dir> && npx hyperframes@0.8.76 check` + `snapshot --frames 8 --describe false`; fix crops,
       overlaps, cutouts covering numbers.
- [ ] 10. Render, copy to `shows/football/output/`, write the detailed `output/<slug>.description.md` (core/WORKFLOW.md step 5; 3–5 hashtags max, plus a `## First comment` section with sources + one question), set `"cover": <seconds>` in `script.json`, send MP4 + description.
- [ ] 11. **Publish (only after Jai approves the finished video):** dry run
       `python3 core/publish.py football <slug> --expect popeye_talks_football`, show Jai the summary,
       ask "Post it to @popeye_talks_football now?", and only on a clear yes re-run with `--yes`
       (add `--trial` only if Jai asks). Send the permalink. Reach settings, token refresh and the
       never-post-without-a-yes rule: `~/.claude/skills/sherlock/PROCESS.md` § 6 (same script, same rules).

Commands need the venv: `export PATH="$PWD/.venv/bin:$PATH"`.

## Example approval message

```
POPEYE · Hrithik Tiwari · ~36s · 92 words · RISING ISL TALENTS EP. 01
1. HOOK     [hook]     "He faced Mané and Félix before he had a starting jersey."
2. NOW      [reveal]   "Now he's India's Golden Glove goalkeeper."
3. WHO      [bio]      "Meet Hrithik Tiwari. Twenty-four. Six-foot-three. From Assam."
4. NUMBERS  [ring]     "A 78.1% save rate. Best of any keeper."  (source: indiansuperleague.com)
5. REWARD   [honours]  "Golden Glove. India call-up."
6. MOVE     [transfer] "And this week, a new deal at Odisha FC."
7. CTA      [cta · Popeye hero] "Follow for more."
ASSETS I NEED: 1. mane.png: Sadio Mané cutout, transparent PNG, waist up (beat 1) …
Approve, and send the assets when ready.
```
