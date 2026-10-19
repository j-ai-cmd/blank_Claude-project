"""Org v3 steps 5–6: current model IDs, effort per phase/route, retry ladder, overload fallback, advisor off."""
from tests.test_flow import SLOP_COPY, contract, msg, plan, writer
from workforce.config import HIRE_DEFAULTS, Route
from workforce.routing import resolve


def test_no_haiku_4_5_left_and_t2_roles_on_sonnet(cfg):
    models = {e.id: e.model for e in cfg.employees.values()}
    assert "claude-haiku-4-5" not in models.values() and HIRE_DEFAULTS["model"] == "claude-haiku-5-5"
    for eid in ("sales_outreach_writer", "sales_cover_letter_writer", "sales_application_writer", "sales_proposal_writer",
                "show_jai_writer", "talent_architect", "eng_backend", "eng_backend_company", "eng_frontend", "eng_qa"):
        assert models[eid] == "claude-sonnet-5-5", eid
    assert models["sales_researcher"] == models["chief_of_staff"] == "claude-haiku-5-5"


def test_ladder_climbs_only_on_retries(cfg):
    haiku, sonnet = cfg.employee("sales_researcher"), cfg.employee("sales_lead")
    assert cfg.model_for(haiku, 1, "S") == "claude-haiku-5-5"
    assert cfg.model_for(haiku, 2, "S") == "claude-sonnet-5-5"
    assert cfg.model_for(haiku, 3, "M") == "claude-sonnet-5-5"
    assert cfg.model_for(haiku, 3, "L") == "claude-opus-5-5"          # two rungs only on an L task
    assert cfg.model_for(sonnet, 3, "L") == "claude-opus-5-5"         # capped at the top rung
    assert cfg.fallback_for("claude-haiku-5-5") == "claude-sonnet-5-5"
    assert cfg.fallback_for("claude-opus-5-5") == "claude-sonnet-5-5"


def test_effort_by_kind_phase_and_route_override(cfg):
    lead = cfg.employee("sales_lead")
    assert cfg.effort_for(lead, "contract") == "low" and cfg.effort_for(lead, "deliver") == "medium"
    assert cfg.effort_for(cfg.employee("verifier"), "verify") == "medium"
    spec = cfg.employee("sales_researcher")
    assert cfg.effort_for(spec, "execute", resolve(cfg, "sales_researcher", "topic_research")) == "medium"
    assert cfg.effort_for(spec, "execute", Route("x", (), (), effort="high")) == "high"


def test_advisor_off_until_enabled(cfg, monkeypatch):
    assert cfg.advisor_for("implement") is None
    monkeypatch.setitem(cfg.org["models"], "advisor", {**cfg.org["models"]["advisor"], "enabled": True})
    assert cfg.advisor_for("implement") == "claude-opus-5-5"
    assert cfg.advisor_for("caption") is None                          # only the listed hard routes


async def test_runner_gets_effort_fallback_and_retry_climbs(make_dispatcher):
    d, runner, _ = make_dispatcher({
        ("sales_lead", "contract"): contract("S"), ("sales_lead", "plan"): plan(),
        ("sales_script_writer", "execute"): writer([SLOP_COPY])})        # fails no_ai_tells every attempt
    await d.handle_message(msg("write a launch caption"))
    lead = next(c for c in runner.calls if c["phase"] == "contract")
    assert (lead["model"], lead["effort"], lead["advisor"]) == ("claude-sonnet-5-5", "low", None)
    runs = [c for c in runner.calls if c["phase"] == "execute"]
    assert [c["model"] for c in runs] == ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-sonnet-5-5"]
    assert runs[0]["fallback_model"] == "claude-sonnet-5-5" and runs[0]["effort"] == "medium"
