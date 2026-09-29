from tests.test_flags import (COPY, OWNER, approve, delivery, msg, poster, task, two_step_contract, two_step_plan,
                              verdict, writer)
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
        ("mkt_lead", "contract"): two_step_contract(), ("mkt_lead", "plan"): two_step_plan,
        ("mkt_copywriter", "execute"): writer(COPY), ("mkt_social_manager", "execute"): poster({}),
        ("verifier", "verify"): verdict(["FAIL", "PASS"]), ("mkt_lead", "deliver"): delivery})
    await d.handle_message(msg("caption and a post please"))
    await approve(d, "G1")
    execs = [c for c in runner.calls if c["phase"] == "execute"]
    assert "REVISION" not in execs[0]["prompt"] and "REVISION" in execs[2]["prompt"]
    assert "FAIL" in execs[2]["prompt"]
