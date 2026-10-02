from tests.test_flags import COPY, OWNER, ref_of
from workforce.db import Task


async def test_C44_owner_request_citable_and_bad_citations_bounced(make_dispatcher, cfg):
    d, _, _ = make_dispatcher({})
    with d.Session() as db:
        db.add(Task(id="tc", department="sales", requested_by=OWNER, original_request="x", contract_version=1,
                    contract={"planned_actions_tiers": []}))
        db.commit()
    d._new_round("tc")
    sink, ctx = {}, {}
    tools = {t.name: t for t in d._common_tools(cfg.employee("sales_writer"), "tc", "T1", set(), ctx)}
    ref = ref_of(await tools["workspace_write"].handler({"name": "c.md", "content": COPY}))
    submit = d._submit_return_tool(cfg.employee("sales_writer"), "tc", "T1", sink, ctx)
    base = {"status": "done", "outputs": [ref], "confidence": 0.9,
            "self_check": [{"criterion_id": "1", "result": "met", "evidence": "ok"}]}
    r = await submit.handler({**base, "citations": [{"claim": "price", "source": "crm:deal/9"}]})
    assert r.get("is_error") and "weren't observed" in r["content"][0]["text"]
    r = await submit.handler({**base, "citations": [{"claim": "launch", "source": "owner:request"},
                                                    {"claim": "tone", "source": "handoff:T1"}]})
    assert not r.get("is_error"), r
