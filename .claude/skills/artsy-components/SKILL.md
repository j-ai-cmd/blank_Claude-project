---
name: artsy-components
description: Adds artsy, handmade-feeling visuals — grain, halftone, dithering, paper texture, hand-drawn marks, risograph misprint, torn edges, kinetic type — to static graphics (Instagram carousels, posters, PNG exports) and HyperFrames videos, using Paper Shaders, React Bits, rough.js / rough-notation, and SVG filters, with Indian film-poster / matchbox / truck-art references for direction. Always opens with superpowers:brainstorming. Use when the user says "artsy", "artsy components", "texture", "grain", "handmade", "poster feel", "risograph", "hand-drawn", or wants a carousel, poster, or video to look less digital/less AI-generic.
---

# Artsy Components

Web UI component libraries (smoothui, amicro, bencho — see the `components` skill) are built for hover and click. Hover and click do not exist in a PNG or an MP4. This skill covers what does survive export: texture, marks, and type in motion.

## Quick start

Seeded paper grain over any slide or scene, no install:

```html
<svg width="0" height="0" style="position:absolute"><filter id="grain">
  <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="3" seed="7" stitchTiles="stitch"/>
  <feColorMatrix type="saturate" values="0"/></filter></svg>
<div style="position:absolute;inset:0;filter:url(#grain);mix-blend-mode:multiply;opacity:.25"></div>
```

## Step 0 — brainstorm first (mandatory)

Invoke `superpowers:brainstorming` before touching any source. Work out with the user, per slide / scene:

- What job does the effect do? (mood, emphasis, pacing, "made by a hand" signal). No job, no effect.
- Output medium: static PNG, video (HyperFrames), or both. This decides which sources are allowed.
- Budget: max 1–2 artsy layers per frame. Texture everywhere reads as a filter, not a style.

Get an explicit yes on the list of effects and where each goes before installing anything.

## Sources

| Source | Good for | Static | Video | Install |
|---|---|---|---|---|
| **SVG filters** (feTurbulence, feDisplacementMap) | paper grain, riso misregistration, torn/rough edges, ink bleed | yes | yes | none — inline `<filter>` |
| **rough.js** | hand-drawn boxes, circles, fills, dividers | yes | yes | `npm i roughjs` (MIT) |
| **rough-notation** | hand-drawn underline, circle, highlight, strike on text | yes | yes (see REFERENCE) | `npm i rough-notation` (MIT) |
| **Paper Shaders** | grain-gradient, halftone-dots, halftone-cmyk, dithering, image-dithering, paper-texture, mesh-gradient, warp | yes (screenshot one frame) | yes | `npm i @paper-design/shaders` (Apache-2.0) |
| **React Bits** (reactbits.dev) | kinetic text, split/blur/scramble reveals, artsy backgrounds | rarely | yes | `npx shadcn@latest add @react-bits/<Name>-TS-TW` |
| **Inspiration only** | Indian film posters, matchbox labels, hand-painted truck art, riso zines | — | — | look, never copy artwork |

**Preference order:** SVG filters, then rough.js / rough-notation, then Paper Shaders, then React Bits. Cheapest and most controllable first. React Bits needs React; use it only when the project is already React or the effect is video-only and worth the setup.

## Rules

1. **Deterministic for video.** HyperFrames renders by seeking frames. Nothing may run on wall-clock time. Paper Shaders: `speed: 0`, drive with `setFrame(ms)` from the timeline. rough.js: fixed `seed`. rough-notation: its own animation uses timers — draw with `animate: false` and reveal it through the timeline (details in REFERENCE.md).
2. **Lock the palette.** Every shader color, stroke, and filter tint comes from the project's existing tokens. No new colors introduced by an effect.
3. **Text stays readable.** Grain and halftone go behind or around type, never over body text. Check contrast after the effect is applied.
4. **Get the code, don't rewrite it.** Install or copy the original component. Mark every edit to third-party code with an inline comment (`/* wiring: ... */`).
5. **Never write the user's copy.** Use their exact words or clear placeholders.
6. **Inspiration is not a source.** Take cues (layout, color blocking, borders, lettering energy) — do not trace or reproduce specific artworks.

## Workflow

- [ ] Brainstorm (Step 0) → approved effect list per slide/scene
- [ ] Build one test frame with the chosen effects in the real palette
- [ ] Export it (PNG, or a 2–3 s HyperFrames render) and show the user
- [ ] On approval, apply across all slides/scenes
- [ ] Verify: render twice, confirm frames are identical (determinism); zoom to 100% on phone-size export to check grain isn't mush and text is sharp

## Finding new sources

If the needed effect is not covered above, search for it, then add it to this table only after it passes: license allows use, runs in a browser, can be made deterministic, can be themed with the project's colors. Record it in [REFERENCE.md](REFERENCE.md).

See [REFERENCE.md](REFERENCE.md) for code snippets per source.
