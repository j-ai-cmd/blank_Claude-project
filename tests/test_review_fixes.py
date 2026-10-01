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
        l3 = MemoryEntry(id="m3", layer="L3", scope_id="sales_ideas", kind="feedback", content="a",
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


def test_unrelated_memory_stays_out_of_the_prompt(cfg, Session):
    ms = MemoryStore(cfg)
    intel = cfg.employee("sales_ideas")
    with Session() as db:
        db.add_all([MemoryEntry(id="ma", layer="L3", scope_id="sales_ideas", kind="feedback", source="t",
                                author="x", status="active", content="Acme prefers short briefs"),
                    MemoryEntry(id="mb", layer="L3", scope_id="sales_ideas", kind="feedback", source="t",
                                author="x", status="active", content="Football stats need two sources"),
                    MemoryEntry(id="mc", layer="L1", scope_id="hq", kind="preference", source="owner", author="owner",
                                status="active", standing=True, content="British spelling")])
        db.flush()
        got = {m.id for m in ms.read(db, intel, "brief on Acme")}
    assert got == {"ma", "mc"}   # related memory + standing rules only


def test_token_diet_prompts(cfg):
    from workforce.routing import resolve
    hook = system_prompt(cfg, cfg.employee("sales_writer"), "execute", resolve(cfg, "sales_writer", "pitch_email"))
    assert '<skill_brief name="humanizer">' in hook and "### 1. Not X but Y" not in hook   # brief, not 28k chars
    assert "name: humanizer" not in hook                                                     # no frontmatter
    proof = system_prompt(cfg, cfg.employee("fact_checker"), "factcheck")
    assert "## D. Truth" in proof and "## E. Actions" not in proof and "# Your training" not in proof
    assert "Recruiting" not in cfg.constitution


def test_show_task_memory_skips_dept_playbook_and_caps_standing(cfg, Session):
    ms = MemoryStore(cfg)
    prod = cfg.employee("studio_builder")
    with Session() as db:
        rows = [MemoryEntry(id="dept", layer="L1", scope_id="studio", kind="preference", source="o", author="owner",
                            status="active", standing=True, content="always use Inter font")]
        rows += [MemoryEntry(id=f"s{i}", layer="L1", scope_id="show:jai", kind="preference", source="o", author="owner",
                             status="active", standing=True, content=f"jai rule number {i}") for i in range(8)]
        db.add_all(rows)
        db.flush()
        got = {m.id for m in ms.read(db, prod, "reel", show="jai")}
    assert "dept" not in got                        # a Studio rule never overrides the Jai show bible
    assert len(got) == 5                            # standing rules capped per prompt


def test_promotion_updates_instead_of_piling_up(cfg, Session):
    """Mem0-style: a near-copy is dropped (NOOP), an overlapping memory replaces the old one (UPDATE)."""
    ms = MemoryStore(cfg)
    voice = cfg.employee("sales_writer")
    with Session() as db:
        t = Task(id="tu", department="sales", requested_by=OWNER, original_request="x", status="ACCEPTED")
        db.add(t)
        db.flush()
        first = ms.submit_candidate(db, voice, t, "Owner signs emails with just his first name")
        db.flush()
        assert ms.promote(db, first.id, t, owner_ticked=True).status == "active"
        copy = ms.submit_candidate(db, voice, t, "Owner signs emails with just his first name.")
        db.flush()
        assert ms.promote(db, copy.id, t, owner_ticked=True).status == "rejected"          # NOOP
        newer = ms.submit_candidate(db, voice, t, "Owner signs emails with his first name and a dash")
        db.flush()
        assert ms.promote(db, newer.id, t, owner_ticked=True).status == "active"           # UPDATE
        assert db.get(MemoryEntry, first.id).status == "archived"
