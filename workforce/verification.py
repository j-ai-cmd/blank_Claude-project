"""Proof (fact check) and Vera (verifier) after the machine checks."""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from sqlalchemy import select

from . import states
from .agents import ToolSpec, err, ok
from .contracts import _norm
from .db import Approval, AuditEvent, MemoryEntry, Task
from .dispatch_common import CLAIM, NUMBER, PROSE_SUFFIXES, TEXT_SUFFIXES, URL, VERIFY, normalize_ids
from .harness import task_dir
from .prompts import owner_request, system_prompt, untrusted


class VerificationMixin:
    # ================================================================== verify (LLM Verifier, §7)
    def _text_artifacts(self, task_id: str) -> list[tuple[str, str]]:
        art = task_dir(task_id) / "artifacts"
        return [(p.name, p.read_text(errors="replace")) for p in sorted(art.glob("*"))
                if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES and not p.name.startswith("X-")]

    def _returns(self, task_id: str) -> list[dict]:
        return [json.loads(p.read_text()) for p in sorted(task_dir(task_id).glob("T*/return.json"))]

    def _source_text(self, task_id: str, srcs: list[str]) -> str:
        """Text of the task-internal sources a claim cites (owner request, contract, handoffs, artifacts, owner facts)."""
        with self.Session() as db:
            t = db.get(Task, task_id)
            owner, contract, plan = self._owner_text(t), json.dumps(t.contract or {}), list(t.plan or [])
        out = []
        for src in srcs:
            if src == "owner:request":
                out.append(owner)
            elif src == "contract":
                out.append(contract)
            elif re.fullmatch(r"handoff:T\d+", src) and int(src[9:]) <= len(plan):
                out.append(json.dumps(plan[int(src[9:]) - 1]))
            elif src.startswith("context:") and src[8:] in self.cfg.employees:
                out.append(self.cfg.owner_facts(src[8:]))
            elif src.startswith("artifact://"):
                p = task_dir(task_id) / "artifacts" / src.split("/")[-1]
                out.append(p.read_text(errors="replace") if p.exists() else "")
            elif src.startswith("memory:"):
                with self.Session() as db:
                    m = db.get(MemoryEntry, src[7:])
                    out.append(m.content if m else "")
            elif src.startswith("pipeline:"):
                from .db import PipelineItem
                with self.Session() as db:
                    r = db.get(PipelineItem, src[9:])
                    out.append(f"{r.to} {r.subject} {r.body} {r.note}" if r else "")
            elif src.startswith("upload:"):
                from . import uploads
                scope, _, name = src[7:].partition("/")
                p = uploads.path(scope, name)
                out.append(p.read_bytes()[:200_000].decode("utf-8", "replace") if p else "")
            elif src.startswith("email:") and self.email_reader.configured():
                try:
                    out.append(json.dumps(self.email_reader.open(src[6:])))
                except Exception:  # noqa: BLE001
                    out.append("")
        return "\n".join(out)

    def _needs_proof(self, t: Task) -> tuple[bool, str]:
        """Proof (fact checker) runs before Vera whenever a deliverable could state a fact (P5/P6)."""
        if not self._text_artifacts(t.id):
            return False, "no text deliverable"
        if any(r.get("citations") for r in self._returns(t.id)):
            return True, "cites sources"
        for name, text in self._text_artifacts(t.id):
            if Path(name).suffix.lower() in PROSE_SUFFIXES and CLAIM.search(URL.sub(" ", text)):
                return True, f"{name} contains numbers/dates/prices"   # C10
        if t.size in ("M", "L"):
            return True, f"size {t.size}"
        if any(self.cfg.employees[h["to"]].dept == "sales" for h in t.plan or []):
            return True, "research/writing work (pitches, applications, scripts) always gets its facts checked"
        return False, "short internal text, no factual claims"

    def _needs_llm_verifier(self, t: Task) -> tuple[bool, str]:
        """DECIDED (owner): Vera grades the brief only when you ask ('verify'), or while a new hire is on
        probation. Facts are always checked by Proof; external actions always wait for your G3 click."""
        if VERIFY.search(self._owner_text(t)) or t.contract.get("_verify_requested"):
            return True, "you asked to verify"
        if any(self.cfg.employees[h["to"]].probation for h in t.plan or [] if h.get("to") in self.cfg.employees):
            return True, "a new hire on probation worked on it"
        return False, "not requested (reply 'verify' to have Vera grade it against your brief)"

    def _to_revision(self, db, t: Task, actor: str, notes: str) -> bool:
        """Shared revision step for Proof and Vera findings. False = limit reached (escalated)."""
        t.revisions += 1
        if t.revisions > self.revision_limit:
            states.transition(db, t, "ESCALATED", actor, "revision limit reached")
            return False
        states.transition(db, t, "REVISION", actor)
        c2 = dict(t.contract)
        c2["_revision_notes"] = notes   # C46: specialists see the findings verbatim
        t.contract = c2
        return True

    async def factcheck(self, task_id: str) -> str | None:
        """Proof: claim-by-claim TRUE/FALSE/UNSOURCED. Returns revision notes, 'stop', or None (passed)."""
        with self.Session() as db:
            t = db.get(Task, task_id)
            plan_emps = [self.cfg.employees[h["to"]] for h in t.plan or []]
            # a deliverable built from private data (CV, statements) is never taken onto the web (exfiltration)
            offline = t.contains_pii or any(set(e.tools) & self.cfg.private_data_tools for e in plan_emps)
            contract = {k: v for k, v in t.contract.items() if not k.startswith("_")}
            earlier = list(t.contract.get("_factcheck") or [])
            db.commit()
        proof = self.cfg.employee("fact_checker")
        arts = [untrusted("deliverable", n, txt[:30_000]) for n, txt in self._text_artifacts(task_id)]
        cites = [c for r in self._returns(task_id) for c in r.get("citations", [])]
        required = set()
        prose = " ".join(_norm(txt) for name, txt in self._text_artifacts(task_id)
                         if Path(name).suffix.lower() in PROSE_SUFFIXES)
        for name, txt in self._text_artifacts(task_id):
            if Path(name).suffix.lower() in PROSE_SUFFIXES:
                txt = URL.sub(" ", txt)   # numbers inside links aren't claims
                spans = [m.span() for m in CLAIM.finditer(txt)]
                required |= {n.group(0) for n in NUMBER.finditer(txt)
                             if any(a < n.end() and n.start() < b for a, b in spans)}   # whole number, e.g. $49 -> 49
        # Cost: a revision round re-checks only what changed. TRUE claims from an earlier round whose exact quote is
        # still in the deliverable are carried over (their sources stay in this task's fetch log); Proof checks the rest.
        carried = [c for c in earlier if c.get("verdict") == "TRUE" and _norm(str(c.get("quote", ""))) and
                   _norm(str(c.get("quote", ""))) in prose and not self._unobserved_citations(task_id, c.get("sources") or [])]
        prompt = ("Contract (a SOURCE you may cite as 'contract' — not a checklist; Vera grades the brief):\n"
                  + json.dumps(contract, indent=1) + "\n\nDeliverables:\n" + "\n\n".join(arts) +
                  "\n\nCitations the writers gave:\n" + json.dumps(cites, indent=1) +
                  "".join("\n\n" + owner_request(f"context:{e.id}", f"Owner facts (true — the owner's own words):\n{f}")
                          for e in plan_emps if (f := self.cfg.owner_facts(e.id))) +
                  ("\n\nThis task holds private data: do NOT use the web; check only against the cited task sources."
                   if offline else "\n\nRe-fetch cited URLs; for web facts find a second independent source.") +
                  ("\n\nAlready verified TRUE in an earlier round and still in the deliverable word for word — do NOT "
                   "re-check or re-fetch these; submit only the OTHER claims (these are added for you):\n"
                   + json.dumps([{k: c.get(k) for k in ("quote", "claim", "sources")} for c in carried], indent=1)
                   if carried else ""))
        sink: dict = {}

        async def submit_factcheck(args):
            claims = normalize_ids(args).get("claims")
            if not isinstance(claims, list):
                return err("claims must be a list of {claim, verdict, sources, evidence}")
            fresh = {_norm(str(c.get("quote", ""))) for c in claims if isinstance(c, dict)}
            claims = claims + [dict(c, evidence=f"carried from an earlier round: {c.get('evidence', '')}")
                               for c in carried if _norm(str(c.get("quote", ""))) not in fresh]
            problems = []
            for i, c in enumerate(claims, 1):
                if not isinstance(c, dict) or not str(c.get("claim", "")).strip():
                    problems.append(f"#{i}: claim text missing")
                    continue
                if _norm(str(c.get("quote", ""))) not in prose or not _norm(str(c.get("quote", ""))):
                    problems.append(f"#{i}: quote must be copied word for word from the deliverable text — a claim is a "
                                    "fact stated IN the deliverable, not whether the brief was met (that is Vera's job)")
                    continue
                if c.get("verdict") not in ("TRUE", "FALSE", "UNSOURCED"):
                    problems.append(f"#{i}: verdict must be TRUE, FALSE or UNSOURCED")
                srcs = [str(x) for x in c.get("sources") or []]
                if c.get("verdict") == "TRUE" and not srcs:
                    problems.append(f"#{i}: TRUE needs the source(s) you checked it against")
                bad = self._unobserved_citations(task_id, srcs)
                if bad:
                    problems.append(f"#{i}: sources not observed in this task {bad} — fetch them or mark UNSOURCED")
                elif c.get("verdict") == "TRUE" and srcs and not any(x.startswith("http") for x in srcs):
                    missing = [n for n in NUMBER.findall(str(c.get("quote", "")) + " " + str(c["claim"]))
                               if n not in self._source_text(task_id, srcs)]
                    if missing:   # deterministic: the number must literally be in the task source it cites
                        problems.append(f"#{i}: {missing} not found in {srcs} — FALSE or UNSOURCED, not TRUE")
            covered = {n for c in claims if isinstance(c, dict)
                       for n in NUMBER.findall(str(c.get("quote", "")) + " " + str(c.get("claim", "")))}
            skipped = sorted(required - covered)
            if skipped:   # a lazy "no claims" can't pass while the deliverable states numbers
                problems.append(f"the deliverables state {skipped} but no claim covers them — list every factual claim")
            if problems:
                return err("Fact check rejected: " + "; ".join(problems[:8]))
            sink["claims"] = claims
            return ok("Fact check stored. Stop here.")
        tools = [ToolSpec("submit_factcheck", "Submit the claim-by-claim fact check (once).",
                          {"type": "object", "properties": {"claims": {"type": "array", "items": {"type": "object", "properties": {
                              "quote": {"type": "string", "description": "exact words copied from the deliverable"},
                              "claim": {"type": "string"}, "verdict": {"type": "string", "enum": ["TRUE", "FALSE", "UNSOURCED"]},
                              "sources": {"type": "array", "items": {"type": "string"}}, "evidence": {"type": "string"}},
                              "required": ["quote", "claim", "verdict", "sources", "evidence"]}}}, "required": ["claims"]},
                          submit_factcheck)]
        owner = self.task_owner(self._dept(task_id))
        self.live.handoff(task_id, owner, proof.id, "for_factcheck", contract.get("objective", ""))
        await self._run(proof, task_id, "factcheck", system_prompt(self.cfg, proof, "factcheck"), prompt, tools,
                        no_web=offline)
        if "claims" in sink:
            n_bad = sum(1 for x in sink["claims"] if x.get("verdict") != "TRUE")
            self.live.handoff(task_id, proof.id, owner, "factcheck_result",
                              "all facts check out" if not n_bad else f"{n_bad} claims wrong or unsourced", passed=not n_bad)
        with self.Session() as db:
            t = db.get(Task, task_id)
            if "claims" not in sink:
                states.transition(db, t, "ESCALATED", "fact_checker", "fact checker produced no result")
                db.commit()
                self._post(t, proof, "⚠️ I couldn't complete the fact check — escalating. Reply 'resume' to retry.")
                return "stop"
            c = dict(t.contract)
            c["_factcheck"] = sink["claims"]
            t.contract = c
            bad = [x for x in sink["claims"] if x["verdict"] != "TRUE"]
            if not bad:
                db.commit()
                return None
            notes = json.dumps({"fact_check_failed": bad})[:3000]
            if not self._to_revision(db, t, "fact_checker", notes):
                db.commit()
                self._post(t, proof, "⚠️ Facts still wrong or unsourced after 2 revisions — escalating to you.\n"
                           + json.dumps(bad)[:1500])
                return "stop"
            db.commit()
            return notes

    async def verify(self, task_id: str) -> None:
        with self.Session() as db:
            t = db.get(Task, task_id)
            states.transition(db, t, "VERIFYING", "harness", "all plan tasks passed automatic checks")
            need_proof, why_proof = self._needs_proof(t)
            need, why = self._needs_llm_verifier(t)
            db.add(AuditEvent(task_id=t.id, actor="dispatcher", kind="verifier_decision",
                              detail={"proof": need_proof, "proof_why": why_proof, "need": need, "why": why}))
            if not need:
                t.verification_id = f"auto-checks-{t.id}-v{t.contract_version}-r{t.revisions}"
            contract = {k: v for k, v in t.contract.items() if not k.startswith("_")}
            db.commit()
        self._active.add(task_id)
        try:
            notes = await self.factcheck(task_id) if need_proof else None
            if notes is None and need:
                notes = await self._vera(task_id, contract)
        finally:
            self._active.discard(task_id)
        if notes == "stop":
            return
        if notes:
            await self.plan(task_id, revision_notes=notes)
            return
        await self.deliver(task_id)

    async def verify_on_request(self, task_id: str, user: str) -> None:
        with self.Session() as db:
            t = db.get(Task, task_id)
            for a in db.scalars(select(Approval).where(Approval.task_id == t.id, Approval.gate == "G4",
                                                       Approval.status == "pending")):
                a.status = "expired"   # a fresh G4 card follows Vera's grades
            c = dict(t.contract)
            c["_verify_requested"] = True
            t.contract = c
            states.transition(db, t, "VERIFYING", user, "owner asked to verify")
            contract = {k: v for k, v in t.contract.items() if not k.startswith("_")}
            db.commit()
        self._active.add(task_id)
        try:
            notes = await self._vera(task_id, contract)
        finally:
            self._active.discard(task_id)
        if notes == "stop":
            return
        if notes:
            await self.plan(task_id, revision_notes=notes)
            return
        await self.deliver(task_id)

    async def _vera(self, task_id: str, contract: dict) -> str | None:
        vera = self.cfg.employee("verifier")
        arts = [untrusted("deliverable", n, txt[:30_000]) for n, txt in self._text_artifacts(task_id)]
        cites = [c for r in self._returns(task_id) for c in r.get("citations", [])]
        prompt = ("Contract:\n" + json.dumps(contract, indent=1) + "\n\nDeliverables:\n" + "\n\n".join(arts) +
                  "\n\nCited sources:\n" + json.dumps(cites, indent=1) +
                  "\n\nFacts were already checked by Proof; you grade only whether the brief was met.")
        sink: dict = {}

        async def submit_verdict(args):
            args = normalize_ids(args)
            grades = args.get("grades") or []
            ids = [c["id"] for c in contract["acceptance_criteria"]]
            if sorted(str(g.get("criterion_id")) for g in grades) != sorted(ids):
                return err(f"grade every criterion exactly once: {ids}")
            if any(g.get("result") not in ("PASS", "FAIL", "UNVERIFIABLE") for g in grades):
                return err("result must be PASS, FAIL or UNVERIFIABLE")
            taste = {c["id"] for c in contract["acceptance_criteria"] if c.get("check") == "owner_taste"}
            if any(g["criterion_id"] in taste and g["result"] != "UNVERIFIABLE" for g in grades):
                return err(f"criteria {sorted(taste)} are the owner's taste call — grade them UNVERIFIABLE (C26)")
            sink["verdict"] = args
            return ok("Verdict stored. Stop here.")
        tools = [ToolSpec("submit_verdict", "Submit criterion grades (once).",
                          {"type": "object", "properties": {"grades": {"type": "array", "items": {"type": "object", "properties": {
                              "criterion_id": {"type": "string"}, "result": {"type": "string", "enum": ["PASS", "FAIL", "UNVERIFIABLE"]},
                              "evidence": {"type": "string"}}, "required": ["criterion_id", "result", "evidence"]}}},
                           "required": ["grades"]}, submit_verdict)]
        owner = self.task_owner(self._dept(task_id))
        self.live.handoff(task_id, owner, vera.id, "for_verification", contract.get("objective", ""))
        await self._run(vera, task_id, "verify", system_prompt(self.cfg, vera, "verify"), prompt, tools)
        verdict = sink.get("verdict")
        if verdict:
            n_fail = sum(1 for g in verdict["grades"] if g.get("result") == "FAIL")
            self.live.handoff(task_id, vera.id, owner, "verdict", "PASS" if not n_fail else f"{n_fail} criteria failed",
                              passed=not n_fail and not verdict.get("uncited_claims"))
        with self.Session() as db:
            t = db.get(Task, task_id)
            if not verdict:
                states.transition(db, t, "ESCALATED", "verifier", "verifier produced no verdict")
                db.commit()
                self._post(t, vera, "⚠️ I couldn't complete verification — escalating. Reply 'resume' to retry.")
                return "stop"
            fails = [g for g in verdict["grades"] if g.get("result") == "FAIL"]
            c = dict(t.contract)
            c["_verification"] = verdict
            t.contract = c
            if fails:
                notes = json.dumps({"failed": fails})[:3000]
                if not self._to_revision(db, t, "verifier", notes):
                    db.commit()
                    self._post(t, vera, "⚠️ Still failing after 2 revisions — escalating to you.\n" + json.dumps(fails)[:1500])
                    return "stop"
                db.commit()
                return notes
            t.verification_id = f"ver_{uuid.uuid4().hex[:8]}"
            db.commit()
            return None
