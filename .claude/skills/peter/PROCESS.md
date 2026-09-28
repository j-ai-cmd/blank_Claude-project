# Peter: full process detail

## Where this comes from

brainrotshorts.com's Reddit story generator (checked 2026-09-25) runs: find or write the story
(paste, or premise → AI writes hook, story, punchline) → pick a character voice → pick a gameplay
background → pick a caption style and generate (voice, caption timing, compositing) → export a 9:16
1080×1920 MP4 and post. Extras it sells: 30+ caption styles, multi-character (OP + commenters),
comment reading, custom backgrounds. This skill does the same steps with Jai's approval gate, his
locked style, and only his assets.

## script.json

Shape: `shows/brainrot/template/script.json`. Keys:

| Key | Meaning |
| --- | --- |
| `post` | `subreddit`, `title`, `age`, `upvotes`, `comments` (real posts only; omit counts for premises) |
| `part` | Part number for multi-part stories, else `null` |
| `caption_style` | `pop` or `highlight` |
| `bg_start` | Seconds into the gameplay clip to start from |
| `assets` | `bg` (with `"from"` = library clip name), optional `music` (with `"from"`) |
| `beats[].say` | Spoken line. `*word*` = emphasis pill |
| `beats[].twist` | `true` → bass hit, Peter jumps, screen shakes |
| `beats[].comment` | `{ user, text, upvotes }` → comment card during the beat |
| `beats[].outro` | Text for the end card, e.g. `"FOLLOW FOR PART 2"` |

## Approval message

```
PETER · "AITA for uninviting my sister…" · PART 1 of 2 · ~36s · 108 words
r/AmItheAsshole · 24.1k ▲ · 3.2k 💬 · source: <link>
1. TITLE     "AITA for uninviting my sister after she ate the top tier of my wedding cake?"
2. SETUP     "Hey Lois, listen to this. The night before the wedding…"
3. TWIST ⚡  "But here's the twist. The bride's own *mom* told her to do it."
4. COMMENT   [card: u/cakefacts · 12.4k ▲] "NTA. Your mom owes you a cake."
5. OUTRO     [FOLLOW FOR PART 2] "Part two tomorrow. Holy crap."
Voice: Peter (B) · Clip: library/bg/parkour-02.mp4 @ 0:40 · Captions: pop · Music: none
Assets needed: none
Approve?
```
