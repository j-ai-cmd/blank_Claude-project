#!/usr/bin/env python3
"""Run the backend locally with SCRIPTED employees (no Claude calls, no spend) to drive the Live Office end to end.

    .venv/bin/python scripts/dev_office.py            # API on http://localhost:8000, token "dev-token"

Then open the frontend (npm --prefix frontend run dev), click the status pill → Connect backend, and enter
http://localhost:8000 + dev-token. Send any pitch request to Atlas (routes it to Sales) or straight to Sam: Sam drafts a contract
(approve it in the decision card), Intel researches (with a stubbed free-LLM call), Hook asks Intel a question
through peer_ask and writes the pitch, Proof checks it, Sam delivers. Data lives in var/dev/port-<PORT>/ (deleted on start).
"""
import asyncio
import os
import re
import shutil
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("PORT", "8000"))
DEV = ROOT / "var" / "dev" / f"port-{PORT}"   # one data folder per port: a launch on a spare port never touches another's
# A second launch must not wipe var/dev under a server that is still running (its SQLite file turns read-only).
with socket.socket() as probe:
    if probe.connect_ex(("127.0.0.1", PORT)) == 0:
        sys.exit(f"port {PORT} is already in use: another dev office is running; stop it first")
shutil.rmtree(DEV, ignore_errors=True)
DEV.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("WORKFORCE_API_TOKEN", "dev-token")
os.environ.setdefault("WORKFORCE_FRONTEND_ORIGIN", "http://localhost:5173,http://127.0.0.1:5173")
os.environ["DATABASE_URL"] = f"sqlite:///{DEV}/office.db"
os.environ["WORKSPACE_ROOT"] = str(DEV / "ws")
os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

from workforce import app as appmod  # noqa: E402
from workforce import free_llm  # noqa: E402
from workforce.agents import FakeRunner  # noqa: E402
from workforce.config import Config  # noqa: E402
from workforce.db import make_sessionmaker  # noqa: E402
from workforce.dispatcher import Dispatcher  # noqa: E402
from workforce.slack import SlackClient  # noqa: E402

PACE = float(os.environ.get("DEV_PACE_S", "2.5"))   # seconds each scripted employee "works", so the walks are visible
BRIEF = ("The Python Software Foundation runs PyCon US and publishes talk recordings on YouTube. "
         "Short clips of those talks could reach people who never watch a full session.")
PITCH = ("Hi PSF team, your PyCon talks deserve a second life as short clips. "
         "I cut long talks into sharp vertical videos that bring new people to the full session.")


def ref(res: dict) -> str:
    return res["content"][0]["text"].removeprefix("saved ")


async def contract(tools, ctx):
    await asyncio.sleep(PACE)
    await tools["submit_contract"].handler({
        "objective": "Research the client, then write a short pitch email", "size": "M",
        "deliverables": [
            {"id": "D1", "description": "cited client brief", "format": "md", "assignee": "sales_researcher", "task_type": "account_brief"},
            {"id": "D2", "description": "pitch email draft", "format": "md", "assignee": "sales_outreach_writer", "task_type": "pitch_email"}],
        "acceptance_criteria": [{"id": "1", "text": "brief cites its sources", "check": "automatic"},
                                {"id": "2", "text": "pitch is two sentences", "check": "automatic"}]})


async def route(tools, ctx):   # Atlas (the memo box's default recipient) hands the request to Sales
    await asyncio.sleep(PACE)
    await tools["submit_contract"].handler({
        "objective": "Route the request to Sales", "size": "M",
        "deliverables": [{"id": "D1", "description": "Sales pitch package", "assignee": "sales_lead", "task_type": "route"}],
        "acceptance_criteria": [{"id": "1", "text": "Sales delivers the brief and pitch", "check": "automatic"}],
        "departments": [{"department": "sales", "objective": "Research the client, then write a short pitch email",
                         "acceptance_criteria": [{"id": "1", "text": "brief cites its sources"},
                                                 {"id": "2", "text": "pitch is two sentences"}]}]})


async def plan(tools, ctx):
    await asyncio.sleep(PACE)
    await tools["submit_plan"].handler({"handoffs": [
        {"deliverable": "D1", "to": "sales_researcher", "task_type": "account_brief", "objective": "brief", "criteria": ["1"]},
        {"deliverable": "D2", "to": "sales_outreach_writer", "task_type": "pitch_email", "objective": "pitch",
         "criteria": ["2"], "inputs_from": ["T1"], "platform": "email"}]})


async def research(tools, ctx):
    await asyncio.sleep(PACE)
    if "llm_free" in tools:
        await tools["llm_free"].handler({"instruction": "Rank these public pages by relevance", "text": BRIEF})
    out = ref(await tools["workspace_write"].handler({"name": "brief.md", "content": BRIEF}))
    await tools["submit_return"].handler({
        "status": "done", "outputs": [out], "confidence": 0.9, "summary": "brief on PSF and PyCon recordings",
        "citations": [{"claim": BRIEF, "source": "owner:request"}],
        "self_check": [{"criterion_id": "1", "result": "met", "evidence": "cited"}]})


async def answer(tools, ctx):
    await asyncio.sleep(PACE / 2)
    await tools["submit_answer"].handler({"answer": "Open with the YouTube recordings: see artifact T1-brief.md."})


async def write(tools, ctx):
    await asyncio.sleep(PACE)
    if "peer_ask" in tools:
        await tools["peer_ask"].handler({"to": "sales_researcher", "question": "Which fact makes the best opening line?"})
    up = re.findall(r"artifact://\S+?T1-brief\.md", ctx["prompt"])
    if up:
        await tools["workspace_read"].handler({"ref": up[0]})
    out = ref(await tools["workspace_write"].handler({"name": "pitch.md", "content": PITCH}))
    await tools["submit_return"].handler({
        "status": "done", "outputs": [out], "confidence": 0.9, "summary": "two-sentence pitch from Intel's brief",
        "self_check": [{"criterion_id": "2", "result": "met", "evidence": "two sentences"}]})


async def factcheck(tools, ctx):
    await asyncio.sleep(PACE)
    await tools["submit_factcheck"].handler({"claims": []})


async def deliver(tools, ctx):
    await asyncio.sleep(PACE / 2)
    await tools["submit_delivery"].handler({"note": "Brief and pitch draft are ready. Nothing was sent."})


def main() -> None:
    free_llm.complete = lambda providers, instruction, text, timeout=60.0, max_tokens=2048: free_llm.FreeAnswer(
        "dev-stub", "none", "1. PyCon recordings page\n2. PSF about page")
    scripts = {("chief_of_staff", "contract"): route, ("chief_of_staff", "deliver"): deliver,
               ("sales_lead", "contract"): contract, ("sales_lead", "plan"): plan, ("sales_lead", "deliver"): deliver,
               ("sales_researcher", "execute"): research, ("sales_researcher", "peer_answer"): answer,
               ("sales_outreach_writer", "execute"): write, ("fact_checker", "factcheck"): factcheck}
    cfg = Config()
    cfg.org["routines"] = {}   # the 9am inbox scan has no scripted employee here; it would only fail and escalate
    appmod.app.state.dispatcher = Dispatcher(cfg, make_sessionmaker(), FakeRunner(scripts, cost_per_run=0.012),
                                             SlackClient(token=""))
    uvicorn.run(appmod.app, host="127.0.0.1", port=PORT, timeout_graceful_shutdown=2)  # open SSE streams never close on their own


if __name__ == "__main__":
    main()
