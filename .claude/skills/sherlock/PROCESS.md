# Sherlock: full process detail

Everything below runs from `/Users/jaidhingra/JAI_INSTA` with `<show>` = `sherlock`.
Voice: `bm_lewis`, ≈150 words/min. Holmes art: basic Holmes in `shows/sherlock/character/`.
Ending: `Elementary [pause 0.6] isn't it?`. Brand kit: `shows/sherlock/brand-kit/`.

## Steps

### 1. Script
Research if the topic is news (WebSearch, sources in the message). Write `script.json` beats in
the show's voice (see the show's `brand/CHARACTER.md`).

### 2. Design pass: /ui-ux-pro-max + component scout (every episode, no skipping)
Invoke `/ui-ux-pro-max`, then for this script:

1. **Pick the visual for each beat** from the kit (`core/COMPONENTS.md`), at least half kit
   components, 2+ different ones.
2. **Scout the five sources** in `core/SOURCES.md` for anything that shows a beat better than the
   current kit: grep the catalogues for the beat's idea (search, chart, upload, map, timeline,
   compare, vote…), open promising ones in the browser (smoothui.dev, amicro.vercel.app,
   bencho.dev/blocks/<slug>) to watch them move, and browse inspora.design and bestdesignsonx.com
   for motion/layout ideas that fit the topic. Aim for 1 new component per episode when one fits;
   none is fine if the kit already covers it well.
3. **Run /ui-ux-pro-max searches** for the episode's interactions and motion, for example:
   ```bash
   S=~/.claude/skills/ui-ux-pro-max/scripts/search.py
   python3 $S "<main interaction, e.g. drag reorder list>" --domain ux -n 3
   python3 $S "<motion, e.g. stagger reveal cards>" --domain gsap -n 2
   python3 $S "<chart type, if any>" --domain chart -n 2
   ```
   Use its guidance on interaction, motion, hierarchy, and contrast only.
4. **Write `VISUALS.md` in the episode folder:** per beat, the component, where it came from
   (kit or which source), the /ui-ux-pro-max guidance applied, and any new component proposed.

The show's style is **locked** in `shows/sherlock/brand/DESIGN.md` (for Sherlock: Jai's Forest +
Cream / Gloock + Karla card). The design pass never changes fonts, colours, labels, or layout
rules. It only chooses which components show each beat, and new components are restyled to the
locked tokens. If /ui-ux-pro-max suggests a different palette or font, ignore that part.

### 3. Asset request
Decide every media asset the script needs and list it in `script.json` under `"assets"`:

```json
"assets": [
  { "id": "haaland", "file": "haaland.jpg", "what": "Erling Haaland photo, face clearly visible, ideally in City kit", "why": "beat 2 profile card" },
  { "id": "openai-logo", "file": "openai-logo.png", "what": "OpenAI logo, transparent PNG", "why": "beat 3 logo row" }
]
```

Be specific: who/what, framing (face, full body, action), format (transparent PNG for logos),
orientation, and which beat uses it. Ask for the minimum that makes the reel better. Don't ask for
things the kit can draw (charts, UI, numbers, text).

### Approval message (script + visuals + assets, one message, then STOP)

```
EP. 07 · Vector databases · ~30s · 72 words

1. THE MYSTERY  [Holmes: hero · quote]
   SAYS: "..."
   SCREEN: headline "..." / quote "..."
2. THE METHOD   [corner · sources (kit) ⟶ cursor picks the right doc]
   ...

VISUALS (/ui-ux-pro-max + scout; style stays locked):
  - Beat 3 uses NEW "magnet-select" from bencho.dev/blocks/magnet-select, ported to the kit
  - Motion: stagger reveal, expo.out 0.4s (ux: "stream answers token by token")
  - Looked at: smoothui ai-citation, amicro uptime-chart, inspora "motion" (not used: <why>)

ASSETS I NEED (drop in shows/sherlock/episodes/<dir>/assets/media/, or send here):
  1. haaland.jpg: Erling Haaland photo, face visible, City kit (beat 2)
  2. openai-logo.png: OpenAI logo, transparent PNG (beat 3)

Sources: ...
Approve the script and the new component, and send the assets when ready.
```

If the reel needs no assets, say "No assets needed."

### 4. Build (after approval + assets)
First port any approved new component into `core/components/` (rules in `core/SOURCES.md`), add
it to `core/COMPONENTS.md` and the showcase episode, and re-check the showcase.

```bash
export PATH="$PWD/.venv/bin:$PATH"
python3 core/reel.py sherlock new <slug>                 # prints the episode folder
# write the approved script.json into it; put Jai's files in assets/media/ (rename to the requested names)
python3 core/reel.py sherlock assets <episode-dir>       # [x]/[ ] checklist; build refuses while any are missing
python3 core/reel.py sherlock build <episode-dir>        # voice + timing + sound effects
# read the build output: any CHECK PRONUNCIATION line means a word was said wrong → fix in voice/PRONOUNCE.json, rebuild
cd <episode-dir> && npx hyperframes@0.8.76 check
npx hyperframes@0.8.76 snapshot --frames 6 --describe false
```
Read `snapshots/contact-sheet.jpg` and review it against the /ui-ux-pro-max checklist
(`references/quick-reference.md`: contrast, hierarchy, one focal point per beat, motion that means
something). Fix overlaps, clipped text, empty beats, bad crops. Headline
too long → shorten it in `script.json` and re-run `reel.py sherlock data` + `sfx` (no re-voice).

### 5. Render and hand over
```bash
npx hyperframes@0.8.76 render -o renders/<slug>.mp4 && cp renders/<slug>.mp4 ../../output/
```
Write the video description to `output/<slug>.description.md`, detailed and ready to paste: Instagram caption (hook line,
   numbered takeaways, the ending line, comment/save/follow CTAs, 3–5 hashtags (Instagram caps posts at 5) from the brand set,
   under 2,200 characters), chapters with timestamps from `assets/episode.js`, a glossary of every
   term the reel uses, alt text, trending-audio ideas (re-checked with WebSearch), sources, and notes
   (what's illustrative, which assets Jai supplied, the cover frame). Then re-run
   `python3 core/brandkit.py sherlock` so the new cover lands in `brand-kit/covers/`.
Send the MP4 and the description file with SendUserFile. The caption is published as Jai: if
`~/.claude/skills/my-writing-style/SKILL.md` exists, follow it.
### 6. Publish to Instagram (last step, after Jai approves the finished video)

Never post without a clear yes from Jai in chat for this video. Approval of the script or the
description is not approval to post, and approval to post one video never carries to the next.

1. Make sure the description has `## Instagram caption` (≤ 2,200 chars, **3–5 hashtags max**:
   Instagram caps posts at 5 since Dec 2025 and suppresses reach above that) and a
   `## First comment` section, and that `script.json` has `"cover": <seconds>`.
2. Dry run (checks token, video, caption; posts nothing):
   ```bash
   python3 core/publish.py sherlock <slug> --expect sherlock_teaches_ai
   ```
3. Show Jai the dry-run summary (account, cover time, audio name, caption, first comment) and
   ask: "Post it to @sherlock_teaches_ai now? (optionally as a trial reel)". Wait.
4. On a clear yes:
   ```bash
   python3 core/publish.py sherlock <slug> --expect sherlock_teaches_ai --yes          # add --trial only if Jai asks
   ```
   It uploads the MP4 (resumable upload), waits for processing, publishes, posts the first
   comment, and writes `output/<slug>.published.json`. It refuses to post the same slug twice.
5. Send Jai the permalink.

Reach settings the script applies (and why):
- `share_to_feed=true`: the reel shows on the grid and in followers' feeds, not only the Reels tab.
- `thumb_offset` = the `cover` second: the grid thumbnail is the hook headline + key visual,
  not a blank first frame.
- `audio_name` = "<title> · Sherlock Teaches AI": names the original audio so it's findable and
  reusable (every reuse links back).
- Caption: hook in the first line (under ~125 chars, before "more"), the topic's search words
  early (Instagram search reads captions), 3–5 accurate hashtags at the end.
- First comment: sources + a question, to seed comments in the first hour.
- `--trial` (optional): trial reel shown to non-followers first, auto-graduates on performance
  (`SS_PERFORMANCE`). Offer it for experimental topics.
- Not settable by the API (tell Jai to do in the app if wanted): trending audio track, pinning the
  comment, collaborators by username, scheduling. Suggest posting at the audience's peak time.

Token: `INSTAGRAM_ACCESS_TOKEN_SHERLOCK` in the project `.env` (never print it). Tokens last ~60 days;
refresh with `GET https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token=…`
and update `.env`. Posting needs the `instagram_business_content_publish` permission; the first
comment needs `instagram_business_manage_comments` (if missing, the reel still posts and the script
says to add the comment by hand).

## Captions and pronunciation (rule since EP. 02, where the voice said "Jeff" for Jev)

- Captions are the script, word for word. `reel.py data` aligns script words to Whisper's word
  timings (difflib); Whisper's spelling is never shown. Numbers stay as the script writes them.
- Pronunciation lives in `shows/sherlock/voice/PRONOUNCE.json` (show-wide) or `"pronounce"` in
  `script.json` (one episode). Value = respelling (`"GPT-5.6": "GPT five point six"`) or IPA in
  slashes (`"Jev": "/dʒˈɛːvː/"`). IPA entries make the voice run Kokoro directly with those phonemes.
- Decimals are voiced as "point" automatically ("5.6" → "5 point 6"), so Kokoro doesn't read the dot
  as a full stop. `[pause N]` markers are left alone.
- The build prints `CHECK PRONUNCIATION (script -> heard)` for every word the voice got wrong.
  Fix and rebuild until it's clean. To find an IPA that works, try 3–5 variants on the real
  sentences and keep the one Whisper hears correctly (for Jev, plain /dʒˈɛv/ and /dʒˈɛvː/ came out
  "Jeff"; /dʒˈɛːvː/ came out "Jev").
