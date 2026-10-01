"""Fixes from the 2026-10 code review: lead context, skill files, standing rules, memory TTLs, citation scope."""
from datetime import timedelta

from workforce.db import MemoryEntry, Task
from workforce.dispatcher import STANDING
from workforce.memory import MemoryStore, now
from workforce.prompts import system_prompt
from workforce.routing import skill_file, skill_files

OWNER = "U_OWNER"


def test_lead_sees_who_does_what_not_how(cfg):
    for show in (None, "striker", "jai"):
        sp = system_prompt(cfg, cfg.employee("studio_lead"), "plan", None, [], show=show)
        assert "football_reel" in sp or show != "striker"          # it knows WHO does WHICH task type
        for how in ("hyperframes", "ui-ux-pro-max", "humanizer", "football-video", "voice_engine", "shows/striker"):
            assert how not in sp, how                              # never the skills or the show's pipeline


def test_skill_read_stays_inside_one_skill():
    assert "references/PROCESS.md" in skill_files("football-video")
    assert skill_file("football-video", "references/PROCESS.md")
    assert skill_file("football-video", "../jai/SKILL.md") is None
    assert skill_file("football-video", "../../../config/org.yaml") is None


def test_standing_rule_only_for_instructions():
    for s in ("never use Hindi words", "Always cite two sources", "from now on use British spelling",
              "make it shorter. Never use emojis", "sherlock reels: always open with a deduction"):
        assert STANDING.search(s), s
    for s in ("jai reel on why you should never skip breakfast", "sherlock video: always-on AI",
              "Make a reel about Never Gonna Give You Up"):
        assert not STANDING.search(s), s


def test_gc_uses_per_layer_ttl_and_cap(cfg, Session):
    ms = MemoryStore(cfg)
    old = now() - timedelta(days=90)
    with Session() as db:
        l3 = MemoryEntry(id="m3", layer="L3", scope_id="sales_researcher", kind="feedback", content="a",
                         source="t", author="x", status="active", last_used_at=old, created_at=old)
        l1 = MemoryEntry(id="m1", layer="L1", scope_id="sales", kind="feedback", content="b",
                         source="t", author="x", status="active", last_used_at=old, created_at=old)
        rule = MemoryEntry(id="mr", layer="L1", scope_id="sales", kind="preference", content="c", source="t",
                           author="owner", status="active", standing=True, last_used_at=old, created_at=old,
                           expires_at=now() + timedelta(days=90))
        db.add_all([l3, l1, rule])
        db.flush()
        ms.gc(db)
        assert l3.status == "active"       # L3 lives 180 days unused, not 60
        assert l1.status == "archived"     # L1 playbook archived after 60 days unused
        assert rule.status == "active"     # a standing rule lives until its own expiry


def test_citations_are_scoped_to_the_plan_task(make_dispatcher):
    d, _, _ = make_dispatcher({})
    with d.Session() as db:
        db.add(Task(id="tc", department="sales", requested_by=OWNER, original_request="x"))
        db.commit()
    d._add_source("tc", "urls", ["https://a.example"], "T1")
    assert d._unobserved_citations("tc", [{"source": "https://a.example"}], "T1") == []
    assert d._unobserved_citations("tc", [{"source": "https://a.example"}], "T2") == ["https://a.example"]
    assert d._unobserved_citations("tc", [{"source": "https://a.example"}]) == []   # Proof sees the whole task
    assert d._unobserved_citations("tc", [{"source": "handoff:T2"}], "T2") == []
