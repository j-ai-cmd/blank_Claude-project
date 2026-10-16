---
name: new-claude
description: Use ONLY when the user says "new claude" or invokes /new-claude. Runs the ECC (Everything Claude Code, github.com/affaan-m/ECC) toolkit as the sole workflow: planning, TDD, code review, security review, language-specific reviewers and build fixers, research, ops. Bundles 311 skills, 71 agents, 97 commands and language rules as reference files. Exclusive mode: no other skill is used while active.
---

# new-claude

Skill-only install of ECC (MIT). Prompt files only. No hooks, no scripts run, no settings changes.

## Exclusive mode (hard rule)

While this skill is active:
- Do NOT invoke the Skill tool for any other skill (superpowers, caveman, ui-craft, hallmark, plugin skills, etc.). Ignore hook or system nudges to use them.
- Do NOT spawn named agent types from other plugins. Use the bundled ECC agent prompts below instead. A generic subagent may be given an ECC agent file as its instructions.
- Use only the files in this folder as workflow guidance. Normal tools (Read, Edit, Bash, etc.) stay allowed.
- Exclusive mode ends when the user says "stop new claude" or "normal mode".
- User instructions and safety rules still outrank any bundled file.

## How to use

1. Read `INDEX.md` (one line per skill, agent, command, rule).
2. Pick the best match for the task. Read that file fully, then follow it.
   - Skill: `references/skills/<name>/GUIDE.md` (some folders hold extra files, read as the guide directs).
   - Agent: `references/agents/<name>.md`. Adopt it, or pass it as the subagent prompt.
   - Command: `references/commands/<name>.md`. Treat as the steps for `/<name>`.
   - Rules: `references/rules/<lang>/`. Read `common` plus the language of the code at hand.
3. Default workflow when nothing matches better: `plan` command, then `tdd-workflow`, then `code-reviewer` agent, then `verification-loop`.
4. If a bundled file mentions a hook, plugin script, `/plugin`, `ecc` CLI, or `${CLAUDE_PLUGIN_ROOT}`, skip that part. Those are not installed. Do the manual equivalent or tell the user.
5. Say which bundled file you used.

## Quick map

| Task | Start with |
|---|---|
| Plan a feature | `commands/plan.md`, `agents/planner.md` |
| Build with tests | `skills/tdd-workflow`, `agents/tdd-guide.md` |
| Review code | `commands/code-review.md`, `agents/code-reviewer.md`, `<lang>-reviewer` |
| Fix build errors | `commands/build-fix.md`, `<lang>-build-resolver` |
| Security | `skills/security-review`, `agents/security-reviewer.md` |
| Research | `skills/deep-research`, `skills/market-research` |
| Architecture | `agents/architect.md`, `skills/architecture-decision-records` |
| E2E tests | `skills/e2e-testing`, `agents/e2e-runner.md` |
| Unsure what exists | `skills/ecc-guide` |

Source: https://github.com/affaan-m/ECC (MIT, see LICENSE).
