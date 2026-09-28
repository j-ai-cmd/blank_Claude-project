# Gotchas (each one cost a render in the reference build)

## Layout and motion

- **GSAP owns `transform`.** An element centred with CSS `translate(-50%, -50%)` loses its centring once GSAP tweens `x`, `rotate` or `scale` on it (the player card sat half off-screen). Centre with `gsap.set(sel, { xPercent: -50, yPercent: -50 })` and keep transforms out of CSS for anything GSAP animates. `hyperframes check` flags CSS-transform conflicts as `gsap_css_transform_conflict`: use `fromTo`.
- **Accents clip.** Big Shoulders' É sits above the line box; with `.ln { overflow: hidden }` it gets cut (MANE). `.ln > span { display: inline-block; padding-top: 0.16em }` fixes it.
- **Transform tweens use transforms.** Tweening `left` fails lint (`gsap_non_transform_motion`); use `x`.
- **Letter staggers trip `content_overlap`.** Every `.ch` span and decorative outline word carries `data-layout-allow-overlap`; photo wrappers carry `data-layout-allow-overflow`. `split()` and `photo()` already add them.
- **Initial hidden states** go in CSS or `gsap.set`, never `tl.set(..., 0)` (frame 0 renders un-hidden).
- **Repeated `fromTo` on one target** (the whip bars) needs `immediateRender: false` plus a `gsap.set` baseline.
- **Hard-coded local times break when VO timing changes.** Every scene time derives from `BEATS` / `SCENES` via `L()` and `D()`.

## Fonts and treatments

- Big Shoulders and Barlow are not in HyperFrames' auto-embedded set. Each composition declares `@font-face` pointing at `assets/fonts/*.woff2`, or the render falls back to a generic font (`font_family_without_font_face`).
- Photo treatments are written into the scene HTML by `hyperframes media-treatment`. The generator overwrites scene files, so run `apply_treatments.sh` after every `build_index.py`. `build_scenes.py` only writes when run through `write_all()` (tests import it safely).
- The palette key is a flat array: `"palette": ["#0f1a11", "#e1fe67"]`. Also, `--grading` needs `--apply`.
- Keep brand crests unfiltered. Dim an "old club" crest with opacity, not CSS filters.

## Audio

- A music bed under the VO must be carved (`carve.mjs`), not just volume-ducked; the workflow requires it before check.
- `carve.mjs` needs `@hyperframes/core` in the project: `npm i -D @hyperframes/core@<cli version>`. It writes a very long `data-fx-chain` line into `index.html`; edit that file with Python string replace, since the Read tool truncates it.
- A section-specific crowd dip is done with separate `<audio>` clips of the same file (`data-media-start`) at different `data-volume`.

## Captions and tests

- Captions measured on the full render get polluted by scene pixels. Test them on the captions-only render (`sceneOpacity` variable = 0; every scene's `#s` reads `var(--sceneOpacity, 1)`).
- The caption band must sit below the content zone (y ≥ 1345). The first version at bottom 190px sat under Instagram's UI, and 50px captions wrapped up into headlines.
- ASR mis-hears names (Phoenix→Félix, Rithik→Hrithik, Joao→João). Fix display text in `FIX`; keep the real timing.

## Environment

- media-use Python paths call `python3` from PATH (system 3.9 is too old): prefix `PATH="$PWD/.venv/bin:$PATH"`. `hyperframes tts` / `remove-background` use `HYPERFRAMES_PYTHON`.
- Keep background-process memory low while rendering on this 16 GB machine. Stop the Studio preview (`npx hyperframes preview --stop`) before heavy jobs.
