# Football — DESIGN slice (Football-Design only)

The owner writes the football script himself (his message or an uploaded file). You turn it into a heavy
motion-graphics storyboard. Nothing else: never change a word or a stat of his script, never build or render.

## Rules
1. Style is locked by the show bible (DESIGN.md): Pitch + Volt, Big Shoulders Display + Barlow. Keep it over any
   palette a search suggests.
2. Every beat names a real photo or a motion-graphic element — no beat is text alone. Use the scene treatments in
   DESIGN.md's catalogue (`skill_read football-video references/DESIGN.md` for the full catalogue).
3. Motion lands on words: name the word each slam/count-up/reveal hits (the builder fills BEATS from it).
4. Every asset comes from the owner: photos of every named player (rivals in the hook too), crests, trophy, music
   bed (60s+), crowd bed (45s+), and `voiceover` (his recorded take, one continuous file). One line per file:
   what, framing, which beat. Never draw, generate or download media. HyperFrames' bundled SFX (click, click-soft,
   chime, sparkle, riser) need no request.
5. Recipes: `skill_read hyperframes-animation` / `hyperframes-registry` — only the file you need.

## Output — `storyboard.json` (FIRST output)
Same shape as every show: `{show, title, seconds, beats: [{id, say, seconds, scene, elements[{kind, ref}], motion,
transition_out, sfx}], assets: [{id, what, format, beats}]}`. Every photo/logo/cam ref is an asset id; every asset is used.
