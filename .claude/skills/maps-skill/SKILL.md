---
name: maps-skill
description: Scans every installed skill, matches the task to the closest ones, shows the candidates with a recommendation, and runs the approved skill. Use when Jai says "match skill", "map skill", "maps skill", "which skill should I use", or "pick the right skill for this".
---

# Maps skill

Match a task to the best installed skill, get Jai's approval, then run it.

## Steps

1. **Get the task.** Take it from the trigger message ("match skill, it's a motion graphic for a football edit"). If none is given, ask one short question: what is the task?
2. **Scan all skills.**
   - Run `python ~/.claude/skills/maps-skill/scripts/list_skills.py` for name + description of every skill in `~/.claude/skills`.
   - Also read the skills list in the system prompt (plugin skills like `ui-craft:*`, `marketing:*` live there, not on disk).
   - For any close candidate, open its `SKILL.md` and read the body. The description alone can hide a mismatch (speed, style, format, platform).
3. **Shortlist 1-4 candidates.** Same domain and plausible for the task. Skip skills that only share a keyword.
4. **Compare on task details.** Check each candidate against: output type, style or pace, platform (Reels, web, print), inputs Jai has, and hard rules in the skill (e.g. "Jai supplies every asset").
5. **Present the match.** Use this format, nothing longer:

   ```
   Task: <one line>

   1. <skill-name> - <what it does, one line>
   2. <skill-name> - <what it does, one line>

   Recommend: #<n> <skill-name>
   Why: <2 short reasons tied to the task>
   Trade-off: <what the other option would do better, one line>

   Approve? (yes / pick 1 / pick 2 / none)
   ```

6. **Wait.** Do nothing else until Jai answers. Approval must come in chat.
7. **Run.** On approval, invoke the chosen skill with the Skill tool, passing the original task as args. Follow that skill from there.

## Rules

- One clear winner: still show it and ask. Never auto-run.
- Only one plausible skill: show it, say no alternative fits, ask.
- Nothing fits: say so. Offer to build one with `write-a-skill`. Do not force a weak match.
- Tie: recommend one anyway and name the deciding factor.
- Jai names a skill directly ("use football-video"): skip matching, invoke it.
- Never invent skills. Only list ones found in the scan.
- Approval covers this task only. Match again for the next task.

## Example

Jai: "match skill - motion graphic design for a football edit"

Candidates found: a slow agency-style motion graphics skill and a fast-paced motion graphics skill.
Football edits are quick cuts on beat, so recommend the fast-paced one. Trade-off: the slow skill fits a premium brand film better. Jai approves, the fast-paced skill runs.
