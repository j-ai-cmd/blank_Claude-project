# core/ — shared reel pipeline code (skeleton)

Needed by jai, sherlock, football-video (Frame runs it in the sandbox):

| File | Used by | Status |
|---|---|---|
| `reel.py` | jai, sherlock, football-video | ✅ built — never synthesizes; uses voice_line output (Sherlock) or your recorded voiceover (Jai, Football) |
| `brandkit.py` | sherlock | TODO |
| `components/` | jai, sherlock | TODO — reusable visual components |
| `sfx/` | jai, sherlock | TODO — click sound effects |
| `publish.py` | sherlock, football-video | **Not created on purpose** — publishing is stripped (config/skills.yaml adapters); you post manually |

Runs only inside `sandbox.exec` (no credentials, no private data).
