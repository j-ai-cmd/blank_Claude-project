# Artsy Components — Reference

## SVG filters

Paper grain (overlay on a full-bleed rect, `mix-blend-mode: multiply`, opacity 0.15–0.35):

```html
<svg width="0" height="0" style="position:absolute">
  <filter id="grain">
    <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="3" seed="7" stitchTiles="stitch"/>
    <feColorMatrix type="saturate" values="0"/>
  </filter>
</svg>
<div class="grain" style="position:absolute;inset:0;filter:url(#grain);mix-blend-mode:multiply;opacity:.25"></div>
```

Rough / torn edge (apply to a shape or a text block):

```html
<filter id="rough">
  <feTurbulence type="turbulence" baseFrequency="0.04" numOctaves="2" seed="3" result="n"/>
  <feDisplacementMap in="SourceGraphic" in2="n" scale="6"/>
</filter>
```

Risograph misregistration: render the same headline twice — one layer in the accent color offset by 2–4 px, `mix-blend-mode: multiply` — and add `url(#grain)` on top. Keep the offset fixed across slides so it reads as a print trait, not a glitch.

Always set `seed` on feTurbulence so output is identical every render.

## rough.js

```js
import rough from 'roughjs';
const rc = rough.svg(svgEl);
svgEl.appendChild(rc.rectangle(40, 40, 400, 120, {
  seed: 12, roughness: 1.6, stroke: 'var(--ivory)', strokeWidth: 3, fill: 'none'
}));
```

`seed` is required for determinism. For video draw-on, set `stroke-dasharray` / `stroke-dashoffset` on the generated paths and animate `dashoffset` from the HyperFrames timeline.

## rough-notation

```js
import { annotate } from 'rough-notation';
const a = annotate(el, { type: 'underline', color: 'var(--ivory)', strokeWidth: 3, animate: false, padding: 4 });
a.show();
```

Types: underline, box, circle, highlight, strike-through, crossed-off, bracket. Its built-in animation is timer-based. For video: `animate: false`, then animate the generated SVG path's `stroke-dashoffset` from the timeline. Its randomness is not seedable — take one render and keep it (the drawn SVG is static once shown).

## Paper Shaders

Shaders available (from the package's `dist/shaders`): color-panels, dithering, dot-grid, dot-orbit, fluted-glass, gem-smoke, god-rays, grain-gradient, halftone-cmyk, halftone-dots, heatmap, image-dithering, lens-distortion, liquid-metal, mesh-gradient, metaballs, neuro-noise, paper-texture, perlin-noise, pulsing-border, simplex-noise, smoke-ring, spiral, static-mesh-gradient, static-radial-gradient, swirl, voronoi, warp, water, waves.

Best fits for a print/poster look: grain-gradient, paper-texture, halftone-dots, halftone-cmyk, dithering, image-dithering (turns a photo into a dithered print).

Deterministic use: construct `ShaderMount` with `speed = 0`, then call `mount.setFrame(ms)` on every timeline tick (frame value is milliseconds since start). Uniform names differ per shader — read the shader's `.d.ts` in `node_modules/@paper-design/shaders/dist/shaders/` before wiring. For a static PNG: set one frame, wait for a paint, export.

React wrappers: `@paper-design/shaders-react`.

## React Bits

Install via shadcn registry: `npx shadcn@latest add @react-bits/<Name>-TS-TW` (also JS / CSS variants; jsrepo supported). Browse names at reactbits.dev. Many text animations use GSAP or `motion` on their own clock — in HyperFrames, replace the autoplay trigger with a progress value from the timeline and mark that edit with a `/* wiring: ... */` comment.

## Inspiration (look, don't copy)

- Hand-painted Bollywood posters: heavy display type, 2–3 flat colors, painted borders, vignette.
- Indian matchbox labels: centered emblem, thin ornamental frame, small caps, misprint.
- Truck art ("Horn OK Please"): bold outlines, repeated motifs, decorative corner pieces.
- Risograph zines: grain, overprint, limited inks.

## Sources added later

(Record new vetted sources here: name, license, what it does, deterministic how.)
