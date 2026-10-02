# Football — BUILD slice (Football-Build only)

You build and render the approved football storyboard from the owner's photos and recorded voiceover. Nothing else:
never change his words, stats or the storyboard's design; never write captions; never synthesize a voice; never post.

## Steps (all commands through `sandbox_exec`, inside your task project)
1. New HyperFrames project; copy this skill's `template/` in (`skill_read football-video references/PROCESS.md`,
   section "6. Build", has the exact commands). Stage his files.
2. Cut out and crop every photo (untrimmed alpha margins make props tiny).
3. Transcribe his voiceover for timing only: captions show his script word for word; put every mis-heard name in
   `FIX` and diff caption text against the script — any difference is a bug.
4. Fill `SCENES` / `BEATS` from the transcript and the storyboard; write each scene's treatment; carve music under VO.
5. `npx hyperframes check` → 0 errors. Contact sheet of every beat: fix overlaps, covered faces, clipped accents,
   dead frames, captions touching content. Known traps: `skill_read football-video references/GOTCHAS.md`.
6. Render the draft + the captions-only test render; run `tests/test_episode.py` until it passes.
7. `hyperframes-core` is loaded; read other HyperFrames skills on demand with `skill_read` — only the file you need.

## Output
The rendered MP4 — FIRST and only deliverable.
