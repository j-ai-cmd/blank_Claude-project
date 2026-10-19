"""Tools handed to employee sessions. Every tool goes through `_guard` -> Policy.check -> audit."""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from .agents import ToolSpec, err, ok
from .config import Employee, ROOT, SKILLS_DIR
from .contracts import validate_pending_actions
from .db import AuditEvent, Task
from .dispatch_common import PIPELINE_STATUSES, SAFE_NAME, SKILL_TEXT_SUFFIXES, TOOL_ACTIONS, normalize_ids
from .harness import plan_task_dir, task_dir
from .policy import APPROVAL
from .pii import find_pii
from .prompts import system_prompt, untrusted


class ToolboxMixin:
    # ------------------------------------------------------------------ tools given to agents
    def _check(self, emp: Employee, task_id: str, action: str, params: dict | None = None):
        with self.Session() as db:
            t = db.get(Task, task_id)
            dec = self.policy.check(db, emp, action, params or {}, t)
            db.commit()
        return dec

    def _guard(self, emp: Employee, task_id: str, spec: ToolSpec) -> ToolSpec:
        """C1: every Dispatcher tool is permission-checked and audited before it runs."""
        action = TOOL_ACTIONS.get(spec.name)
        inner = spec.handler

        async def guarded(args: dict) -> dict:
            if action:
                dec = self._check(emp, task_id, action, {"tool": spec.name})
                if not dec.allowed:
                    return err(f"denied by policy: {dec.reason}")
            return await inner(args)
        return ToolSpec(spec.name, spec.description, spec.schema, guarded)

    def _submit_delivery_tool(self, sink: dict) -> ToolSpec:
        async def submit_delivery(args):
            sink["note"] = str(args.get("note", ""))[:3000]
            return ok("Delivery stored. Stop here.")
        return ToolSpec("submit_delivery", "Submit the owner-facing delivery note (once).",
                        {"type": "object", "properties": {"note": {"type": "string"}}, "required": ["note"]}, submit_delivery)

    def _lead_tools(self, emp: Employee, task_id: str, phase: str, sink: dict) -> list[ToolSpec]:
        """The same three tools in every phase of a lead session (a changing tool list would drop the cache);
        only the current phase's tool works."""
        live = {"contract": "submit_contract", "plan": "submit_plan", "deliver": "submit_delivery"}[phase]
        tools = [self._submit_contract_tool(emp, task_id, sink if phase == "contract" else {}),
                 self._submit_plan_tool(emp, task_id, sink if phase == "plan" else {}),
                 self._submit_delivery_tool(sink if phase == "deliver" else {})]

        def off_phase(spec: ToolSpec) -> ToolSpec:
            async def refuse(_args):
                return err(f"{spec.name} is not for this turn — this is the {phase} phase: call {live}")
            return ToolSpec(spec.name, spec.description, spec.schema, refuse)
        return [t if t.name == live else off_phase(t) for t in tools]

    def _peer_ask_tool(self, emp: Employee, task_id: str, pt: str, packets: list[dict], ctx: dict) -> ToolSpec | None:
        """ORG-V3 §3c: ask an UPSTREAM peer on this task about its finished work. The Dispatcher checks the pair,
        relays the question and runs the peer once (no web, no new work); nothing else ever reaches another employee."""
        handoff = packets[int(pt[1:]) - 1]
        peers = {}   # employee id -> its plan step, for finished upstream steps only
        for dep in handoff.get("inputs_from") or []:
            if re.fullmatch(r"T\d+", dep) and int(dep[1:]) <= len(packets) and (plan_task_dir(task_id, dep) / "return.json").exists():
                peers[packets[int(dep[1:]) - 1]["to"]] = dep
        if not peers:
            return None
        rules = self.cfg.org.get("peer_ask") or {}
        limit, max_chars = int(rules.get("max_per_pair", 3)), int(rules.get("max_question_chars", 1500))
        web = {"web.search", "web.fetch"}

        async def ask(args):
            to, question = str(args.get("to", "")), str(args.get("question", "")).strip()
            dep = peers.get(to)
            if dep is None:
                return err(f"you may ask only the finished upstream employees of your step: {sorted(peers)}")
            peer = self.cfg.employee(to)
            if not question or len(question) > max_chars:
                return err(f"question must be 1–{max_chars} characters")
            if find_pii(question):
                return err("no personal data in questions to other employees")
            if set(emp.tools) & self.cfg.private_data_tools and set(peer.tools) & web:
                return err(f"you hold private data and {peer.name} can use the web — ask the owner instead (open_questions)")
            log_p = task_dir(task_id) / "peer_asks.json"
            log = json.loads(log_p.read_text()) if log_p.exists() else {}
            pair = f"{pt}->{dep}"
            if log.get(pair, 0) >= limit:
                return err(f"you already asked {peer.name} {limit} times on this task — decide, or put it in open_questions")
            log[pair] = log.get(pair, 0) + 1
            log_p.write_text(json.dumps(log))
            answer = await self._peer_answer(peer, task_id, dep, packets, emp, question)
            with self.Session() as db:
                db.add(AuditEvent(task_id=task_id, actor=emp.id, kind="peer_ask",
                                  detail={"from": emp.id, "to": peer.id, "pair": pair, "question": question[:300],
                                          "answer": (answer or "")[:300]}))
                db.commit()
            if answer is None:
                return err(f"{peer.name} gave no answer — decide yourself or put it in open_questions")
            ctx["untrusted"] = True   # another employee's words (C13)
            return ok(untrusted("peer", peer.id, answer) + "\nCite the peer's artifact:// refs, not this answer.")

        return ToolSpec("peer_ask", f"Ask a finished upstream employee of your step about its work: {sorted(peers)}. "
                        f"At most {limit} questions each.",
                        {"type": "object", "properties": {"to": {"type": "string", "enum": sorted(peers)},
                                                          "question": {"type": "string"}}, "required": ["to", "question"]}, ask)

    async def _peer_answer(self, peer: Employee, task_id: str, dep: str, packets: list[dict], asker: Employee,
                           question: str) -> str | None:
        d = plan_task_dir(task_id, dep)
        ret = json.loads((d / "return.json").read_text())
        with self.Session() as db:
            show = db.get(Task, task_id).show
        self.live.handoff(task_id, asker.id, peer.id, "peer_ask", question, step=dep)
        sink: dict = {}

        async def submit_answer(args):
            sink["answer"] = str(args.get("answer", ""))[:1500]
            return ok("Answer stored. Stop here.")
        own = [t for t in self._common_tools(peer, task_id, dep, set(), {"untrusted": False, "pt": dep})
               if t.name == "workspace_read"]
        prompt = ("Your handoff:\n" + json.dumps({k: v for k, v in packets[int(dep[1:]) - 1].items() if k != "task_id"}, indent=1)
                  + "\n\nYour return packet:\n" + json.dumps({k: ret.get(k) for k in ("summary", "outputs", "open_questions")}, indent=1)
                  + "\n\nQuestion from " + asker.name + ":\n" + untrusted("peer_question", asker.id, question))
        await self._run(peer, task_id, "peer_answer", system_prompt(self.cfg, peer, "peer_answer", None, show=show), prompt,
                        own + [ToolSpec("submit_answer", "Answer the question (once).",
                                        {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]},
                                        submit_answer)], no_web=True)
        self.live.handoff(task_id, peer.id, asker.id, "peer_answer", sink.get("answer", "(no answer)"), step=dep)
        return sink.get("answer")

    def _free_llm_tool(self, emp: Employee, task_id: str, ctx: dict) -> ToolSpec | None:
        """Tier F (ORG-V3 §3b): send PUBLIC text (pages you fetched, the owner's public request) to a free-tier LLM
        for a summary, ranking or rough draft. Policy refuses private-data holders and PII tasks; this handler
        refuses personal data and the task's private strings. The answer is unverified, untrusted text."""
        cfg = self.cfg.org.get("free_llm") or {}
        if not cfg.get("enabled") or not cfg.get("providers"):
            return None
        max_chars = int(cfg.get("max_input_chars", 30000))

        async def call(args):
            import asyncio
            from . import free_llm
            instruction, text = str(args.get("instruction", "")).strip(), str(args.get("text", ""))
            if not instruction or not text.strip():
                return err("give an instruction and the public text to work on")
            if len(text) + len(instruction) > max_chars:
                return err(f"too long (max {max_chars} characters) — split it")
            if find_pii(instruction + "\n" + text):
                return err("personal data found — free external LLMs only get public text")
            with self.Session() as db:
                private = (db.get(Task, task_id).contract or {}).get("_private_strings", [])
            if any(p and p in text for p in private):
                return err("text contains this task's private details — not sent")
            try:
                ans = await asyncio.to_thread(free_llm.complete, list(cfg["providers"]), instruction, text,
                                              float(cfg.get("timeout_s", 60)))
            except free_llm.FreeLLMUnavailable as e:
                return err(f"no free LLM available ({e}) — do this step yourself")
            with self.Session() as db:
                db.add(AuditEvent(task_id=task_id, actor=emp.id, kind="free_llm",
                                  detail={"provider": ans.provider, "model": ans.model, "chars_in": len(text),
                                          "chars_out": len(ans.text), "instruction": instruction[:200]}))
                db.commit()
            ctx["untrusted"] = True
            return ok(untrusted("free_llm", f"{ans.provider}/{ans.model}", ans.text[:20_000]) +
                      "\nUnverified output of a free external model: check it against your sources, cite those sources, "
                      "and never paste it as your deliverable.")

        return ToolSpec("llm_free", "Cheap first pass on PUBLIC text with a free external model (summarise fetched pages, "
                        "rank candidates, rough draft). Never personal or private data. Output is unverified.",
                        {"type": "object", "properties": {"instruction": {"type": "string"}, "text": {"type": "string"}},
                         "required": ["instruction", "text"]}, call)

    def _skill_read_tool(self, route) -> ToolSpec:
        """Read-only access to the files of the skills loaded for this route (and its support skills), nothing else."""
        roots = {n: (SKILLS_DIR / n).resolve() for n in [*route.skills, *route.support]}

        async def read(args):
            root = roots.get(str(args.get("skill", "")))
            if root is None:
                return err(f"you may read only the skills loaded for this task: {sorted(roots)}")
            p = (root / str(args.get("path", "") or "")).resolve()
            if not p.is_relative_to(root) or not p.exists():
                return err("no such file in that skill")
            if p.is_dir():
                names = sorted(c.name + ("/" if c.is_dir() else "") for c in p.iterdir() if not c.name.startswith("."))
                return ok("\n".join(names[:300]) or "(empty folder)")
            if p.suffix.lower() not in SKILL_TEXT_SUFFIXES:
                return err("text files only")
            return ok(p.read_text(errors="replace")[:50_000])

        return ToolSpec("skill_read", "Read a file of a skill loaded for this task (path relative to the skill folder; "
                        "'' or a folder path lists it).",
                        {"type": "object", "properties": {"skill": {"type": "string"}, "path": {"type": "string"}},
                         "required": ["skill"]}, read)

    def _unobserved_citations(self, task_id: str, citations: list) -> list[str]:
        p = task_dir(task_id) / "sources.json"
        seen = json.loads(p.read_text()) if p.exists() else {}
        observed = set(seen.get("urls", [])) | set(seen.get("pointers", [])) | {f"memory:{m}" for m in seen.get("memory_ids", [])}
        arts = task_dir(task_id) / "artifacts"
        bad = []
        for c in citations:
            src = str(c.get("source", "")) if isinstance(c, dict) else str(c)
            if src.startswith("artifact://") and (arts / src.split("/")[-1]).exists():
                continue
            if src not in observed:
                bad.append(src)
        return bad

    def _add_source(self, task_id: str, kind: str, values: list[str]) -> None:
        p = task_dir(task_id) / "sources.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(p.read_text()) if p.exists() else {"urls": [], "memory_ids": [], "pointers": []}
        data[kind] = sorted(set(data.get(kind, [])) | set(values))
        p.write_text(json.dumps(data))

    def _common_tools(self, emp: Employee, task_id: str, pt: str, allowed_inputs: set[str], ctx: dict) -> list[ToolSpec]:
        art = task_dir(task_id) / "artifacts"
        art.mkdir(parents=True, exist_ok=True)
        prefix = f"{pt}-"

        async def ws_write(args):
            if len(str(args.get("content", ""))) > 2_000_000:
                return err("artifact too large (2 MB text limit) — split it (C33)")
            name = prefix + SAFE_NAME.sub("_", str(args["name"]).split("/")[-1]).removeprefix(prefix)[:100]
            (art / name).write_text(str(args["content"]))
            with self.Session() as db:
                db.add(AuditEvent(task_id=task_id, actor=emp.id, kind="artifact", detail={"name": name, "pt": pt}))
                db.commit()
            self.live.publish("artifact.created", task_id, employee_id=emp.id, name=name, step=pt)
            return ok(f"saved artifact://{task_id}/{name}")

        async def ws_read(args):
            ref = str(args["ref"])
            name = SAFE_NAME.sub("_", ref.split("/")[-1])
            allowed_names = {r.split("/")[-1] for r in allowed_inputs}
            if not (name.startswith(prefix) or name in allowed_names):
                return err("you may only read your own artifacts or the upstream ones listed in your prompt")
            p = art / name
            if not p.exists():
                return err("no such artifact")
            if not name.startswith(prefix):
                ctx["untrusted"] = True  # another employee's output (C13)
            return ok(untrusted("artifact", name, p.read_text(errors="replace")[:50_000]))

        async def mem_read(args):
            with self.Session() as db:
                rows = self.memory.read(db, emp, str(args.get("query", "")), show=db.get(Task, task_id).show)
                db.commit()
                ids = [m.id for m in rows]
                lines = [f"[{m.id}] {m.content}" for m in rows]
            self._add_source(task_id, "memory_ids", ids)
            return ok("\n".join(lines) or "nothing relevant")

        async def slack_post(args):
            with self.Session() as db:
                t = db.get(Task, task_id)
                self._post(t, emp, str(args["text"])[:3000])
            return ok("posted in the task thread")

        tools = [
            ToolSpec("workspace_write", f"Save an output artifact (text). Stored as {prefix}<name>.",
                     {"type": "object", "properties": {"name": {"type": "string"}, "content": {"type": "string"}}, "required": ["name", "content"]}, ws_write),
            ToolSpec("workspace_read", "Read an artifact by artifact:// ref (your own, or upstream refs listed in your prompt).",
                     {"type": "object", "properties": {"ref": {"type": "string"}}, "required": ["ref"]}, ws_read),
            ToolSpec("memory_read", "Search your permitted memory. Cite results as memory:<id>.",
                     {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}, mem_read),
        ]
        if "slack.post_own_thread" in emp.tools:
            tools.append(ToolSpec("slack_post", "Post a short progress note in the task thread.",
                                  {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}, slack_post))
        return tools

    # ------------------------------------------------------------------ pipeline (every pitch/application sent)
    def _pipeline_tools(self, emp: Employee, task_id: str) -> list[ToolSpec]:
        from .db import PipelineItem
        tools = []
        if "pipeline.read" in emp.tools:
            async def pread(args):
                q = str(args.get("query") or "").lower()
                with self.Session() as db:
                    rows = [r for r in db.scalars(select(PipelineItem).order_by(PipelineItem.sent_at.desc()))
                            if not q or q in f"{r.to} {r.subject} {r.kind} {r.status}".lower()][:40]
                    out = [{"id": r.id, "kind": r.kind, "to": r.to, "subject": r.subject, "status": r.status,
                            "sent": str(r.sent_at)[:10], "follow_up_due": str(r.follow_up_due)[:10] if r.follow_up_due else None,
                            "note": r.note, "body": r.body[:1500]} for r in rows]
                self._add_source(task_id, "pointers", [f"pipeline:{r['id']}" for r in out])
                return ok(untrusted("pipeline", "rows", json.dumps(out, indent=1)) if out else "pipeline is empty")
            tools.append(ToolSpec("pipeline_read", "Read your pitch/application pipeline (optional text filter). Cite rows as pipeline:<id>.",
                                  {"type": "object", "properties": {"query": {"type": "string"}}}, pread))
        if "pipeline.update" in emp.tools:
            async def pupdate(args):
                st = str(args.get("status", ""))
                if st not in PIPELINE_STATUSES:
                    return err(f"status must be one of {sorted(PIPELINE_STATUSES)}")
                with self.Session() as db:
                    r = db.get(PipelineItem, str(args.get("id")))
                    if r is None:
                        return err("no such pipeline row (rows are created only when something is actually sent)")
                    r.status, r.note = st, str(args.get("note") or r.note)[:2000]
                    if args.get("follow_up_due"):
                        try:
                            r.follow_up_due = datetime.fromisoformat(str(args["follow_up_due"])).replace(tzinfo=timezone.utc)
                        except ValueError:
                            return err("follow_up_due must be YYYY-MM-DD")
                    db.commit()
                return ok(f"{r.id} -> {st}")
            tools.append(ToolSpec("pipeline_update", "Set a pipeline row's status, note and next follow-up date.",
                                  {"type": "object", "properties": {"id": {"type": "string"}, "status": {"type": "string",
                                   "enum": sorted(PIPELINE_STATUSES)}, "note": {"type": "string"},
                                   "follow_up_due": {"type": "string"}}, "required": ["id", "status"]}, pupdate))
        return tools

    # ------------------------------------------------------------------ inbox (read-only)
    def _email_tools(self, emp: Employee, task_id: str) -> list[ToolSpec]:
        reader = self.email_reader

        async def elist(args):
            if not reader.configured():
                return err("no email connector configured (IMAP_HOST/IMAP_USER/IMAP_PASSWORD) — return blocked and tell the owner")
            hours = max(1, min(48, int(args.get("hours") or 24)))
            rows = reader.list_recent(hours)
            self._add_source(task_id, "pointers", [f"email_listed:{r['id']}" for r in rows])
            return ok(json.dumps(rows, indent=1) if rows else "no email in that window")

        async def eopen(args):
            if not reader.configured():
                return err("no email connector configured")
            m = reader.open(str(args.get("id")))
            self._add_source(task_id, "pointers", [f"email:{m['id']}"])
            return ok(untrusted("email", m["id"], json.dumps(m, indent=1)))
        return [ToolSpec("email_list", "List emails from the last N hours (headers only). Open EVERY one with email_open.",
                         {"type": "object", "properties": {"hours": {"type": "integer"}}}, elist),
                ToolSpec("email_open", "Open one email by id (read-only; never marks it read). Cite it as email:<id>.",
                         {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}, eopen)]

    # ------------------------------------------------------------------ uploads (your files, per scope)
    def _upload_tools(self, emp: Employee, task_id: str) -> list[ToolSpec]:
        from . import uploads
        scopes = uploads.scopes_for(self.cfg, emp)
        if not scopes:
            return []

        async def up_list(args):
            return ok("\n".join(f"{s}/{n}" for s in scopes for n in uploads.listing(s)) or "no files yet — ask the owner")

        async def up_read(args):
            scope, _, name = str(args.get("ref", "")).removeprefix("upload:").partition("/")
            if scope not in scopes:
                return err(f"you can't read '{scope}' files (yours: {scopes})")
            p = uploads.path(scope, name)
            if p is None:
                return err("no such file — ask the owner to add it (never invent its contents)")
            self._add_source(task_id, "pointers", [f"upload:{scope}/{p.name}"])
            try:
                text = p.read_bytes()[:200_000].decode("utf-8")
            except UnicodeDecodeError:
                return ok(f"{p.name} is a binary file ({p.stat().st_size} bytes) — import it into your project instead")
            return ok(untrusted("upload", f"{scope}/{p.name}", text))
        return [ToolSpec("uploads_list", f"List the owner's files you may use (scopes: {scopes}).", {"type": "object", "properties": {}}, up_list),
                ToolSpec("uploads_read", "Read a text file the owner uploaded: ref 'upload:<scope>/<name>'. Cite it as that ref.",
                         {"type": "object", "properties": {"ref": {"type": "string"}}, "required": ["ref"]}, up_read)]

    # ------------------------------------------------------------------ build tools (producers, designers, engineers)
    def _build_tools(self, emp: Employee, task_id: str, pt: str, allowed_inputs: set[str], ctx: dict) -> list[ToolSpec]:
        from . import runtime, uploads
        project = plan_task_dir(task_id, pt) / "project"
        show_dir = (self.cfg.shows.get(emp.show) or {}).get("dir") if emp.show else None
        runtime.seed_project(project, show_dir)
        work = "code" if "code.write" in emp.tools else "video"
        art = task_dir(task_id) / "artifacts"

        def inside(rel: str) -> Path | None:
            p = (project / rel).resolve()
            return p if str(p).startswith(str(project.resolve())) and "/.." not in rel else None

        async def pwrite(args):
            p = inside(str(args.get("path", "")))
            if p is None:
                return err("path must stay inside your project")
            if len(str(args.get("content", ""))) > 2_000_000:
                return err("file too large (2 MB text)")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(args.get("content", "")))
            return ok(f"wrote {p.relative_to(project)}")

        async def pread(args):
            p = inside(str(args.get("path", "")))
            if p is None or not p.exists():
                return err("no such file in your project")
            if p.is_dir():
                return ok("\n".join(sorted(x.name + ("/" if x.is_dir() else "") for x in p.iterdir()))[:6000])
            return ok(p.read_text(errors="replace")[:50_000])

        async def pimport(args):
            ref, dest = str(args.get("ref", "")), inside(str(args.get("dest", "")))
            if dest is None:
                return err("dest must stay inside your project")
            if ref.startswith("upload:"):
                scope, _, name = ref[7:].partition("/")
                if not uploads.can_read(self.cfg, emp, scope):
                    return err(f"you can't use '{scope}' files")
                src = uploads.path(scope, name)
            else:
                name = ref.split("/")[-1]
                src = art / name if name in {r.split("/")[-1] for r in allowed_inputs} else None
            if src is None or not src.exists():
                return err("not found, or not an input you were given — ask the owner for missing assets")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, dest)
            return ok(f"copied to {dest.relative_to(project)}")

        async def prun(args):
            dec = self._check(emp, task_id, "sandbox.exec", {"cost_usd": 0.0})
            if not dec.allowed:
                return err(f"denied by policy: {dec.reason}")
            try:
                argv = runtime.parse_command(str(args.get("command", "")), work, show_dir)
            except runtime.RuntimeError_ as e:
                return err(str(e))
            cwd = inside(str(args.get("cwd") or "."))
            if cwd is None or not cwd.is_dir():
                return err("cwd must be a folder inside your project")
            res = runtime.run(cwd, argv, timeout=int(args.get("timeout") or 900))
            with self.Session() as db:
                db.add(AuditEvent(task_id=task_id, actor=emp.id, kind="sandbox_exec",
                                  detail={"argv": argv, "exit": res.exit_code}))
                db.commit()
            return ok(f"exit {res.exit_code}\n{res.output}")

        async def pexport(args):
            p = inside(str(args.get("path", "")))
            if p is None or not p.is_file():
                return err("no such file in your project")
            name = f"{pt}-" + SAFE_NAME.sub("_", str(args.get("name") or p.name)).removeprefix(f"{pt}-")[:100]
            if p.stat().st_size > 500 * 1024 * 1024:
                return err("file too large (500 MB)")
            shutil.copy(p, art / name)
            with self.Session() as db:
                db.add(AuditEvent(task_id=task_id, actor=emp.id, kind="artifact", detail={"name": name, "pt": pt}))
                db.commit()
            return ok(f"saved artifact://{task_id}/{name}")

        tools = [
            ToolSpec("project_write", "Write a text file in your sandbox project (path relative to it).",
                     {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                      "required": ["path", "content"]}, pwrite),
            ToolSpec("project_read", "Read a file, or list a folder, in your sandbox project.",
                     {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, pread),
            ToolSpec("project_import", "Copy an upstream artifact (artifact://… listed in your prompt) or an owner upload "
                     "(upload:<scope>/<name>) into your project.",
                     {"type": "object", "properties": {"ref": {"type": "string"}, "dest": {"type": "string"}},
                      "required": ["ref", "dest"]}, pimport),
            ToolSpec("run_command", "Run ONE allowlisted command in your project (no shell). Video: npx hyperframes@<v> "
                     "<init|check|snapshot|render|…>, python3 core/reel.py <your-show> <new|assets|build|data|sfx>. "
                     "Code: npm test|ci|install|run build, node, python3 -m pytest.",
                     {"type": "object", "properties": {"command": {"type": "string"}, "cwd": {"type": "string"},
                                                       "timeout": {"type": "integer"}}, "required": ["command"]}, prun),
            ToolSpec("export_output", "Save a finished file from your project (e.g. the MP4) as your output artifact.",
                     {"type": "object", "properties": {"path": {"type": "string"}, "name": {"type": "string"}},
                      "required": ["path"]}, pexport),
        ]
        if "voice.synthesize" in emp.tools:
            tools.append(self._voice_tool(emp, task_id, project, inside))
        return tools

    def _voice_tool(self, emp: Employee, task_id: str, project: Path, inside) -> ToolSpec:
        """The voice is chosen by the Dispatcher from the show — the employee can't pick another (I5)."""
        from . import runtime
        spec = self.cfg.shows.get(emp.show) or {}
        base = self.cfg.org["runtime"].get("default_base_voice", {})
        kind = spec.get("voice", "base") if emp.show else "base"
        engine = spec.get("voice_engine") or base.get("engine", "kokoro")
        voice_id = spec.get("voice_id") or (None if emp.show else base.get("voice_id"))
        show_dir = ROOT / spec.get("dir", "") if emp.show else None
        settings = {}
        if show_dir is not None and (show_dir / "voice" / "VOICE.json").exists():
            try:
                settings = json.loads((show_dir / "voice" / "VOICE.json").read_text())
            except json.JSONDecodeError:
                settings = {}
        reference = (show_dir / "voice" / "reference" / "prompt.wav") if kind == "owner_clone" else None

        async def speak(args):
            dec = self._check(emp, task_id, "voice.synthesize", {"voice": kind, "cost_usd": 0.0})
            if not dec.allowed:
                return err(f"denied by policy: {dec.reason}")
            if kind == "owner_clone" and not (show_dir / "voice" / "reference" / "CONSENT.md").exists():
                return err("the owner's consent record (voice/reference/CONSENT.md) is missing — return blocked and ask")
            out = inside(str(args.get("out", "")))
            if out is None or out.suffix.lower() != ".wav":
                return err("out must be a .wav path inside your project")
            ok_, msg = runtime.synthesize(str(args.get("text", "")), engine, voice_id, out, reference, settings)
            with self.Session() as db:
                db.add(AuditEvent(task_id=task_id, actor=emp.id, kind="voice",
                                  detail={"engine": engine, "voice": kind, "ok": ok_, "note": msg[:200]}))
                db.commit()
            return ok(f"wrote {out.relative_to(project)} ({msg})") if ok_ else err(msg + " — return blocked and tell the owner")
        return ToolSpec("voice_line", f"Speak one line in this show's voice ({engine}{' ' + voice_id if voice_id else ''}) "
                        "into a .wav in your project. [pause N] adds a pause.",
                        {"type": "object", "properties": {"text": {"type": "string"}, "out": {"type": "string"}},
                         "required": ["text", "out"]}, speak)

    def _act_tool(self, emp: Employee, task_id: str) -> ToolSpec:
        """Generic connector action. R2/R3 never execute here: they must go in pending_actions."""
        internal = set(TOOL_ACTIONS.values()) | {"web.search", "web.fetch", "cos.request", "delegate"}

        async def act(args):
            action, params = str(args.get("action")), dict(args.get("params") or {})
            if action in internal or action.startswith(("workspace.", "memory.", "slack.")):
                return err(f"'{action}' isn't a business tool — use the dedicated tool for it (C27)")
            dec = self._check(emp, task_id, action, params)
            if dec.outcome == APPROVAL:
                return err(f"'{action}' needs owner approval ({dec.tier}: {dec.reason}). Don't retry — add it to "
                           "pending_actions in your return packet with an exact preview.")
            if not dec.allowed:
                return err(f"denied: {dec.reason}")
            return err(f"'{action}' is permitted but no connector is configured for it yet. Say so in open_questions "
                       "and do not invent its result.")
        return ToolSpec("act", "Use a business tool from your allowlist, e.g. {action:'crm.read', params:{...}}.",
                        {"type": "object", "properties": {"action": {"type": "string"}, "params": {"type": "object"}},
                         "required": ["action"]}, act)

    def _submit_return_tool(self, emp: Employee, task_id: str, pt: str, sink: dict, ctx: dict) -> ToolSpec:
        prefix = f"{pt}-"

        async def handler(args):
            rp = {"task_id": task_id, "from": emp.id, **normalize_ids(args)}
            rp.setdefault("self_check", [])
            rp.setdefault("confidence", 0.5)
            rp.setdefault("outputs", [])
            if rp.get("status") not in ("done", "partial", "blocked", "out_of_scope"):
                return err("status must be done, partial, blocked or out_of_scope")
            names = [str(o).split("/")[-1] for o in rp["outputs"]]
            if not all(str(o).startswith("artifact://") for o in rp["outputs"]):
                return err("outputs must be artifact:// refs")
            if any(not n.startswith(prefix) for n in names):
                return err(f"outputs must be your own artifacts ({prefix}*) — never another employee's")
            missing = [n for n in names if not (task_dir(task_id) / "artifacts" / n).exists()]
            if missing:
                return err(f"outputs not found (write them first): {missing}")
            if rp["status"] in ("done", "partial") and not names:
                return err("a done/partial return needs at least one output artifact")
            with self.Session() as db:
                approved_tiers = set(db.get(Task, task_id).contract.get("planned_actions_tiers") or [])
            bad = validate_pending_actions(self.cfg, emp, rp.get("pending_actions") or [], approved_tiers)
            if bad:
                return err("pending_actions rejected: " + "; ".join(bad))
            unknown = self._unobserved_citations(task_id, rp.get("citations") or [])
            if unknown:   # C44: fix citations in-session instead of burning a harness attempt
                return err(f"These citations weren't observed in this task: {unknown}. Use only owner:request, contract, "
                           f"handoff:{pt}, artifact:// refs you read, memory:<id> you read, or URLs you fetched — or drop "
                           "the claim.")
            shape = return_packet_problems({**rp, "memory_candidates": []})
            if shape:   # L1: fix the form now, in this session, instead of burning a harness attempt
                return err("Return packet malformed: " + shape + ". Fix it and call submit_return again.")
            with self.Session() as db:
                t = db.get(Task, task_id)
                for mc in rp.get("memory_candidates") or []:
                    mc = mc if isinstance(mc, dict) else {"content": str(mc)}
                    if mc.get("content"):
                        self.memory.submit_candidate(db, emp, t, mc["content"], kind=mc.get("kind") or "feedback",
                                                     layer=mc.get("layer") if mc.get("layer") in ("L1", "L3") else "L3",
                                                     pointer=mc.get("pointer"),
                                                     derived_from_untrusted=bool(ctx.get("untrusted")))
                db.commit()
            rp["memory_candidates"] = []  # stored as typed rows
            sink["return"] = rp
            return ok("Return packet stored. Stop here.")
        schema = {"type": "object", "properties": {
            "status": {"type": "string", "enum": ["done", "partial", "blocked", "out_of_scope"]},
            "outputs": {"type": "array", "items": {"type": "string"}}, "summary": {"type": "string"},
            "citations": {"type": "array", "items": {"type": "object", "properties": {
                "claim": {"type": "string"}, "source": {"type": "string"}}, "required": ["claim", "source"]}},
            "self_check": {"type": "array", "items": {"type": "object", "properties": {
                "criterion_id": {"type": "string"}, "result": {"type": "string", "enum": ["met", "not_met", "unverifiable"]},
                "evidence": {"type": "string"}}, "required": ["criterion_id", "result", "evidence"]}},
            "confidence": {"type": "number"}, "open_questions": {"type": "array", "items": {"type": "string"}},
            "pending_actions": {"type": "array", "items": {"type": "object"}},
            "memory_candidates": {"type": "array", "items": {"type": "object"}}},
            "required": ["status", "outputs", "self_check", "confidence"]}
        return ToolSpec("submit_return", "Submit your return packet (once). Use status blocked + open_questions "
                        "instead of guessing.", schema, handler)


def return_packet_problems(rp: dict) -> str:
    import jsonschema
    from .checks import _return_schema
    try:
        jsonschema.validate(rp, _return_schema())
    except jsonschema.ValidationError as e:
        where = "/".join(str(p) for p in e.absolute_path) or "packet"
        return f"{where}: {e.message}"
    return ""
