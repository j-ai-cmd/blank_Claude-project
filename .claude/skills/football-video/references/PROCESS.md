# Process: commands per step

`EP` = the new episode project directory. `T` = `~/.claude/skills/football-video/template`.

## 1–2. Research and script

- Web search each fact. Keep a sources list: league site, Transfermarkt, FBref, Sofascore, club site, reputable press.
- Write the script to `<series>/01-scripts/<slug>.md`: a VO table (segment, line) plus a beat plan (beat, scene treatment, assets).

## 3. Design pass

```bash
S=~/.claude/skills/ui-ux-pro-max/scripts/search.py
python3 $S "sports broadcast kinetic motion graphics" --design-system -p "<Series>" --variance 9 --motion 10 -f markdown
python3 $S "<beat-specific need, e.g. stat reveal count up>" --domain gsap -n 3
```

Keep the Pitch + Volt palette over any palette the search returns (Jai's choice). Apply its style, effects and motion through DESIGN.md.

## 5. Approval message format

```
FOOTBALL VIDEO · <Player / story> · ~<N>s · <W> words · <SERIES> EP. <NN>
1. HOOK     [rival photos dot-screen + outline names]   "He faced Mané and João Félix..."
2. NOW      [volt block + hero roar + trophy]           "Now? He's India's Golden Glove goalkeeper."
...
SCRIPT (for you to voice, plain text):
<full script, correct spellings, "..." for breaths>
STATS + SOURCES:
- 78.1% save rate, best in the ISL: <url>
ASSETS I NEED (drop into <EP>/assets/incoming/):
1. <player> photos, 3–7: headshot, action, club kit, national kit, celebration; 1500px+ short side (beats 1, 3, 5)
2. <rival> photo, 1 each (hook)
3. <club> crest PNG, <new club> crest PNG, <national> crest PNG (payoff)
4. <trophy> photo (hook + payoff)
5. Music bed (instrumental, 60s+) and stadium crowd recording (45s+), WAV/MP3
6. Voiceover recorded from the script above, one continuous take
Approve, and send the files when ready.
```

## 6. Build

```bash
cd "<series dir>"
npx hyperframes init <slug> --example blank --resolution portrait --skill general-video --non-interactive
cd <slug> && cp -r "$T"/scripts "$T"/tests . && mkdir -p assets && cp -r "$T"/assets/fonts assets/
/opt/homebrew/bin/python3.12 -m venv .venv && ./.venv/bin/pip install -q pillow numpy soundfile
mkdir -p assets/photos/src assets/photos/cut assets/logos assets/audio/sfx
cp ~/.claude/skills/media-use/audio/assets/sfx/{click,click-soft,chime,sparkle,riser}.mp3 assets/audio/sfx/
```

Photos: cut out, then crop to the subject (untrimmed alpha margins make props tiny and break bottom anchoring):

```bash
for f in assets/photos/src/*.png; do HYPERFRAMES_PYTHON="$PWD/.venv/bin/python" npx hyperframes remove-background "$f" -o "assets/photos/cut/$(basename "$f")" --json; done
./.venv/bin/python - <<'PY'
from PIL import Image; import glob
for f in glob.glob("assets/photos/cut/*.png"):
    im=Image.open(f).convert("RGBA"); b=im.split()[3].point(lambda v:255 if v>24 else 0).getbbox()
    if b: im.crop(b).save(f)
PY
```

VO and captions timing:

Captions show the approved script text word for word; the transcript supplies timing only. Put every word Whisper mis-hears (names, clubs, numbers written differently) in `FIX` so the caption matches the script, and diff the final caption text against the script before rendering: any difference is a bug.

```bash
ffmpeg -y -i <jai-vo>.mp3 -ar 48000 assets/audio/vo.wav
ffprobe -v error -show_entries format=duration -of csv=p=0 assets/audio/vo.wav   # -> VO_DUR in build_index.py
npx hyperframes transcribe assets/audio/vo.wav --model small.en --json            # writes assets/audio/transcript.json
```

Fill `build_scenes.py`: `SCENES` (scene start = first word of each segment, duration = next start − this start; last scene = VO end + ~2s hold), `TOTAL`, and `BEATS` (the word each motion lands on). Rewrite the `OUT[...]` scene blocks for this story using the DESIGN.md catalogue. Fill `build_index.py`: `VO_DUR`, `FIX` (every mis-heard name), `MANUAL` (awkward caption breaks), `SFX` (clicks on cuts and slams). Edit `apply_treatments.sh` selectors (rivals → INK, bench → GREY). Music and crowd files from Jai go to `assets/audio/music.wav` and `assets/audio/crowd-bed.wav` (trim or loop to `TOTAL` with ffmpeg if needed).

```bash
python3 scripts/build_index.py              # writes scenes, captions, index
./scripts/apply_treatments.sh               # HyperFrames media treatments (after every rebuild)
node ~/.claude/skills/hyperframes-audio/scripts/carve.mjs --comp index.html --bed el-bgm --voice el-vo
npx hyperframes check
```

## 7. Frame review

```bash
npx hyperframes render --workers 2 --output renders/draft.mp4
i=0; for t in <one time per beat>; do ffmpeg -y -ss $t -i renders/draft.mp4 -frames:v 1 -vf scale=270:-1 /tmp/cs/f$(printf %02d $i).png -loglevel error; i=$((i+1)); done
ffmpeg -y -i /tmp/cs/f%02d.png -filter_complex "tile=8x2" -frames:v 1 renders/contact-sheet.png
```

Read the sheet. Check for faces covered, text under photos, clipped accents, captions touching blocks, empty frames, low contrast on volt. Fix, rebuild, repeat.

## 8. Tests

```bash
npx hyperframes render --workers 2 --quality draft --variables '{"sceneOpacity":0}' --output tests/captions-only.mp4
rm -rf tests/frames && ./.venv/bin/python tests/test_episode.py renders/draft.mp4
```

The generic tests (render integrity, black and frozen frames, loudness and clipping, crowd bed, caption sentence, centring, band and tracker) carry over unchanged. Rewrite the G4 per-scene goal tests: one per beat, sampling the real frame at that beat's time (photo present, volt coverage, grey beats desaturated, crest colours, prop clear of face). Keep every threshold honest. When a test fails, look at the frame first, then decide whether the build or the test is wrong, and say which.

## 9. Post caption

`renders/<slug>.description.md`, sections in this order:

1. **Instagram caption** (paste-ready, under 2,200 characters): a hook line built on the story's contrast ("Three years on the bench at FC Goa. One season to change that."), who he is in one line, the stats as a numbered list, the caveat plus payoff in one short paragraph, then three CTA lines (comment question, save, "Follow for more. We find the best rising talents, so you don't have to."), then 3–5 hashtags (Instagram caps posts at 5), picked from: player, league, club, series, `#ScoutingReport`.
2. **Chapters**: `m:ss` + beat name, from `SCENES` starts.
3. **Cover frame**: the strongest volt-block frame (time + what's in it), plus a backup.
4. **Alt text**: one paragraph describing what the reel shows.
5. **Sources**: every stat with its URL.
6. **Notes**: which assets Jai supplied, anything low-res or unverified.

Reference: `/Users/jaidhingra/Jdotai- videos/rising-isl-talents/hrithik-tiwari-ep1/renders/hrithik-tiwari-ep1.description.md`.

## 10. Deliver

Send `renders/draft.mp4`, `tests/proof-sheet.png`, `tests/REPORT.md` (generate from `tests/report.json`: goal / test / result / measured). The MP4 may only reach the desktop app if it is above about 15 MB; say so.
