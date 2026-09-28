#!/usr/bin/env python3
"""Print name + description for every skill under ~/.claude/skills (and any extra dirs passed as args)."""
import re, sys, pathlib

roots = [pathlib.Path.home() / ".claude" / "skills"] + [pathlib.Path(a).expanduser() for a in sys.argv[1:]]
for root in roots:
    for f in sorted(root.glob("*/SKILL.md")):
        text = f.read_text(errors="ignore")
        m = re.match(r"---\n(.*?)\n---", text, re.S)
        if not m:
            continue
        fm = m.group(1)
        name = re.search(r"^name:\s*(.+)$", fm, re.M)
        desc = re.search(r"^description:\s*(.+?)(?=\n\w[\w-]*:|\Z)", fm, re.S | re.M)
        d = " ".join(desc.group(1).split()).strip("\"'>|- ") if desc else "(no description)"
        print(f"- {name.group(1).strip() if name else f.parent.name}: {d[:400]}")
