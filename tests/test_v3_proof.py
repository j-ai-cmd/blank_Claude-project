"""Proof cost: a revision round re-checks only claims that changed (live run 2026-10-19: 3 full Sonnet fact checks)."""
from tests.test_flags import msg, task, writer
from tests.test_v2 import _one_step

WEEKDAYS = "Support is open on weekdays"


async def test_revision_round_carries_verified_claims_and_checks_only_the_rest(make_dispatcher):
    prompts = []

    async def proof(tools, ctx):
        prompts.append(ctx["prompt"])
        if len(prompts) == 1:
            claims = [{"quote": "Plans start at $49", "claim": "price", "verdict": "FALSE", "sources": ["owner:request"], "evidence": "request says $39"},
                      {"quote": WEEKDAYS, "claim": "hours", "verdict": "TRUE", "sources": ["owner:request"], "evidence": "in the request"}]
        else:   # only the changed claim is submitted; the weekday claim is carried over
            claims = [{"quote": "Plans start at $39", "claim": "price", "verdict": "TRUE", "sources": ["owner:request"], "evidence": "matches"}]
        r = await tools["submit_factcheck"].handler({"claims": claims})
        assert not r.get("is_error"), r

    texts = iter([f"Plans start at $49 a month. {WEEKDAYS}.", f"Plans start at $39 a month. {WEEKDAYS}."])

    async def script(tools, ctx):
        await writer(next(texts))(tools, ctx)
    d, _, _ = make_dispatcher(_one_step("sales_script_writer", "caption", "", extra_scripts={
        ("fact_checker", "factcheck"): proof, ("sales_script_writer", "execute"): script}))
    await d.handle_message(msg("caption: plans start at $39 a month, support is open on weekdays"))
    t = task(d)
    assert t.status == "DELIVERED" and t.revisions == 1
    assert "Already verified" not in prompts[0]
    assert "Already verified" in prompts[1] and WEEKDAYS in prompts[1] and "$49" not in prompts[1].split("Already verified")[1]
    stored = {c["quote"]: c for c in t.contract["_factcheck"]}
    assert set(stored) == {"Plans start at $39", WEEKDAYS}
    assert stored[WEEKDAYS]["evidence"].startswith("carried from an earlier round")


async def test_changed_quote_is_not_carried(make_dispatcher):
    prompts = []

    async def proof(tools, ctx):
        prompts.append(ctx["prompt"])
        verdict = "UNSOURCED" if len(prompts) == 1 else "TRUE"
        quote = "Plans start at $49" if len(prompts) == 1 else "Plans start at $39"
        await tools["submit_factcheck"].handler({"claims": [
            {"quote": quote, "claim": "price", "verdict": verdict, "sources": ["owner:request"], "evidence": "x"}]})
    texts = iter(["Plans start at $49 a month.", "Plans start at $39 a month."])

    async def script(tools, ctx):
        await writer(next(texts))(tools, ctx)
    d, _, _ = make_dispatcher(_one_step("sales_script_writer", "caption", "", extra_scripts={
        ("fact_checker", "factcheck"): proof, ("sales_script_writer", "execute"): script}))
    await d.handle_message(msg("caption: plans start at $39 a month"))
    assert task(d).status == "DELIVERED"
    assert "Already verified" not in prompts[1]          # nothing TRUE survived word for word, so nothing is carried
