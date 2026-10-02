# core/ — shared reel pipeline code

Used by the show builders (Sherlock-Build, Jai-Build; Football-Build uses the football-video template).
Runs only inside `sandbox.exec` (no credentials, no private data).

| File | Used by | Status |
|---|---|---|
| `reel.py` | Sherlock-Build, Jai-Build | build/render driver: `new`, `assets`, `voicetext`, `build`, `data`, `sfx` |
| `fetch_fonts.py` | setup | downloads each show's locked fonts into `fonts/` |
| `components/` | designers + builders | TODO — reusable visual components (`COMPONENTS.md`) |
| `sfx/` | builders | TODO — click sound effects |

Posting is not done here: Post (studio_poster) prepares the post and you approve it (`social.publish`).
