"""Org v3 step 10: llm_free — public text to Groq, then Gemini; never private data. HTTP is mocked."""
import httpx
import pytest
from sqlalchemy import select

from workforce import free_llm
from workforce.db import AuditEvent, Task


class Resp:
    def __init__(self, code, text="answer"):
        self.status_code, self.text = code, text

    def json(self):
        return {"choices": [{"message": {"content": self.text}}]}


PROVIDERS = [{"name": "groq", "base_url": "https://g.example/v1", "model": "m1", "key_env": "GROQ_API_KEY"},
             {"name": "gemini", "base_url": "https://gm.example/v1", "model": "m2", "key_env": "GEMINI_API_KEY"}]


def test_falls_back_on_rate_limit_and_skips_missing_keys(monkeypatch):
    calls = []
    monkeypatch.setenv("GROQ_API_KEY", "k1")
    monkeypatch.setenv("GEMINI_API_KEY", "k2")

    def post(url, headers=None, json=None, timeout=None):
        calls.append((url, headers["Authorization"], json["model"]))
        return Resp(429) if "g.example" in url else Resp(200, "from gemini")
    monkeypatch.setattr(httpx, "post", post)
    ans = free_llm.complete(PROVIDERS, "summarise", "public page text")
    assert (ans.provider, ans.text) == ("gemini", "from gemini")
    assert calls[0] == ("https://g.example/v1/chat/completions", "Bearer k1", "m1")
    monkeypatch.delenv("GROQ_API_KEY")
    monkeypatch.delenv("GEMINI_API_KEY")
    with pytest.raises(free_llm.FreeLLMUnavailable, match="no GROQ_API_KEY"):
        free_llm.complete(PROVIDERS, "x", "y")


def _task(d, tid, pii=False, private=()):
    with d.Session() as db:
        db.add(Task(id=tid, department="sales", requested_by="U_OWNER", original_request="x", contract_version=1,
                    status="IN_PROGRESS", contains_pii=pii, contract={"_private_strings": list(private)}))
        db.commit()


async def test_tool_sends_public_text_and_refuses_personal_or_private(make_dispatcher, cfg, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k1")
    sent = []
    monkeypatch.setattr(httpx, "post", lambda url, headers=None, json=None, timeout=None: sent.append(json) or Resp(200, "ranked"))
    d, _, _ = make_dispatcher({})
    _task(d, "f1", private=["Northwind secret rate"])
    intel = cfg.employee("sales_researcher")
    ctx = {"untrusted": False}
    tool = d._guard(intel, "f1", d._free_llm_tool(intel, "f1", ctx))
    ok = await tool.handler({"instruction": "rank these posts", "text": "post A ... post B"})
    assert "ranked" in ok["content"][0]["text"] and "<untrusted" in ok["content"][0]["text"] and ctx["untrusted"]
    for text in ("mail jai@gmail.com about it", "the Northwind secret rate is high"):
        assert (await tool.handler({"instruction": "summarise", "text": text})).get("is_error"), text
    assert len(sent) == 1                                                    # refused text never left
    with d.Session() as db:
        assert db.scalar(select(AuditEvent).where(AuditEvent.kind == "free_llm")).detail["provider"] == "groq"


async def test_policy_refuses_private_holders_and_pii_tasks(make_dispatcher, cfg):
    d, _, _ = make_dispatcher({})
    _task(d, "f2", pii=True)
    _task(d, "f3")
    intel, letter = cfg.employee("sales_researcher"), cfg.employee("sales_cover_letter_writer")
    with d.Session() as db:
        assert d.policy.check(db, intel, "llm.free", {}, db.get(Task, "f2")).outcome == "deny"     # PII task
        assert d.policy.check(db, intel, "llm.free", {}, db.get(Task, "f3")).outcome == "allow"
        assert d.policy.check(db, letter, "llm.free", {}, db.get(Task, "f3")).outcome == "deny"    # not allowlisted
    for e in cfg.employees.values():
        if "llm.free" in e.tools:
            assert not set(e.tools) & cfg.private_data_tools, e.id
    assert {e.id for e in cfg.employees.values() if "llm.free" in e.tools} == {
        "sales_scout", "sales_researcher", "sales_rabbit_hole_finder", "show_peter_writer"}
