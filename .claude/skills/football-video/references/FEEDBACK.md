# Jai's rules (captured from the Hrithik Tiwari build)

Each rule carries the reason so edge cases can be judged.

## Stack and assets

- **HyperFrames for everything.** Jai stopped the build when an old tool (Chatterbox TTS from the Remotion pipeline) was used: "only use /hyperframes everywhere and for everything … if anything is not here, you ask me."
- **Ask for assets; build only from his files.** He supplies photos, crests, trophies, VO, music and crowd noise ("never generating assets yourself, asking me what it needs and I'll supply"). Low-res photos (about 450px) are fine to use. Say so, and ask for higher-res versions of the same shots.
- **Skip other outlets' branded graphics** (for example a Foot Globe card with baked-in text) even when he sends them. Use his clean photos instead.

## Voice

- He hated the local Kokoro voices (`am_michael` read flat). He records the VO himself, Peter Drury-style, from the script you give him.
- **Plain script text only.** When pronunciation guides were added, he said "no, don't give the pronunciations." Give correct spellings with accents (Mané, João Félix) and nothing else.
- Use "..." in the script where a Drury-style breath before a big line helps.
- Real VO length rules the timeline. His Drury read ran 64s against a 43s estimate; re-time everything from the transcript.

## Design

- **Loved Pitch + Volt; hated the "AI-generated" look**: holograms, glows, gradients. Keep it flat and typographic.
- **Hated "just text all along."** He wants heavy motion graphics and real photos wherever they fit. Even the rivals named in the hook (Mané, Félix) get real photos.
- **Run `/ui-ux-pro-max` for the design pass** and again when correcting frames.
- **No overlaps on faces**: the Golden Glove trophy was sitting on Hrithik's face. Check every frame for props or text covering a face, number or headline.
- **Sharpen rough edges**: dead frames (the empty first 0.7s), clipped accents (MANE without its É), photos covering text, captions touching blocks.

## Captions

- One sentence at a time (clean fragments of 2–8 words for long ones), **centred**, with a **colour tracker** on the word being spoken. Left-aligned single words were rejected.
- Real per-word timing from `hyperframes transcribe`; display text corrected to the script's spelling.

## Sound

- **Clicks, not whooshes; clicks replaced the impacts too.**
- Crowd noise bed under the whole video, dipped for the caveat beat.

## Proof

- **Tests for every goal and every frame**, run against the real render, with a proof sheet. "Verify to me that each goal and each frame works and it's rendered properly." Report failures honestly; fix the build or the test, and say which.
