# Pitch + Volt design system (locked)

Brand kit with the files (profile photo, logos, covers, highlight covers, tokens, TTF/woff2 fonts, SFX, voice guide): `/Users/jaidhingra/Jdotai- videos/rising-isl-talents/brand-kit/BRAND.md`. New episode covers: edit `brand-kit/src/index.html`, clip 5 (cover template).

Source: Jai's "Pitch + Volt" reference card (Big Shoulders is stadium-signage condensed, Barlow is the scoreboard), resolved by `/ui-ux-pro-max` to **Brutalism**, plus duotone photos and hard offset shadows from its block/duotone and Bauhaus styles. Implemented in `template/scripts/build_scenes.py` (`BASE_CSS`, `JS_LIB`, `photo()`, `split()`).

## Tokens

| Token | Hex | Use |
|---|---|---|
| Pitch (bg) | `#0f1a11` | every background; text on volt |
| Volt | `#e1fe67` | the only accent: headline words, numbers, poster blocks, tracker, borders |
| Chalk | `#eef1e6` | primary text |
| Muted | `#b3baad` | labels, rules, frame chrome |
| Line | `#3d4a3f` | row rules |
| Bench greys | `#141715` `#9ca197` `#c3c7bf` | struggle / caveat beats: accent removed entirely |

Fonts, self-hosted woff2 in `template/assets/fonts/`: `Big Shoulders Display` 800 uppercase for headlines, numbers and names; `Barlow` 700 for labels (30px, 0.14em tracking, uppercase), captions and sub-lines.

## Look

- Flat: 0px corners, solid fills, no glows, gradients, soft shadows, particles or grid overlays.
- Left-aligned, asymmetric type. Big outlined background words (`.out`, Pitch fill with a dark stroke) drift slowly behind photos.
- Volt poster blocks (`.blk`, clip-path wipe in) only on peak beats: the "now" payoff, the season stamp, the hero stat, the line, the CTA.
- Photos: background-removed cutouts with a hard offset shadow silhouette (`.sh`, volt or Pitch, 26px/20px). The subject stays full colour. Rivals get the volt dot-screen treatment (HyperFrames `monoScreen` with palette `["#0f1a11","#e1fe67"]`). Bench years are grey (`saturation -1`). Crests and logos keep exact colours.
- Frame chrome from the series intro on: header row at y≈150 (series name / episode), footer rule plus row at bottom 360px ("Scouting report" / player tag after he is named).

## Layout (1080×1920, Reels safe)

- 72px side margins. Content zone y 250–1340. Caption band y 1345–1500. Footer rule about y 1510.
- Captions: sentence groups (2–8 words, at most 2 lines), centred, Barlow 800 42px uppercase, each word on a Pitch plate; the spoken word flips to a volt plate with Pitch text.

## Motion (heavy, every beat moves)

`JS_LIB` helpers, all seek-safe on one paused GSAP timeline per scene:

| Helper | Effect |
|---|---|
| `chars(sel, t)` | letter stagger rise with rotate, `expo.out`, 0.022s stagger |
| `slideIn / slideOut` | photo slides with a 14px motion blur that resolves |
| `glitch(id, t)` | RGB-split: volt and chalk silhouette copies jitter 0.12s |
| `shake(t, a)` | 3-frame screen shake on slams |
| `punch(sel, t)` | zoom punch 1.14→1 |
| `wipe(sel, t)` | clip-path block reveal |
| `count(sel, to, t, d, dec, suf)` | number count-up |
| `draw(sel, t, d, axis)` | line or ruler draw (scaleX/scaleY) |

Root-level whip: 3 skewed bars (volt / Pitch / volt) sweep across at every scene cut.

## Scene catalogue (from the reference episode)

- **Hook**: rival photos slam in dot-screen with outline names drifting; side-by-side rival tiles; spinning outlined "??" shirt number; volt block wipe; hero roars up from the bottom; trophy spins in beside him.
- **Series intro**: letter-staggered title, volt bar draw, giant outline "01", volt ticker marquee.
- **Scouting report**: cutout right, data rows left (age count-up, height ruler draw, position, coordinates crosshair for home town), name letters stagger over the photo.
- **Struggle**: grey photo, 1→2→3 counter filling year bars, old club crest.
- **Breakout**: volt season block plus action photo; stat rows slide in and count up; hero stat on a volt block with an SVG ring filling to the value.
- **Caveat**: calm, grey, slow push-out; a grid of squares filling to the sample size.
- **Payoff**: numbered honours list (active row goes volt); trophy flies in; national crest flips in; old crest → arrow draw → new crest with a "This week" stamp.
- **The line**: grey "3 yrs" box against a volt "1 season" block that wipes in from the seam, with the hero breaking out of it.
- **CTA**: volt card, "Follow for more", sub-lines on the VO, hero cutout.

## Sound

- Clicks for every cut and every slam (`click.mp3`: 0.7 on cuts, 0.8 on slams). No whooshes, no bass impacts.
- `click-soft` ticks on counters, `chime` and `sparkle` on trophy reveals, `riser` under stat build-ups.
- Jai's music bed at 0.12, carved under the VO with `hyperframes-audio` `carve.mjs`. Jai's crowd bed at about 0.16, dropped to 0.05 for the caveat beat.
