"""Org v3 step 4: skill_read (read-only, route-scoped) and the routes for the new skills."""
from workforce.config import SKILLS_DIR
from workforce.db import Task
from workforce.prompts import skills_block
from workforce.routing import resolve


def _task(d, tid="sk1", dept="engineering", show=None):
    with d.Session() as db:
        db.add(Task(id=tid, department=dept, requested_by="U_OWNER", original_request="x", show=show, contract_version=1))
        db.commit()
    return tid


def _text(res):
    return res["content"][0]["text"]


async def test_skill_read_opens_route_skill_references_through_policy(make_dispatcher, cfg):
    d, _, _ = make_dispatcher({})
    tid = _task(d)
    emp = cfg.employee("eng_qa")
    route = resolve(cfg, "eng_qa", "security_review")
    tool = d._guard(emp, tid, d._skill_read_tool(route))
    res = await tool.handler({"skill": "new-claude", "path": "references/agents/security-reviewer.md"})
    assert not res.get("is_error")
    assert _text(res) == (SKILLS_DIR / "new-claude/references/agents/security-reviewer.md").read_text()[:50_000]
    listing = await tool.handler({"skill": "new-claude", "path": ""})
    assert "INDEX.md" in _text(listing) and "references/" in _text(listing)


async def test_skill_read_refuses_other_skills_and_escapes(make_dispatcher, cfg):
    d, _, _ = make_dispatcher({})
    tid = _task(d)
    tool = d._guard(cfg.employee("eng_qa"), tid, d._skill_read_tool(resolve(cfg, "eng_qa", "security_review")))
    assert (await tool.handler({"skill": "sherlock", "path": "SKILL.md"})).get("is_error")      # not this route's skill
    for path in ("../sherlock/SKILL.md", "../../config/permissions.yaml", "/etc/passwd"):
        assert (await tool.handler({"skill": "new-claude", "path": path})).get("is_error"), path


async def test_skill_read_denied_by_policy_without_the_allowlist_entry(make_dispatcher, cfg):
    d, _, _ = make_dispatcher({})
    tid = _task(d, dept="sales")
    letter = cfg.employee("sales_cover_letter_writer")         # private-data writer: no skill.read in its tools
    assert "skill.read" not in letter.tools
    tool = d._guard(letter, tid, d._skill_read_tool(resolve(cfg, "sales_cover_letter_writer", "cover_letter")))
    res = await tool.handler({"skill": "humanizer", "path": "SKILL.md"})
    assert res.get("is_error") and "denied by policy" in _text(res)


def test_new_routes_and_prompt_mentions_skill_read(cfg):
    assert resolve(cfg, "sales_rabbit_hole_finder", "sherlock_topic_pitch").skills == ["sherlock-ideas"]
    assert resolve(cfg, "eng_qa", "security_review").skills == ["new-claude"]
    assert "skill_read" in skills_block(resolve(cfg, "eng_qa", "security_review"))
    assert "2d only" in str(cfg.adapter("sherlock")["character"])
    assert not (SKILLS_DIR / "jai-insta").exists()               # duplicate of jai, removed
