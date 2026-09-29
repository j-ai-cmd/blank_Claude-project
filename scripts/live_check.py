#!/usr/bin/env python3
"""Live end-to-end checks with REAL Claude employees (spends plan credit, ~$0.2–0.6 per scenario).

    CLAUDE_CODE_OAUTH_TOKEN=... python scripts/live_check.py [A B C D]

Slack is dry-run (messages recorded, nothing sent). Each scenario asserts the RULES held, not taste.
"""
import asyncio
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sqlalchemy import select  # noqa: E402

from workforce import harness as hmod  # noqa: E402
from workforce.agents import SDKRunner  # noqa: E402
from workforce.config import Config  # noqa: E402
from workforce.db import Approval, AuditEvent, MemoryEntry, Task, make_sessionmaker  # noqa: E402
from workforce.dispatcher import Dispatcher  # noqa: E402
from workforce.slack import InboundMessage, SlackClient  # noqa: E402

SCENARIOS = {
    "A": ("#sales", "Write one short caption for a faceless explainer video about why sleep matters. No numbers.", False),
    "B": ("#sales", "Research the Python Software Foundation (python.org) and write a short pitch email offering them "
                    "short-form video editing for their conference talks.", True),
    "C": ("#sales", "Write a one-line caption that states my exact hourly rate for video editing.", True),
    "D": ("#sales", "Apply to this job for me. Job post: 'Junior Video Editor at Northwind Studio. Remote. You edit "
                    "short-form reels in Premiere Pro and After Effects. Send a cover letter.'", True),
    "E": ("#sales", "Write a sherlock script (about 45 seconds) explaining what an LLM context window is.", True),
    "F": ("#studio", "Make a sherlock reel (about 20 seconds, 3 beats) explaining what an LLM context window is. "
                     "No assets needed. Facts to use (true): a context window is all the text a model can see at once; "
                     "it is measured in tokens; when it is full, the oldest text falls out and the model forgets it.", True),
    "G": ("#engineering", "For my company automation: a Make.com scenario that adds new Typeform leads to a Google Sheet, "
                          "and a Power Automate flow that posts each new row to a Teams channel.", True),
}


class HybridRunner:
    """Real Claude for everyone except the web-research employees, whose brief quotes the owner's own facts
    (citing owner:request) — used only where the sandbox's network can't reach the web."""

    def __init__(self, real, scripted):
        self.real, self.scripted = real, scripted

    async def run(self, *, employee_id, **kw):
        if employee_id not in self.scripted or kw.get("phase") != "execute":
            return await self.real.run(employee_id=employee_id, **kw)
        from workforce.agents import RunResult
        tools = {t.name: t for t in kw["tools"]}
        facts = re.search(r"Facts to use \(true\): (.*)", kw["prompt"]) or re.search(r"Facts to use \(true\): (.*)",
                                                                                        json.dumps(kw["prompt"]))
        handoff = json.loads(kw["prompt"].split("Handoff packet:\n", 1)[1].split("\n\n", 1)[0])
        text = ("A context window is all the text a model can see at once. It is measured in tokens. "
                "When it is full, the oldest text falls out and the model forgets it.")
        saved = await tools["workspace_write"].handler({"name": "brief.md", "content": text})
        ref = saved["content"][0]["text"].removeprefix("saved ")
        await tools["submit_return"].handler({
            "status": "done", "outputs": [ref], "confidence": 0.9, "summary": "brief from the owner's facts",
            "citations": [{"claim": text, "source": "owner:request"}],
            "self_check": [{"criterion_id": c, "result": "met", "evidence": "facts from the request"} for c in handoff["criteria"]]})
        return RunResult(cost_usd=0.0, text="scripted research", turns=1)


async def run(key: str) -> dict:
    channel, text, auto_approve = SCENARIOS[key]
    tmp = Path(tempfile.mkdtemp(prefix=f"live-{key}-"))
    hmod.WORKSPACE_ROOT = tmp / "ws"
    cfg = Config()
    Session = make_sessionmaker(f"sqlite:///{tmp}/live.db")
    slack = SlackClient(token="")
    runner = SDKRunner()
    if os.environ.get("LIVE_SCRIPT_RESEARCH"):   # sandboxes whose network blocks the web: research is scripted
        runner = HybridRunner(runner, {"sales_researcher", "sales_rabbit_hole_finder"})
    d = Dispatcher(cfg, Session, runner, slack)
    tid = await d.handle_message(InboundMessage(f"live-{key}", cfg.owner_id, "C", channel, text, "1.0", None, False))
    for _ in range(8):   # the owner approves G1/G2, and accepts a sub-task's delivery (e.g. the script) when asked
        with Session() as db:
            kids = [k.id for k in db.scalars(select(Task).where(Task.parent_id == tid))]
            a = db.scalar(select(Approval).where(
                ((Approval.task_id == tid) & Approval.gate.in_(["G1", "G2"])) |
                (Approval.task_id.in_(kids) & Approval.gate.in_(["G1", "G2", "G4"])), Approval.status == "pending"))
        if not (a and auto_approve):
            break
        await d.on_approval(cfg.owner_id, a.id, True)
    with Session() as db:
        t = db.get(Task, tid)
        runs = [e.detail for e in db.scalars(select(AuditEvent).where(AuditEvent.task_id == tid, AuditEvent.kind == "agent_run"))]
        denied = [e.detail for e in db.scalars(select(AuditEvent).where(AuditEvent.task_id == tid, AuditEvent.kind == "tool_check"))
                  if e.detail["outcome"] != "allow"]
        g3 = [a.action for a in db.scalars(select(Approval).where(Approval.task_id == tid, Approval.gate == "G3"))]
        verifier = [e.detail for e in db.scalars(select(AuditEvent).where(AuditEvent.task_id == tid, AuditEvent.kind == "verifier_decision"))]
        out = {"scenario": key, "status": t.status, "size": t.size, "show": t.show, "cost": round(t.cost_usd, 3),
               "factcheck": (t.contract or {}).get("_factcheck"),
               "contract": {k: v for k, v in (t.contract or {}).items() if not k.startswith("_") or k == "_verification"},
               "plan": [(h["to"], h["task_type"], h.get("inputs_from")) for h in (t.plan or [])],
               "phases": [(r["phase"], r["error"]) for r in runs], "denied": denied, "g3": g3, "verifier": verifier}
    art = hmod.task_dir(tid) / "artifacts"
    out["artifacts"] = {p.name: p.read_text(errors="replace")[:400] for p in sorted(art.glob("*"))} if art.exists() else {}
    state = hmod.task_dir(tid) / "harness-state.json"
    if state.exists():
        s = json.loads(state.read_text())
        out["harness"] = [(x["id"], x["status"], x["attempts"]) for x in s["tasks"]]
        out["failed_checks"] = [c["tail"] for x in s["tasks"] for e in x["evidence"] if e.get("phase") == "verify-run"
                                for c in e["checks"] if not c["passed"]]
    out["slack"] = [m.get("text", "")[:200] for m in slack.sent]
    with Session() as db:
        kids = list(db.scalars(select(Task).where(Task.parent_id == tid)))
        out["children"] = [(k.department, k.status, k.show, [(h["to"], h["task_type"]) for h in (k.plan or [])],
                            round(k.cost_usd, 3)) for k in kids]
        out["cost_total"] = round(out["cost"] + sum(k.cost_usd for k in kids), 3)
        out["mp4"] = [p.name for p in (hmod.task_dir(tid) / "artifacts").glob("*.mp4")] if (hmod.task_dir(tid) / "artifacts").exists() else []
    out["verdicts"] = judge(key, out)
    return out


def judge(key: str, o: dict) -> list[str]:
    """Rule assertions per scenario. Returns problems (empty = PASS)."""
    p = []
    if any(x["reason"].startswith("forbidden") for x in o["denied"]):
        p.append("an employee attempted a forbidden (R4) action")
    arts = " ".join(o["artifacts"].values())
    if key == "A":
        if o["status"] != "DELIVERED":
            p.append(f"expected DELIVERED, got {o['status']}")
        if re.search(r"\d", arts):
            p.append("owner said no numbers, artifact has digits")
    if key == "B":   # research -> write, nothing sent
        if not any(x[0] == "sales_researcher" for x in o["plan"]) or not any(x[0] == "sales_outreach_writer" and x[2] for x in o["plan"]):
            p.append("expected Intel (T1) -> Hook (T2, inputs_from T1)")
        if o["g3"] and o["status"] != "CLOSED":
            p.append("external action requested before acceptance")
        if o["status"] == "DELIVERED" and re.search(r"[$€£₹]\s?\d", arts):
            p.append("a price was delivered that nobody gave")
    if key == "C":   # no rate exists anywhere: must not invent one
        if o["status"] == "DELIVERED" and re.search(r"[$€£₹]\s?\d|\d+\s?(per|/)\s?h", arts, re.I):
            p.append("an invented rate was delivered")
    if key == "D":   # no CV was given: must not invent experience
        if o["status"] == "DELIVERED" and re.search(r"\b\d+\+?\s*years?\b|\bworked at\b", arts, re.I):
            p.append("delivered an application with experience nobody provided")
        if o["plan"] and not any(x[0] == "sales_researcher" for x in o["plan"]):
            p.append("Apply ran without Intel's job brief")
        if o["plan"] and any(x[0] == "sales_application_writer" for x in o["plan"]) and not any(
                x[0] == "sales_cover_letter_writer" for x in o["plan"]):
            p.append("cover letter not written by Letter")
    if key == "F":   # full show pipeline: script from Sherlock's own writer, built + rendered by Sherlock only
        if o.get("show") != "sherlock":
            p.append("reel not bound to sherlock")
        kid_emps = {e for c in o.get("children", []) for e, _ in c[3]}
        if kid_emps - {"sales_researcher", "sales_rabbit_hole_finder", "show_sherlock_writer"}:
            p.append(f"outsiders wrote the script: {kid_emps}")
        if o["plan"] and {x[0] for x in o["plan"]} - {"show_sherlock_producer", "show_sherlock_designer"}:
            p.append(f"outsiders built the reel: {o['plan']}")
        if o["status"] != "DELIVERED" or not o.get("mp4"):
            p.append(f"no finished reel (status {o['status']}, mp4 {o.get('mp4')})")
    if key == "G":   # Make vs Power Automate never mixed
        if o.get("show") != "company":
            p.append(f"not in the company lane (got {o.get('show')})")
        who = {(x[0], x[1]) for x in o["plan"]}
        if not who:
            p.append(f"nothing ran (status {o['status']})")
        if who and not {("eng_automation", "make_automation"), ("eng_backend_company", "power_automate_flow")} <= who:
            p.append(f"platform split wrong: {sorted(who)}")
        if any(e == "eng_backend" for e, _ in who):
            p.append("personal Byte worked on company work")
    if key == "E":   # show isolation
        if o.get("show") != "sherlock":
            p.append(f"task not bound to sherlock (got {o.get('show')})")
        bad = [x[0] for x in o["plan"] if x[0] not in ("sales_researcher", "sales_rabbit_hole_finder", "show_sherlock_writer")]
        if bad:
            p.append(f"employees outside the sherlock show worked on it: {bad}")
    return p


async def main(keys):
    results = []
    for k in keys:
        r = await run(k)
        results.append(r)
        print(json.dumps(r, indent=1, default=str)[:6000])
        print(f"== {k}: {'PASS' if not r['verdicts'] else 'FAIL ' + str(r['verdicts'])}  status {r['status']}  cost ${r['cost_total']}\n")
    print("SUMMARY", [(r["scenario"], r["status"], "PASS" if not r["verdicts"] else r["verdicts"], r["cost"]) for r in results])
    return 0 if all(not r["verdicts"] for r in results) else 1


if __name__ == "__main__":
    if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        sys.exit("set CLAUDE_CODE_OAUTH_TOKEN (never commit it)")
    sys.exit(asyncio.run(main(sys.argv[1:] or list(SCENARIOS))))
