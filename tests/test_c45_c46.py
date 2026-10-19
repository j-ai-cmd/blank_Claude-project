from tests.test_flags import (COPY, approve, delivery, msg, poster, two_step_contract, two_step_plan, verdict, writer)
from workforce.checks import main as check_main


def test_C45_notes_inside_deliverable_fail(tmp_path):
    bad = tmp_path / "a.md"
    bad.write_text("LAUNCH CAPTION (DRAFT)\n\nMeet the planner.\n\nGAPS\n- app name unknown")
    assert check_main(["deliverable_only", str(bad)]) == 1
    good = tmp_path / "b.md"
    good.write_text("Meet the planner. Your week, in one place.")
    assert check_main(["deliverable_only", str(good)]) == 0
    img = tmp_path / "c.png"
    img.write_bytes(bytes([0x89, 0x50, 0x4E, 0x47, 0xFF, 0xFE]))
    assert check_main(["deliverable_only", str(img)]) == 0


async def test_C46_specialists_see_verifier_findings(make_dispatcher):
    d, runner, _ = make_dispatcher({
        ("sales_lead", "contract"): two_step_contract(), ("sales_lead", "plan"): two_step_plan,
        ("sales_researcher", "execute"): writer(COPY), ("sales_outreach_writer", "execute"): poster({}),
        ("verifier", "verify"): verdict(["FAIL", "PASS"]), ("sales_lead", "deliver"): delivery})
    await d.handle_message(msg("caption and a post please, verify it"))
    await approve(d, "G1")
    execs = [c for c in runner.calls if c["phase"] == "execute"]
    assert "REVISION" not in execs[0]["prompt"] and "REVISION" in execs[2]["prompt"]
    assert "FAIL" in execs[2]["prompt"]


def test_C45_word_count_notes_fail_but_plain_numbers_pass(tmp_path):
    """Live run 2026-10-19: the Sherlock script opened with its own word count."""
    live = tmp_path / "script.md"
    live.write_text("SCRIPT (spoken body, approx. 119 words; counted by splitting on spaces)\n\nObserve. You ask a question.")
    assert check_main(["deliverable_only", str(live)]) == 1
    for bad in ("Meet the planner.\n\nWord count: 4", "Meet the planner. [212 characters]"):
        (tmp_path / "x.md").write_text(bad)
        assert check_main(["deliverable_only", str(tmp_path / "x.md")]) == 1, bad
    ok = tmp_path / "ok.md"
    ok.write_text("SCRIPT\n\nThe window holds 200,000 tokens, roughly 150,000 words of text.\n\nCAPTION\n\nObserve the desk.")
    assert check_main(["deliverable_only", str(ok)]) == 0
