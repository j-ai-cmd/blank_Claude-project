"""v3: one engineer per project lane, Power Automate check, 9am inbox routine (Scan updates the pipeline),
Spark (ideas) across shows, Apply (CV + cover letters)."""
import json
from datetime import datetime, timezone


from tests.test_flags import OWNER, msg, ref_of, task
from workforce.checks import main as check_main
from workforce.db import PipelineItem, Task
from workforce.dispatcher import validate_contract
from workforce.prompts import show_allowed

BASE = {"objective": "x", "size": "M", "acceptance_criteria": [{"id": "1", "text": "t", "check": "automatic"}]}


# ------------------------------------------------------------------ company vs personal
def test_company_lane_detection(cfg):
    assert cfg.shows_named("fix the company api bug") == ["company"]
    assert cfg.shows_named("lane: company — add a feature") == ["company"]
    assert cfg.shows_named("pitch this company for a role") == []          # a sales request isn't the lane
    assert cfg.shows_named("fix the bug in my portfolio site") == []


def test_each_project_has_its_own_engineer(cfg, runtimes):
    forge = cfg.employee("eng_lead")
    co = [{"id": "D1", "assignee": "eng_backend_company", "task_type": "company_fix_bug"}]
    office = [{"id": "D1", "assignee": "eng_office_app", "task_type": "office_fix_bug"}]
    assert not validate_contract({**BASE, "deliverables": co}, forge, cfg, show="company")
    assert not validate_contract({**BASE, "deliverables": office}, forge, cfg, show="officeapp")
    assert any("only on the 'company'" in p for p in validate_contract({**BASE, "deliverables": co}, forge, cfg, show="officeapp"))
    assert any("only on the 'officeapp'" in p for p in validate_contract({**BASE, "deliverables": office}, forge, cfg, show="company"))
    assert any("names no show" in p for p in validate_contract({**BASE, "deliverables": office}, forge, cfg, show=None))
    assert cfg.shows_named("fix the live office login bug") == ["officeapp"]
    assert not show_allowed(cfg, cfg.employee("sales_ideas"), "company")


def test_project_memory_never_crosses(cfg, Session):
    from workforce.memory import MemoryStore
    ms = MemoryStore(cfg)
    byte_co, loom = cfg.employee("eng_backend_company"), cfg.employee("eng_office_app")
    with Session() as db:
        t = Task(id="tc", department="engineering", requested_by=OWNER, original_request="x", show="company")
        db.add(t)
        db.flush()
        m = ms.submit_candidate(db, byte_co, t, "Company repo uses pnpm", layer="L3")
        rule = ms.submit_candidate(db, byte_co, t, "Company PRs need two reviewers", layer="L1")
        m.status = rule.status = "active"
        db.flush()
        assert m.scope_id == "eng_backend_company" and rule.scope_id == "show:company"
        seen = {x.id for x in ms.read(db, loom, "", show="officeapp")}
        assert m.id not in seen and rule.id not in seen                         # the office app never sees company work
        assert {m.id, rule.id} <= {x.id for x in ms.read(db, byte_co, "")}


# ------------------------------------------------------------------ Make vs Power Automate
def test_platform_only_checks(tmp_path):
    make = {"name": "Leads", "flow": [{"id": 1, "module": "google-sheets:addRow"}, {"id": 2, "module": "slack:createMessage"}]}
    pa = {"definition": {"$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
                         "triggers": {"manual": {"type": "Request"}}, "actions": {"Send": {"type": "OpenApiConnection"}}}}
    f = tmp_path / "x.json"
    f.write_text(json.dumps(make))
    assert check_main(["platform_only", str(f), "make"]) == 0
    assert check_main(["platform_only", str(f), "power_automate"]) == 1
    f.write_text(json.dumps(pa))
    assert check_main(["platform_only", str(f), "power_automate"]) == 0
    assert check_main(["platform_only", str(f), "make"]) == 1
    f.write_text(json.dumps({**make, "notes": "then trigger the Power Automate flow"}))   # mixed in: rejected
    assert check_main(["platform_only", str(f), "make"]) == 1


def test_power_automate_route_is_checked_for_its_platform(cfg, runtimes):
    from workforce.routing import resolve
    assert "power_automate_only" in resolve(cfg, "eng_backend_company", "power_automate_flow").checks


# ------------------------------------------------------------------ pipeline + inbox routine
class FakeInbox:
    def __init__(self, mails):
        self.mails = {m["id"]: m for m in mails}

    def configured(self):
        return True

    def list_recent(self, hours):
        return [{k: m[k] for k in ("id", "from", "subject", "date")} for m in self.mails.values()]

    def open(self, i):
        return self.mails[i]


async def test_inbox_routine_opens_every_email_and_updates_pipeline(make_dispatcher, cfg):
    seen = {}

    async def scan(tools, ctx):
        seen["n"] = seen.get("n", 0) + 1
        rows = json.loads((await tools["email_list"].handler({"hours": 24}))["content"][0]["text"])
        for r in rows[:1] if seen["n"] == 1 else rows:        # first attempt lazily skips the newsletter
            await tools["email_open"].handler({"id": r["id"]})
        pipe = await tools["pipeline_read"].handler({"query": "acme"})   # Scan marks the reply itself (Track is gone)
        pid = json.loads(pipe["content"][0]["text"].split("\n", 1)[1].rsplit("\n", 1)[0])[0]["id"]
        await tools["pipeline_update"].handler({"id": pid, "status": "replied_positive", "note": "wants a call"})
        ref = ref_of(await tools["workspace_write"].handler({"name": "digest.md", "content": "Positive reply from Acme."}))
        await tools["submit_return"].handler({"status": "done", "outputs": [ref], "confidence": 0.9,
                                              "self_check": [{"criterion_id": "1", "result": "met", "evidence": "all opened"}]})

    d, runner, _ = make_dispatcher({("ops_inbox_scanner", "execute"): scan})
    d.email_reader = FakeInbox([
        {"id": "1", "from": "ceo@acme.test", "subject": "Re: video editing", "date": "", "body": "Love it, let's talk"},
        {"id": "2", "from": "news@x.test", "subject": "Newsletter", "date": "", "body": "sale"}])
    with d.Session() as db:
        db.add(PipelineItem(id="pl_1", kind="pitch", to="ceo@acme.test", subject="Video editing for Acme", body="Hi"))
        db.commit()
    at_9 = datetime(2026, 9, 30, 3, 31, tzinfo=timezone.utc)                  # 09:01 in Asia/Kolkata
    assert d.due_routines(datetime(2026, 9, 30, 3, 0, tzinfo=timezone.utc)) == []   # 08:30 local: not yet
    assert d.due_routines(at_9) == ["inbox_scan"]
    tid = await d.run_routine("inbox_scan", at_9)
    assert await d.run_routine("inbox_scan", at_9) is None                    # once a day
    with d.Session() as db:
        t = db.get(Task, tid)
        row = db.get(PipelineItem, "pl_1")
    # first pass skipped email 2 -> inbox_coverage failed -> retried; second pass opened both
    execs = [c["employee"] for c in runner.calls if c["phase"] == "execute"]
    assert execs.count("ops_inbox_scanner") >= 2 and t.status == "DELIVERED", (execs, t.status)
    assert row.status == "replied_positive" and t.requested_by == "routine:inbox_scan"
    scanner = cfg.employee("ops_inbox_scanner")
    assert "web.fetch" not in scanner.tools and "email.send_external" not in scanner.tools


async def test_inbox_without_connector_asks_owner(make_dispatcher):
    async def scan(tools, ctx):
        r = await tools["email_list"].handler({})
        assert r.get("is_error") and "IMAP" in r["content"][0]["text"]
        await tools["submit_return"].handler({"status": "blocked", "outputs": [], "confidence": 0.1, "self_check": [],
                                              "open_questions": ["Add the email connector (IMAP)"]})
    d, _, slack = make_dispatcher({("ops_inbox_scanner", "execute"): scan})
    await d.run_routine("inbox_scan", datetime(2026, 9, 30, 4, 0, tzinfo=timezone.utc))
    assert task(d).status == "ESCALATED" and any("IMAP" in m.get("text", "") for m in slack.sent)


# ------------------------------------------------------------------ cover letters + rabbit holes
def test_apply_is_private_and_works_from_the_job_you_give(cfg, runtimes):
    from workforce.dispatcher import validate_plan
    apply_ = cfg.employee("sales_applications")
    assert {"owner_profile.read", "pipeline.read"} <= set(apply_.tools) and "web.fetch" not in apply_.tools
    sam = cfg.employee("sales_lead")
    contract = {**BASE, "deliverables": [{"id": "D1", "assignee": "sales_applications", "task_type": "cover_letter"}]}
    _, prob = validate_plan(cfg, sam, "t", contract, 1, "M", [
        {"deliverable": "D1", "to": "sales_applications", "task_type": "cover_letter", "objective": "o", "criteria": ["1"]}], "", False)
    assert prob == []                                    # the job you paste is enough; Scout is optional


def test_spark_serves_shows_but_not_projects(cfg):
    spark = cfg.employee("sales_ideas")
    assert show_allowed(cfg, spark, "jai") and show_allowed(cfg, spark, "sherlock") and show_allowed(cfg, spark, "striker")
    assert not show_allowed(cfg, spark, "company") and not show_allowed(cfg, spark, "officeapp")


# ------------------------------------------------------------------ hiring + restart
async def test_hire_goes_live_only_by_your_command_and_starts_on_probation(tmp_path, Session):
    import shutil

    import yaml

    from workforce.agents import FakeRunner
    from workforce.config import ROOT, Config
    from workforce.dispatcher import Dispatcher
    from workforce.slack import SlackClient
    shutil.copytree(ROOT / "config", tmp_path / "config")
    shutil.copytree(ROOT / "context", tmp_path / "context")
    (tmp_path / "proposals").mkdir()
    spec = {"id": "studio_podcast_editor", "name": "Echo", "department": "studio", "kind": "specialist",
            "does": ["edit podcasts"], "does_not": ["publish"], "fire_when": "you ask for a podcast edit",
            "tools": ["workspace.read", "workspace.write", "submit_return"], "max_tier": "R1",
            "personality": {"voice": ["calm"]}, "routes": [{"task_type": "podcast_edit", "run": [], "checks": ["spellcheck"]}],
            "context": "Edits your podcast.", "probation_tasks": ["a", "b", "c"], "pitch": "Meet Echo."}
    (tmp_path / "proposals" / "p1.yaml").write_text(yaml.safe_dump(spec))
    d = Dispatcher(Config(tmp_path / "config"), Session, FakeRunner(), SlackClient(token=""))
    assert "studio_podcast_editor" not in d.cfg.employees
    assert d.command("U_STRANGER", "hire p1.yaml") == "Only the owner can run commands."
    out = d.command(OWNER, "hire p1.yaml")
    assert out.startswith("Hired Echo") and "1. a" in out
    e = d.cfg.employee("studio_podcast_editor")
    assert e.probation and e.kind == "specialist" and "podcast_edit" in d.cfg.routes(e.id)
    assert (tmp_path / "context" / "studio_podcast_editor.md").exists()
    assert "studio_podcast_editor" not in (tmp_path / "config" / "org.yaml").read_text()   # org.yaml untouched
    assert d.command(OWNER, "end-probation studio_podcast_editor").endswith("off probation.")
    assert not d.cfg.employee("studio_podcast_editor").probation


def test_restart_resumes_interrupted_rounds_once(make_dispatcher):
    d, _, _ = make_dispatcher({})
    with d.Session() as db:
        db.add(Task(id="r1", department="sales", requested_by=OWNER, original_request="x", contract_version=1,
                    status="IN_PROGRESS", plan=[{"to": "sales_writer", "task_type": "post_copy"}], contract={"objective": "o"}))
        db.commit()
    assert d.sweep(boot=True).get("resume") == ["r1"]
    with d.Session() as db:
        assert db.get(Task, "r1").status == "IN_PROGRESS"
    assert not d.sweep(boot=True).get("resume")                            # a second crash -> escalate to you
    with d.Session() as db:
        assert db.get(Task, "r1").status == "ESCALATED"


async def test_claude_connection_failure_is_not_blamed_on_your_wording(make_dispatcher):
    from workforce.agents import RunResult

    d, runner, slack = make_dispatcher({})

    async def broken(**kw):
        return RunResult(is_error=True, text="Authentication error · This may be a temporary network issue")
    runner.run = broken
    await d.handle_message(msg("write a caption about sleep"))
    texts = " ".join(m.get("text", "") for m in slack.sent)
    assert "Couldn't reach Claude" in texts and "rephrase" not in texts
