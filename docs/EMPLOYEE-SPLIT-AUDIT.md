# Employee split audit — one job, minimal memory

Rule: every request splits into **Research+Write → Design → Build**. Each employee loads only the skill text for its own step.

## 1. Your usual prompts → who does what

| Your prompt | Research + Write | Design | Build | Verdict |
|---|---|---|---|---|
| "football video on <player>" | Intel (stats) → Striker-Writer | Striker-Design | Striker | Split exists, wiring broken (F1–F6) |
| "jai, build a video on X" | Burrow + Intel → Jai-Writer | Jai-Design | Jai | Same |
| "sherlock, reel on <AI topic>" | Burrow + Intel → Sherlock-Writer | Sherlock-Design | Sherlock | Same |
| "peter, <reddit link>" | Peter-Writer | Peter-Design | Peter | Same + voice contradiction (F9) |
| non-show explainer / promo / music video | Script (no researcher) | **nobody** | Reel (designs + builds) | Not split (F7) |
| "pitch <client>" | Scout → Intel → Hook / Pitch | Pitch (deck) | Pitch | Pitch does all 3 (F11) |
| "apply to <job>" | Scout → Intel → Letter + Apply | — | Apply submits | OK |
| inbox 9am | Scan → Track | — | — | OK |
| "build me a site / UI" | Forge spec | **nobody** | Loom (designs + builds) | Not split (F11) |
| code / bug / spec / tickets | Byte (11 routes) | — | Byte | Too broad (F12) |
| automation | Gear (Make) / Byte-Co (Power Automate) | — | same | OK |
| money / reports | Ledger / Gauge | — | — | OK |
| new employee | Rhea → Architect | — | — | OK |

## 2. Ideal 3-way split for every video

| Role | Knows ONLY | Skills | Output |
|---|---|---|---|
| Writer | topic research (from Intel/Burrow), show voice, script shape, captions | show `write` slice + humanizer | script + beats + caption |
| Designer | show design bible, components, motion language | ui-ux-pro-max, components, hyperframes-animation, hyperframes-registry, show `design` slice | per-beat storyboard: scene, component, motion, transition |
| Builder | HyperFrames code, audio, render | hyperframes-core, -cli, -keyframes, -audio, media-use, show `build` slice | MP4 |

## 3. Flags (worst first)

| # | Flag | Where | Fix |
|---|---|---|---|
| F1 | **Writers are told to skip writing, designers told to skip design.** Skill adapters apply to *every* route that loads the skill. `football-video`/`jai`/`sherlock`/`peter` adapters say "skip research + script-writing" and "skip /ui-ux-pro-max" — and the Writer + Designer load those same skills. | `config/skills.yaml` adapters; `workforce/routing.py:54` | Key adapters per employee/route, not per skill |
| F2 | **Builders get zero HyperFrames knowledge.** Producer routes run only the show skill; `support:` (hyperframes-core, -cli, -animation…) is stored but never loaded into the prompt. | `workforce/prompts.py:81`, `routing.py:54` | Put build skills in `run`, or load `support` on demand |
| F3 | **Every employee loads the whole show skill** (all 11 steps: research, script, design, build, publish). `scope:` is one prose line. Memory waste + role bleed. | `skills.yaml` show routes | Split each show skill into `<show>-write`, `<show>-design`, `<show>-build` |
| F4 | **No motion designer exists.** Designers output PNG only; no `components`, no `hyperframes-animation`/`-registry`. `components` only on Loom. `jai` skill still calls deleted `/artsy-components`. Motion graphics are improvised by the builder. | show designer routes | Designer output = beat storyboard JSON; give the skills above |
| F5 | **Designer runs without the script.** No `upstream_from: [show_*_writer]` → visuals can't map to beats. | show designer routes | Add upstream_from writer |
| F6 | **Builders write captions** (`description.md` second output) — duplicates the writer's job. | producer routes | Writer owns caption; builder outputs MP4 only |
| F7 | **Reel designs + builds** (ui-ux-pro-max + hyperframes + workflow ≈ 66 KB). No non-show video designer. `video_script` has no research upstream → Script invents or researches. | Reel, Script routes | Add non-show video designer; `upstream_from: [sales_researcher]` on Script |
| F8 | Skill `references/`, `PROCESS.md`, `template/` never loaded — only `SKILL.md`. Approval format and football template unreachable. | `routing.skill_text` | Load the slice's needed reference files |
| F9 | Contradictions: Striker adapter `voice=base` vs you record VO; Peter adapter strips "any voiceover" vs show `voice: base, kokoro`. | `skills.yaml`, `org.yaml` | Pick one per show |
| F10 | Research is one generic employee (Intel, 794-byte skill) for football stats, AI topics, jobs, clients. Burrow not wired into football. | Intel, Striker-Writer | OK if per-show memory holds; consider a stats-sourcing check |
| F11 | Pitch (deck) and Loom (UI) each design + write/build in one session. | Pitch, Loom | Pixel designs → Pitch/Loom implements |
| F12 | Byte has 11 routes (code, specs, tickets, sprints, PRD, domain model, architecture). Largest memory surface. | Byte | Split planner (docs) vs coder |
