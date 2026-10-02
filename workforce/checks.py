"""Deterministic verification checks run by the agent-harness controller (config/checks.yaml).

    python -m workforce.checks <check> <args...>

Exit 0 = pass, 1 = fail, 3 = check not available in this environment (counts as a failure in the
harness, so a task can never pass on a check that didn't really run).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .config import ROOT  # honours WORKFORCE_ROOT when installed as a package
SCHEMAS = ROOT / "schemas"
PASS, FAIL, UNAVAILABLE = 0, 1, 3

AI_TELLS = [
    r"\bdelve\b", r"\btapestry\b", r"\btestament to\b", r"\bin today's (fast-paced|digital)\b",
    r"\bnot (just|only) [^.]{1,40}, but\b", r"\bit'?s not about\b[^.]{1,60}\bit'?s about\b",
    r"\bgame[- ]changer\b", r"\bunlock(s|ing)? the (power|potential)\b", r"\belevate your\b",
    r"\bseamless(ly)?\b", r"\bin conclusion\b", r"\bnavigat(e|ing) the (complex|ever)", r"\blet'?s dive in\b",
    r"\bI hope this (email|message) finds you well\b", r"\bharness the power\b", r"\bever-evolving\b",
]
CHAR_LIMITS = {"linkedin": 3000, "x": 280, "twitter": 280, "instagram": 2200, "email_subject": 78,
               "sms": 160, "slack": 4000}


def _read(path: str) -> str:
    return Path(path).read_text(errors="replace")


def _return_schema() -> dict:
    rp = json.loads((SCHEMAS / "return_packet.json").read_text())
    rp["properties"]["memory_candidates"]["items"] = json.loads((SCHEMAS / "memory_entry.json").read_text())
    return rp


def packet_schema(return_packet: str) -> int:
    import jsonschema
    try:
        jsonschema.validate(json.loads(_read(return_packet)), _return_schema())
    except (jsonschema.ValidationError, json.JSONDecodeError) as e:
        print(f"FAIL return packet invalid: {str(e).splitlines()[0]}")
        return FAIL
    print("return packet valid")
    return PASS


def criteria_covered(handoff: str, return_packet: str) -> int:
    h, r = json.loads(_read(handoff)), json.loads(_read(return_packet))
    got = {str(c.get("criterion_id")): c for c in r.get("self_check", []) if isinstance(c, dict)}
    crit = [str(c) for c in h.get("criteria", [])]
    missing = [c for c in crit if c not in got]
    unmet = [c for c in crit if c in got and got[c].get("result") not in ("met", "unverifiable")]
    no_evidence = [c for c in crit if c in got and got[c].get("result") == "met"
                   and not str(got[c].get("evidence") or "").strip()]
    if missing or unmet or no_evidence:
        print(f"FAIL missing={missing} not_met={unmet} met_without_evidence={no_evidence}")
        return FAIL
    print(f"all {len(crit)} criteria covered with evidence")
    return PASS


def pii_absent(*paths: str) -> int:
    from .pii import find_pii
    files = [f for p in paths for f in ([Path(p)] if Path(p).is_file() else sorted(Path(p).rglob("*")) if Path(p).is_dir() else [])
             if f.is_file() and f.suffix.lower() in ("", ".txt", ".md", ".json", ".html", ".csv", ".srt", ".vtt")]
    hits = [(str(f), k) for f in files for k, _ in find_pii(_read(str(f)))]
    if hits:
        print(f"FAIL personal data found: {hits[:5]}")
        return FAIL
    print("no personal data found")
    return PASS


def no_ai_tells(path: str) -> int:
    text = _read(path)
    hits = [p for p in AI_TELLS if re.search(p, text, re.I)]
    words = max(1, len(text.split()))
    dashes = text.count("—")
    if dashes / words > 1 / 60:
        hits.append(f"em-dash density {dashes}/{words} words")
    if len(hits) >= 2:
        print(f"FAIL AI tells: {hits}")
        return FAIL
    print(f"ok ({len(hits)} minor tell(s))")
    return PASS


META = re.compile(r"^\s*(#+\s*)?(\(?draft\)?|gaps?|notes?|todo|assumptions?|open questions?|metadata|"
                  r"character count|word count|rationale|options?)\s*[:\-—]?\s*$|\((draft|placeholder)\)", re.I | re.M)


def deliverable_only(path: str) -> int:
    """C45: the deliverable file holds the deliverable, not working notes."""
    p = Path(path)
    if not p.is_file():
        print("FAIL missing file")
        return FAIL
    try:
        text = p.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        print("binary deliverable — not applicable")
        return PASS
    hits = [m.group(0).strip() for m in META.finditer(text)]
    if hits:
        print(f"FAIL working notes inside the deliverable: {hits[:5]} — move them to summary/open_questions")
        return FAIL
    print("deliverable only")
    return PASS


def spellcheck(path: str) -> int:
    try:
        from spellchecker import SpellChecker
    except ImportError:
        print("UNAVAILABLE pyspellchecker not installed")
        return UNAVAILABLE
    text = re.sub(r"https?://\S+|\S+@\S+\.\w+", " ", _read(path))   # links and addresses aren't words
    if re.search(r"\b(TODO|lorem ipsum|\[INSERT|\{\{)", text, re.I):
        print("FAIL placeholder text left in")
        return FAIL
    if re.search(r"\b(\w+) \1\b", text, re.I):
        print("FAIL repeated word")
        return FAIL
    sc = SpellChecker()
    custom = ROOT / "config" / "dictionary.txt"
    if custom.exists():
        sc.word_frequency.load_words([w.strip().lower() for w in custom.read_text().split() if w.strip()])
    words = [w.lower() for w in re.findall(r"\b[a-zA-Z][a-z]{3,}\b", text)]  # skip Capitalized names/acronyms? lowercase only
    unknown = sorted(sc.unknown(words))
    if words and len(unknown) / len(set(words)) > 0.03:
        print(f"FAIL {len(unknown)} unknown words: {unknown[:15]} (add real terms to config/dictionary.txt)")
        return FAIL
    print(f"ok ({len(unknown)} unknown: {unknown[:5]})")
    return PASS


def char_limits(path: str, platform: str = "") -> int:
    lim = CHAR_LIMITS.get(platform.lower())
    n = len(_read(path))
    if lim and n > lim:
        print(f"FAIL {n} chars > {platform} limit {lim}")
        return FAIL
    print(f"ok ({n} chars{'' if not lim else f' / {lim}'})")
    return PASS


def json_valid(path: str, schema: str = "") -> int:
    try:
        data = json.loads(_read(path))
    except json.JSONDecodeError as e:
        print(f"FAIL invalid JSON: {e}")
        return FAIL
    if schema:
        import jsonschema
        try:
            jsonschema.validate(data, json.loads(_read(schema)))
        except jsonschema.ValidationError as e:
            print(f"FAIL schema: {str(e).splitlines()[0]}")
            return FAIL
    print("valid JSON")
    return PASS


def citations_resolve(return_packet: str, sources: str, artifacts_dir: str = "") -> int:
    """A citation counts only if its source was actually observed in this task: a URL the Dispatcher
    fetched, a memory id / connector pointer the Dispatcher returned, or an artifact that exists."""
    r = json.loads(_read(return_packet))
    seen = json.loads(_read(sources)) if Path(sources).exists() else {}
    observed = set(seen.get("urls", [])) | set(seen.get("pointers", [])) | set(seen.get("memory_ids", []))
    bad = []
    for c in r.get("citations", []):
        src = str(c.get("source", ""))
        if src.startswith("artifact://"):
            name = src.split("/")[-1]
            if not (artifacts_dir and (Path(artifacts_dir) / name).exists()):
                bad.append(src)
        elif src.startswith("memory:") and src.removeprefix("memory:") in observed:
            continue
        elif src not in observed:
            bad.append(src)
    if bad:
        print(f"FAIL unresolvable citations: {bad[:5]}")
        return FAIL
    print(f"{len(r.get('citations', []))} citation(s) resolve")
    return PASS


def link_check(path: str, sources: str = "") -> int:
    """Links must resolve. URLs already fetched in this task are proven reachable; a proxy/network error is
    'couldn't check' (UNAVAILABLE), never 'broken'; only HTTP >= 400 or an unknown host is a broken link."""
    import httpx
    fetched = set(json.loads(_read(sources)).get("urls", [])) if sources and Path(sources).exists() else set()
    urls = sorted(set(re.findall(r"https?://[^\s)>\]\"']+", _read(path))) - fetched)
    bad, unreachable = [], []
    for u in urls[:30]:
        try:
            resp = httpx.head(u, follow_redirects=True, timeout=10)
            if resp.status_code >= 400:
                resp = httpx.get(u, follow_redirects=True, timeout=10)
            if resp.status_code >= 400:
                bad.append((u, resp.status_code))
        except (httpx.ProxyError, httpx.TimeoutException) as e:
            unreachable.append((u, type(e).__name__))
        except httpx.HTTPError as e:
            bad.append((u, type(e).__name__))
    if bad:
        print(f"FAIL broken links: {bad[:5]}")
        return FAIL
    if unreachable:
        print(f"UNAVAILABLE network/proxy blocked link checks: {unreachable[:5]}")
        return UNAVAILABLE
    print(f"{len(urls)} link(s) ok ({len(fetched)} already fetched this task)")
    return PASS


def video_spec(path: str, spec: str = "{}") -> int:
    if not shutil.which("ffprobe"):
        print("UNAVAILABLE ffprobe not installed (runs in the Modal render sandbox)")
        return UNAVAILABLE
    s = json.loads(spec) if spec.strip().startswith("{") else json.loads(_read(spec))
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
                          "-of", "json", path], capture_output=True, text=True, timeout=60)
    info = json.loads(out.stdout or "{}")
    dur = float(info.get("format", {}).get("duration", 0))
    streams = info.get("streams", [])
    v = next((x for x in streams if x.get("codec_type") == "video"), {})
    if not v or dur <= 0:
        print("FAIL not a playable video (no video stream / zero duration)")
        return FAIL
    errs = []
    if s.get("duration_s") and abs(dur - s["duration_s"]) > s.get("tolerance_s", 0.5):
        errs.append(f"duration {dur:.1f}s != {s['duration_s']}s")
    if s.get("width") and v.get("width") != s["width"]:
        errs.append(f"width {v.get('width')}")
    if s.get("height") and v.get("height") != s["height"]:
        errs.append(f"height {v.get('height')}")
    if s.get("audio") and not any(x.get("codec_type") == "audio" for x in streams):
        errs.append("no audio track")
    if errs:
        print("FAIL " + "; ".join(errs))
        return FAIL
    print(f"ok {dur:.1f}s {v.get('width')}x{v.get('height')}")
    return PASS


def sandbox_tests(plan_task_dir: str) -> int:
    """Runs the engineer's own tests on the runtime (Modal in production). Code with no tests fails."""
    from . import runtime
    project = Path(plan_task_dir) / "project"
    if not runtime.available("sandbox"):
        print("UNAVAILABLE no code runtime configured")
        return UNAVAILABLE
    cmd = runtime.test_command(project) if project.exists() else None
    if not cmd:
        print("FAIL no tests found (package.json 'test' script or test_*.py) — code must ship with tests")
        return FAIL
    res = runtime.run(project, cmd, timeout=900)
    print(res.output[-1500:])
    return PASS if res.exit_code == 0 else (UNAVAILABLE if res.exit_code == 3 else FAIL)


def hyperframes_check(plan_task_dir: str) -> int:
    from . import runtime
    if not runtime.available("render"):
        print("UNAVAILABLE no render runtime configured")
        return UNAVAILABLE
    proj = runtime.find_hf_project(Path(plan_task_dir) / "project")
    if proj is None:
        print("FAIL no HyperFrames project (hyperframes.json) in your sandbox")
        return FAIL
    ver = os.environ.get("HYPERFRAMES_VERSION", "0.8.91")
    res = runtime.run(proj, ["npx", "-y", f"hyperframes@{ver}", "check"], timeout=900)
    print(res.output[-2500:])
    return PASS if res.exit_code == 0 else (UNAVAILABLE if res.exit_code == 3 else FAIL)


SPEC_FIELDS = ("id", "name", "department", "kind", "does", "does_not", "fire_when", "tools", "max_tier",
               "personality", "routes", "context", "probation_tasks", "pitch")


def employee_spec(path: str) -> int:
    """Mason (architect): the proposal must be a valid, safe employee spec. It is never applied automatically."""
    import yaml
    from .config import Config
    try:
        spec = yaml.safe_load(_read(path))
    except yaml.YAMLError as e:
        print(f"FAIL not YAML: {str(e).splitlines()[0]}")
        return FAIL
    if not isinstance(spec, dict):
        print("FAIL spec must be a YAML mapping")
        return FAIL
    from .config import SKILLS_DIR
    from .routing import skill_path
    cfg = Config()
    errs = [f"missing {f}" for f in SPEC_FIELDS if f not in spec]
    if spec.get("id") in cfg.employees:
        errs.append(f"id {spec.get('id')} already exists")
    if spec.get("department") not in cfg.org["departments"]:
        errs.append(f"department must be one of {sorted(cfg.org['departments'])}")
    if spec.get("kind") != "specialist":
        errs.append("new employees are specialists only")
    if spec.get("max_tier") not in ("R0", "R1", "R2"):
        errs.append("max_tier must be R0, R1 or R2 (never R3/R4)")
    tools = spec.get("tools") or []
    actions = cfg.permissions["actions"]
    for t in tools:
        tier = actions.get(t)
        if tier is None:
            errs.append(f"unknown tool {t}")
        elif tier in ("R3", "R4"):
            errs.append(f"tool {t} is {tier} — not allowed for a new employee")
        elif cfg.restricted_kind(t) not in (None, "specialist"):
            errs.append(f"tool {t} is restricted to kind {cfg.restricted_kind(t)}")
    if "web.fetch" in tools and set(tools) & cfg.private_data_tools:
        errs.append("web.fetch together with private-data tools")
    bound = spec.get("show") or spec.get("lane")
    if spec.get("show") and spec.get("lane"):
        errs.append("bind to one show OR one lane, not both")
    if spec.get("new_lane"):
        nl = spec["new_lane"]
        if not spec.get("lane") or spec["lane"] in cfg.shows:
            errs.append("new_lane needs a new, unused lane name in `lane`")
        if not isinstance(nl, dict) or not nl.get("triggers"):
            errs.append("new_lane needs triggers (the words that name this project)")
    elif bound and bound not in cfg.shows:
        errs.append(f"unknown show/lane {bound} (a new coding project needs new_lane)")
    for sk in spec.get("support") or []:
        if not (SKILLS_DIR / str(sk) / "SKILL.md").exists():
            errs.append(f"support skill {sk} not installed")
    existing = {tt for eid in cfg.employees for tt in cfg.routes(eid)}
    new_skills = {str(k) for k in (spec.get("new_skills") or {})}
    for r in spec.get("routes") or []:
        if not isinstance(r, dict) or not r.get("task_type"):
            errs.append("each route needs task_type")
            continue
        if r["task_type"] in existing:
            errs.append(f"task_type {r['task_type']} is already owned by another employee (I2)")
        for sk in r.get("run") or []:
            if sk not in new_skills and not skill_path(sk).exists():
                errs.append(f"route {r['task_type']}: skill {sk} not installed and not in new_skills")
        for c in r.get("checks") or []:
            if c not in cfg.checks["checks"]:
                errs.append(f"route {r['task_type']}: unknown check {c}")
        if not r.get("checks"):
            errs.append(f"route {r['task_type']}: needs at least one check")
    if len(spec.get("probation_tasks") or []) != 3:
        errs.append("exactly 3 probation_tasks")
    if errs:
        print("FAIL " + "; ".join(errs[:10]))
        return FAIL
    print(f"employee spec {spec['id']} valid (proposal only — the owner activates it by editing config)")
    return PASS


MAKE_MARKERS = re.compile(r"make\.com|integromat|\"module\"\s*:\s*\"[\w-]+:[\w-]+", re.I)


def _is_pa(d) -> bool:
    if not isinstance(d, dict):
        return False
    defin = d.get("definition") or (d.get("properties") or {}).get("definition")
    return isinstance(defin, dict) and ("triggers" in defin or "actions" in defin)


def power_automate_only(path: str) -> int:
    """Byte-Co builds Power Automate flows only: a Logic Apps definition with no other platform inside."""
    text = _read(path)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"FAIL not JSON: {e}")
        return FAIL
    if not _is_pa(data):
        print("FAIL not a Power Automate / Logic Apps definition (needs definition.triggers/actions)")
        return FAIL
    if MAKE_MARKERS.search(text):
        print("FAIL Make.com content inside a Power Automate deliverable")
        return FAIL
    print("power_automate only")
    return PASS


STORYBOARD_MEDIA = {"photo", "logo", "cam", "clip", "screenshot", "audio"}


def storyboard_spec(path: str) -> int:
    """A designer's storyboard: every beat says its line, shows something, moves with intent; every media
    element points at a requested asset and every requested asset is used (the builder invents nothing)."""
    try:
        sb = json.loads(_read(path))
    except json.JSONDecodeError as e:
        print(f"FAIL not JSON: {e}")
        return FAIL
    beats = sb.get("beats") if isinstance(sb, dict) else None
    if not isinstance(beats, list) or not beats:
        print("FAIL storyboard needs a non-empty beats[]")
        return FAIL
    assets = {a.get("id"): a for a in sb.get("assets") or [] if isinstance(a, dict)}
    errs, used, ids = [], set(), set()
    for i, b in enumerate(beats, 1):
        if not isinstance(b, dict):
            errs.append(f"beat {i} is not an object")
            continue
        bid = b.get("id") or f"#{i}"
        if bid in ids:
            errs.append(f"duplicate beat id {bid}")
        ids.add(bid)
        for f in ("say", "scene", "motion"):
            if not str(b.get(f, "")).strip():
                errs.append(f"beat {bid}: {f} missing")
        els = b.get("elements") or []
        if not els:
            errs.append(f"beat {bid}: no elements (no beat is text alone or empty)")
        for e in els:
            if isinstance(e, dict) and e.get("kind") in STORYBOARD_MEDIA:
                if e.get("ref") not in assets:
                    errs.append(f"beat {bid}: {e.get('kind')} '{e.get('ref')}' is not in assets[]")
                used.add(e.get("ref"))
    for aid, a in assets.items():
        if not str(a.get("what", "")).strip():
            errs.append(f"asset {aid}: what missing")
    unused = sorted(set(assets) - used - {"voiceover", "music", "crowd"})
    if unused:
        errs.append(f"assets never used by a beat: {unused}")
    if errs:
        print("FAIL " + "; ".join(errs[:12]))
        return FAIL
    print(f"storyboard ok: {len(beats)} beat(s), {len(assets)} asset(s)")
    return PASS


def post_ready(path: str) -> int:
    """The poster's post.json: one account, one rendered video, the writer's caption within Instagram's limits."""
    try:
        post = json.loads(_read(path))
    except json.JSONDecodeError as e:
        print(f"FAIL not JSON: {e}")
        return FAIL
    errs = []
    if not isinstance(post, dict):
        print("FAIL post.json must be an object")
        return FAIL
    if not str(post.get("account", "")).startswith("@"):
        errs.append("account must be an @handle")
    if not str(post.get("video", "")).lower().endswith(".mp4"):
        errs.append("video must be the rendered .mp4")
    cap = str(post.get("caption", ""))
    if not cap.strip():
        errs.append("caption missing")
    if len(cap) > CHAR_LIMITS["instagram"]:
        errs.append(f"caption {len(cap)} chars > 2200")
    tags = re.findall(r"(?<!\w)#\w+", cap)
    if len(tags) > 5:
        errs.append(f"{len(tags)} hashtags > 5 (Instagram's cap)")
    if errs:
        print("FAIL " + "; ".join(errs))
        return FAIL
    print(f"post ready for {post['account']}")
    return PASS


def inbox_coverage(return_packet: str, sources: str) -> int:
    """The scanner must open every email it listed — no skipping by subject line."""
    seen = json.loads(_read(sources)) if Path(sources).exists() else {}
    ptr = set(seen.get("pointers", []))
    listed = {p.split(":", 1)[1] for p in ptr if p.startswith("email_listed:")}
    opened = {p.split(":", 1)[1] for p in ptr if p.startswith("email:")}
    missing = sorted(listed - opened)
    if missing:
        print(f"FAIL {len(missing)} email(s) listed but never opened: {missing[:10]}")
        return FAIL
    print(f"all {len(listed)} email(s) opened")
    return PASS


CHECKS = {f.__name__: f for f in [power_automate_only, storyboard_spec, post_ready, inbox_coverage, hyperframes_check, sandbox_tests, employee_spec, deliverable_only, packet_schema, criteria_covered, pii_absent, no_ai_tells, spellcheck,
                                  char_limits, json_valid, citations_resolve, link_check, video_spec]}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in CHECKS:
        print(f"usage: python -m workforce.checks <{'|'.join(CHECKS)}> args...")
        return 2
    try:
        return CHECKS[argv[0]](*argv[1:])
    except FileNotFoundError as e:
        print(f"FAIL missing file: {e.filename}")
        return FAIL


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
