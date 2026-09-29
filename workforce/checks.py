"""Deterministic verification checks run by the agent-harness controller (config/checks.yaml).

    python -m workforce.checks <check> <args...>

Exit 0 = pass, 1 = fail, 3 = check not available in this environment (counts as a failure in the
harness, so a task can never pass on a check that didn't really run).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

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
    text = _read(path)
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


def link_check(path: str) -> int:
    import httpx
    urls = sorted(set(re.findall(r"https?://[^\s)>\]\"']+", _read(path))))
    bad = []
    for u in urls[:30]:
        try:
            resp = httpx.head(u, follow_redirects=True, timeout=10)
            if resp.status_code >= 400:
                resp = httpx.get(u, follow_redirects=True, timeout=10)
            if resp.status_code >= 400:
                bad.append((u, resp.status_code))
        except httpx.HTTPError as e:
            bad.append((u, type(e).__name__))
    if bad:
        print(f"FAIL broken links: {bad[:5]}")
        return FAIL
    print(f"{len(urls)} link(s) ok")
    return PASS


def image_spec(path: str, spec: str = "{}") -> int:
    try:
        from PIL import Image
    except ImportError:
        print("UNAVAILABLE Pillow not installed")
        return UNAVAILABLE
    s = json.loads(spec) if spec.strip().startswith("{") else json.loads(_read(spec))
    with Image.open(path) as im:
        w, h, fmt = im.width, im.height, (im.format or "").lower()
    errs = []
    if s.get("width") and w != s["width"]:
        errs.append(f"width {w}!={s['width']}")
    if s.get("height") and h != s["height"]:
        errs.append(f"height {h}!={s['height']}")
    if s.get("format") and fmt != s["format"].lower():
        errs.append(f"format {fmt}!={s['format']}")
    if s.get("max_bytes") and Path(path).stat().st_size > s["max_bytes"]:
        errs.append("file too large")
    if errs:
        print("FAIL " + "; ".join(errs))
        return FAIL
    print(f"ok {w}x{h} {fmt}")
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


def brand_colors(path: str) -> int:
    kit = ROOT / "company" / "brand-kit.json"
    if not kit.exists():
        print("UNAVAILABLE brand kit not added yet")
        return UNAVAILABLE
    print("UNAVAILABLE brand color check not implemented until the brand kit format is known")
    return UNAVAILABLE


def web_audit_scores(url: str) -> int:
    if not shutil.which("lighthouse"):
        print("UNAVAILABLE lighthouse not installed")
        return UNAVAILABLE
    if urlparse(url).scheme not in ("http", "https"):
        print("FAIL not a URL")
        return FAIL
    out = subprocess.run(["lighthouse", url, "--quiet", "--output=json", "--chrome-flags=--headless"],
                         capture_output=True, text=True, timeout=300)
    cats = json.loads(out.stdout or "{}").get("categories", {})
    low = {k: v.get("score") for k, v in cats.items() if (v.get("score") or 0) < 0.8}
    if low:
        print(f"FAIL scores below 0.8: {low}")
        return FAIL
    print("ok all categories >= 0.8")
    return PASS


CHECKS = {f.__name__: f for f in [deliverable_only, packet_schema, criteria_covered, pii_absent, no_ai_tells, spellcheck,
                                  char_limits, json_valid, citations_resolve, link_check, image_spec,
                                  video_spec, brand_colors, web_audit_scores]}


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
