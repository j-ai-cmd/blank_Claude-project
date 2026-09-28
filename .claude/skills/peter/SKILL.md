---
name: peter
description: Runs Jai's brainrot Instagram reel pipeline, modelled step for step on brainrotshorts.com's Reddit story generator - story (Reddit link, pasted text, or a premise) → Peter Griffin voice → gameplay background → caption style → generate → export, with Jai's approval gate, Bubblegum + Plum style, twist hits, comment cards, part splitting, and click sounds. Use when Jai says "peter" ("peter, make this <reddit link>", "peter, story about <premise>", "hey peter") or sends a Reddit story for a brainrot reel.
---

# Peter (brainrot)

Project: `/Users/jaidhingra/JAI_INSTA` (run commands from there). Show: `shows/brainrot/`.
Read first: `shows/brainrot/brand/CHARACTER.md` (script shape, niches) and `brand/DESIGN.md` (locked style).
Full step detail and the approval template: [PROCESS.md](PROCESS.md).

## Hard rules

1. Nothing is voiced, built, or rendered before Jai approves the script.
2. Every asset comes from Jai: Peter's art (`shows/brainrot/character/` idle.png, talk.png, optional
   blink.png), gameplay clips (`library/bg/`), music (`library/music/`), meme sounds (`library/sfx/`).
   Never draw, generate, download, rip, or reuse media of your own, not even placeholders.
3. No UI-kit components in this show. Style is locked (Shrikhand + Courier Prime, gum + plum).
4. Video work goes through `/hyperframes` (existing project: skip its intent interview).
5. Original voice only (`voice/VOICE.json`); never clone the real actor.
6. Strip usernames and identifying details. Premise stories are original fiction: never present them
   as a real post (no invented upvote/comment counts).

## The 5 steps (same order as brainrotshorts.com), plus the approval gate

- [ ] **1. Story.** One of three inputs:
      - Reddit link → read post, OP edits/updates, top comments (Chrome via Claude in Chrome; if that
        fails, ask Jai to paste). Never guess the story.
      - Pasted text → use it as the source.
      - Premise ("peter, story about a guy who…") → write an original story in the chosen niche's style.
      Then write the script: title → hook → story → twist(s) → comment/update → punchline (30–40s,
      ~95–115 words; longer stories → parts with a cliffhanger and a "FOLLOW FOR PART 2" outro).
- [ ] **2. Voice.** Peter by default (`voice/VOICE.json`). Jai may name another voice candidate.
- [ ] **3. Background.** List `library/bg/`; pick a clip + start offset not used in the last 5 episodes
      (check `shows/brainrot/episodes/*/script.json`). Empty library → ask Jai for clips (≥60s, no audio).
- [ ] **4. Caption style.** `pop` (default: 1–2 huge words) or `highlight` (up to 4 words, spoken word lit).
      Optional music bed from `library/music/`.
- [ ] **Approval gate:** one message with the post card, beats (twists, comment card, outro marked),
      run time, voice, clip + offset, caption style, music, assets needed, source link. **STOP.**
- [ ] **5. Generate + export.** `python3 core/reel.py brainrot new <slug>` → write `script.json` →
      `assets` (until all ticked) → `build` → `check` + snapshots (title, twist, comment, end) →
      `render` → copy to `shows/brainrot/output/` → write the detailed `output/<slug>.description.md`
      (core/WORKFLOW.md step 5) → send MP4 + description.
      Multi-part: build every part in one go (part numbers in `"part"`).

Commands need the venv:

```bash
export PATH="$PWD/.venv/bin:$PATH"
python3 core/reel.py brainrot new roommate-airbnb
python3 core/reel.py brainrot assets shows/brainrot/episodes/<date>-roommate-airbnb
python3 core/reel.py brainrot build shows/brainrot/episodes/<date>-roommate-airbnb
```

## Example

Jai: "peter, story about a guy whose roommate secretly rented out his room on Airbnb"
→ premise input, original story (no fake counts), r/tifu style → approval message (see PROCESS.md)
→ wait → build, render, send.
