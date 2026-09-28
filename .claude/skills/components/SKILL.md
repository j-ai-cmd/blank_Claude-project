---
name: components
description: Use when a project needs interactive UI components, micro-interactions, or animated effects added or upgraded — "make this interactive", "add some polish/motion", "pull in a component library" — or when the user names bencho.dev, amicro.vercel.app, smoothui.dev, inspora.design, or bestdesignsonx.com by name.
---

# Components

## Overview

Five sources come up repeatedly for interactive UI work. Only three have installable code; two are inspiration-only. This skill routes to the right one per component and never lets a flashy demo get rewritten from scratch when the original ships.

## Sources — what's actually usable

| Source | Has code? | Install | License | Caveat |
|---|---|---|---|---|
| **smoothui.dev** | Yes, ~198 components | `npx shadcn@latest add @smoothui/<name>` | — | Needs React + Tailwind v4 + `motion`. Cleanest option — try here first. |
| **amicro.vercel.app** | Yes (MIT) | Primitives (spotlight, tilt-card, magnetic-button, text-reveal, etc.): shadcn registry — `npx shadcn@latest add https://raw.githubusercontent.com/Subhan-code/Amicro--Micro-transitions-/main/registry/ui/<name>.json`. Homepage button demos (glare, morph, focus-blur): not in the registry — copy `AnimatedButton.tsx` + `FocusBlur.tsx` + `buttons.tsx` from the repo's `src/components/` and `src/data/` by hand. | MIT | Its README's `npx @subhanhq/amicro add` is dead (that package is just the site build) — use the registry URL instead. Expect a stray TS error or two to patch. |
| **bencho.dev** | Yes, per-block (MIT) | No CLI, no public repo. Open the block → **Code** tab → **Copy prompt** → paste the returned source in by hand. | MIT (bencho.dev/licence) | Only ~half the blocks expose "Copy prompt" — if a block lacks it, substitute a smoothui/amicro equivalent rather than reverse-engineering the compiled bundle. Ships its own CSS variable names (`--ink`, `--fill-slab`, etc.) — map each to the project's existing tokens in one scoped block, never invent new globals. |
| **inspora.design** | No | — | — | Gallery only. Reference for direction, never a source of code. |
| **bestdesignsonx.com** | No | — | — | X/Twitter design feed. Same — look, don't copy. |

**Order of preference: smoothui → amicro → bencho.** Reach for bencho only when the specific block you want isn't in the other two, and only after confirming it has a Copy prompt button.

## Workflow

1. **Brainstorm the fit before touching any site.** Invoke `superpowers:brainstorming` to work out, with the user, which components actually belong: where in the existing UI, what interaction it adds, and why — not "what looks cool on the demo page." A component with no clear job doesn't go in.
2. **Confirm scope before installing.** Once the brainstorm produces a candidate list, tell the user exactly which components and which files/pages they touch, and wait for a yes before running any install or copy.
3. **Get the code, not a rewrite.** Use the table above per component. Never hand-author a component that one of these three already ships — copy the original file(s) verbatim, then wire it in.
4. **Mark every edit to third-party source.** Wiring props (`onClick`, `label`, callbacks), fixing a type error, removing a duplicate attribute — each such change gets an inline comment tagging it as a deliberate edit (e.g. `/* wiring: added onClick */`), so a future diff against upstream shows exactly what's project-specific.
5. **Theme without touching upstream files.** Map the library's CSS variables to the project's existing design tokens in one new, clearly-labeled scoped CSS block. Don't edit the library's own classes or introduce new global tokens the project didn't already have.
6. **Verify before calling it done.** Typecheck, build, and render the affected pages (localhost or equivalent) at both desktop and mobile widths. Confirm the specific interaction actually works (click it, drag it, hover it) — don't just confirm it compiles.

## Common mistakes

- Treating inspora.design or bestdesignsonx.com as installable — they're mood boards.
- Running `npx @subhanhq/amicro add` from Amicro's README — that command doesn't work; use the shadcn registry URL instead.
- Trying to get bencho.dev source from its GitHub — the repo is private/404; the only path is the Code tab's Copy prompt button, and only on blocks that have it.
- Skipping the brainstorm step and installing whatever looked most animated on the source site.
- Rewriting a component's internals to "clean it up" instead of wiring props onto the original.
