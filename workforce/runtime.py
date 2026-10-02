"""Execution runtime for employees that build things: video/design producers and engineers.

Nothing an employee writes ever runs as a shell on the Dispatcher. The employee gets a per-plan-task
project folder (`{T}/project`) and three narrow tools (write/read files, run ONE allowlisted command,
synthesize a voice line). Commands are parsed (no shell), matched against an allowlist for the
employee's kind of work, and run by a backend:

  RUNTIME_BACKEND=remote  production: the project is shipped to a runtime service and results are copied back.
                          The service is deploy/runtime_server.py (self-hosted, e.g. on the Oracle box) or
                          deploy/modal_app.py (Modal). Both speak the same /exec and /voice API and hold no credentials.
                          RUNTIME_URL + RUNTIME_TOKEN locate it. (RUNTIME_BACKEND=modal with MODAL_RUNTIME_* still works.)
  RUNTIME_BACKEND=local   development/testing only: runs on this machine in the project folder with an
                          empty environment and a timeout. Never enable on a server with secrets.
  (unset)                 no runtime: routes that need it are refused at contract time.

Voices are Kokoro base voices only (never a clone). They run on the runtime service. For local testing
VOICE_DEV_ENGINE=espeak substitutes espeak-ng and marks the output as a DEV voice.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path

from .config import ROOT

HYPERFRAMES_SUBCOMMANDS = {"check", "lint", "validate", "snapshot", "render", "init", "add", "catalog", "info",
                           "compositions", "timeline", "inspect", "keyframes", "beats", "compare", "docs"}
REEL_SUBCOMMANDS = {"new", "assets", "voicetext", "build", "data", "sfx"}
MAX_OUT = 6000


class RuntimeError_(Exception):
    pass


@dataclass
class ExecResult:
    exit_code: int
    output: str


def backend() -> str:
    return os.environ.get("RUNTIME_BACKEND", "").strip().lower()


def available(kind: str) -> bool:
    """kind: render | sandbox | voice."""
    b = backend()
    if b in ("remote", "modal"):
        return bool(_url())
    if b == "local":
        if kind == "voice":
            return bool(os.environ.get("VOICE_DEV_ENGINE"))
        return True
    return False


# ---------------------------------------------------------------------------------------------- allowlist
def parse_command(command: str, work: str, show_dir: str | None) -> list[str]:
    """Return argv or raise. work: 'video' (producers/designers) or 'code' (engineers)."""
    if re.search(r"[;&|`$<>\\]|\n", command):
        raise RuntimeError_("one plain command only — no shell operators (; & | ` $ < > \\)")
    argv = shlex.split(command)
    if not argv:
        raise RuntimeError_("empty command")
    head = argv[0]
    if any(".." in a.split("/") for a in argv) or any(a.startswith("/") for a in argv[1:]):
        raise RuntimeError_("paths must stay inside your project folder")
    if work == "video":
        rest = [a for a in argv[1:] if a not in ("-y", "--yes")]
        if head == "npx" and len(rest) >= 2 and re.fullmatch(r"hyperframes(@[\w.\-]+)?", rest[0]):
            if rest[1] not in HYPERFRAMES_SUBCOMMANDS:
                raise RuntimeError_(f"hyperframes {rest[1]} is not allowed here (publish/cloud/auth/tts/skills are stripped)")
            return ["npx", "-y", *rest]
        if head == "python3" and len(argv) >= 4 and argv[1] == "core/reel.py":
            if not show_dir or argv[2] != Path(show_dir).name:
                raise RuntimeError_(f"you may only run reel.py for your own show ({Path(show_dir).name if show_dir else 'none'})")
            if argv[3] not in REEL_SUBCOMMANDS:
                raise RuntimeError_(f"reel.py {argv[3]} is not allowed")
            return argv
        if head in ("ls", "ffprobe"):
            return argv
        raise RuntimeError_("allowed: npx hyperframes@<v> <check|snapshot|render|init|add|…>, "
                            "python3 core/reel.py <your-show> <new|assets|build|data|sfx>, ls, ffprobe")
    if work == "code":
        if head == "npm" and len(argv) >= 2 and argv[1] in ("test", "ci", "install", "run"):
            if argv[1] == "run" and (len(argv) < 3 or argv[2] not in ("test", "build", "lint", "typecheck")):
                raise RuntimeError_("npm run test|build|lint|typecheck only")
            return argv
        if head in ("node", "ls"):
            return argv
        if head == "python3" and len(argv) >= 2 and (argv[1] in ("-m",) and len(argv) >= 3 and argv[2] in ("pytest", "unittest")
                                                     or argv[1].endswith(".py")):
            return argv
        if head == "pytest":
            return argv
        raise RuntimeError_("allowed: npm test|ci|install|run <test|build|lint|typecheck>, node <file>, "
                            "python3 -m pytest, python3 <file.py>, pytest, ls")
    raise RuntimeError_(f"unknown work kind {work}")


# ---------------------------------------------------------------------------------------------- execution
def _clean_env(project: Path) -> dict:
    env = {"PATH": os.environ.get("RUNTIME_PATH") or os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
           "HOME": str(project / ".home"), "LANG": "C.UTF-8",
           "HYPERFRAMES_SKIP_SKILLS": "1", "DO_NOT_TRACK": "1", "HYPERFRAMES_TELEMETRY": "0",
           "npm_config_update_notifier": "false", "PYTHONDONTWRITEBYTECODE": "1"}
    for k in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE",
              "PUPPETEER_EXECUTABLE_PATH", "npm_config_cache"):   # network plumbing only, never credentials
        if os.environ.get(k):
            env[k] = os.environ[k]
    (project / ".home").mkdir(exist_ok=True)
    return env


def run(project: Path, argv: list[str], timeout: int = 900) -> ExecResult:
    b = backend()
    if b == "local":
        if argv[:2] and argv[0] == "npx":
            vendor_cdn(project)
        try:
            p = subprocess.run(argv, cwd=project, env=_clean_env(project), capture_output=True, text=True,
                               timeout=timeout)
        except subprocess.TimeoutExpired:
            return ExecResult(124, f"timed out after {timeout}s")
        except FileNotFoundError as e:
            return ExecResult(127, f"not installed on the runtime: {e.filename}")
        out = (p.stdout + ("\n" + p.stderr if p.stderr else ""))
        return ExecResult(p.returncode, _tail(out))
    if b in ("remote", "modal"):
        return _remote_exec(project, argv, timeout)
    return ExecResult(3, "no runtime configured (RUNTIME_BACKEND)")


def _tail(s: str) -> str:
    s = re.sub(r"\x1b\[[0-9;]*m", "", s)
    return s if len(s) <= MAX_OUT else "…" + s[-MAX_OUT:]


CDN = re.compile(r"https://cdn\.jsdelivr\.net/npm/(@?[\w.\-/]+?)@([\w.\-]+)/([\w./\-]+)")


def vendor_cdn(project: Path) -> None:
    """Local backend only (RUNTIME_VENDOR_CDN=1): a sandbox whose browser can't reach the CDN gets the same
    package versions from npm, and the HTML points at the local copy. Same bytes, deterministic renders."""
    if os.environ.get("RUNTIME_VENDOR_CDN") != "1":
        return
    for html in project.rglob("*.html"):
        if "node_modules" in html.parts:
            continue
        txt = html.read_text(errors="replace")
        hits = set(CDN.findall(txt))
        if not hits:
            continue
        for pkg, ver, _ in hits:
            dest = html.parent / "node_modules" / pkg
            if not dest.exists():
                subprocess.run(["npm", "i", "--no-save", "--prefix", str(html.parent), f"{pkg}@{ver}"],
                               capture_output=True, text=True, timeout=300, env={**_clean_env(project), "HOME": os.environ.get("HOME", "/root")})
        txt = CDN.sub(lambda m: f"node_modules/{m.group(1)}/{m.group(3)}", txt)
        html.write_text(txt)


def _pack(project: Path) -> str:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for p in project.rglob("*"):
            if "node_modules" in p.parts or ".home" in p.parts:
                continue
            tar.add(p, arcname=str(p.relative_to(project)), recursive=False)
    return base64.b64encode(buf.getvalue()).decode()


def _unpack(project: Path, b64: str) -> None:
    with tarfile.open(fileobj=io.BytesIO(base64.b64decode(b64)), mode="r:gz") as tar:
        for m in tar.getmembers():
            target = (project / m.name).resolve()
            if not str(target).startswith(str(project.resolve())) or m.issym() or m.islnk():
                continue   # never let the sandbox write outside the project
            tar.extract(m, project, filter="data")


def _url() -> str:
    return (os.environ.get("RUNTIME_URL") or os.environ.get("MODAL_RUNTIME_URL") or "").rstrip("/")


def _headers() -> dict:
    return {"Authorization": f"Bearer {os.environ.get('RUNTIME_TOKEN') or os.environ.get('MODAL_RUNTIME_TOKEN', '')}"}


def _remote_exec(project: Path, argv: list[str], timeout: int) -> ExecResult:
    import httpx
    url = _url() + "/exec"
    try:
        r = httpx.post(url, json={"argv": argv, "timeout": timeout, "project": _pack(project)},
                       headers=_headers(), timeout=timeout + 120)
        r.raise_for_status()
        data = r.json()
    except Exception as e:  # noqa: BLE001
        return ExecResult(3, f"runtime unreachable: {type(e).__name__}: {e}")
    if data.get("project"):
        _unpack(project, data["project"])
    return ExecResult(int(data.get("exit_code", 1)), _tail(str(data.get("output", ""))))


# ---------------------------------------------------------------------------------------------- voice
def synthesize(text: str, engine: str, voice_id: str | None, out: Path,
               settings: dict | None = None) -> tuple[bool, str]:
    """Returns (ok, message). The CALLER (Dispatcher policy) has already decided this employee may use this voice."""
    out.parent.mkdir(parents=True, exist_ok=True)
    b = backend()
    if b == "local":
        dev = os.environ.get("VOICE_DEV_ENGINE", "")
        if dev != "espeak" or not shutil.which("espeak-ng"):
            return False, f"voice engine '{engine}' runs on the runtime service; not available locally"
        clean = re.sub(r"\[pause [\d.]+\]", ", ", text)
        p = subprocess.run(["espeak-ng", "-v", "en-gb" if engine == "kokoro" else "en-us", "-s", "165", "-w", str(out), clean],
                           capture_output=True, text=True, timeout=120)
        if p.returncode != 0:
            return False, p.stderr[-500:]
        return True, f"DEV VOICE (espeak-ng standing in for {engine}) — replace on the runtime service"
    if b in ("remote", "modal"):
        import httpx
        payload = {"engine": engine, "voice_id": voice_id, "text": text, "settings": settings or {}}
        try:
            r = httpx.post(_url() + "/voice", json=payload, timeout=1800, headers=_headers())   # CPU voices are slow
            r.raise_for_status()
            out.write_bytes(base64.b64decode(r.json()["wav"]))
        except Exception as e:  # noqa: BLE001
            return False, f"voice service error: {type(e).__name__}: {e}"
        return True, "ok"
    return False, "no runtime configured (RUNTIME_BACKEND)"


# ---------------------------------------------------------------------------------------------- project setup
def seed_project(project: Path, show_dir: str | None) -> None:
    """A producer's project is a mini copy of the repo: the shared pipeline (core/) and ONLY its own show's
    folder (I5 — another show's assets, voice and episodes are simply not there)."""
    project.mkdir(parents=True, exist_ok=True)
    if show_dir and not (project / "core").exists():
        shutil.copytree(ROOT / "core", project / "core", ignore=shutil.ignore_patterns("__pycache__"))
        src = ROOT / show_dir
        if src.exists():
            shutil.copytree(src, project / show_dir, ignore=shutil.ignore_patterns("episodes", "output", "__pycache__"))
        (project / show_dir / "episodes").mkdir(parents=True, exist_ok=True)


def find_hf_project(root: Path) -> Path | None:
    hits = sorted((p.parent for p in root.rglob("hyperframes.json") if "node_modules" not in p.parts),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    return hits[0] if hits else None


def test_command(project: Path) -> list[str] | None:
    pkg = project / "package.json"
    if pkg.exists():
        try:
            if json.loads(pkg.read_text()).get("scripts", {}).get("test"):
                return ["npm", "test", "--silent"]
        except json.JSONDecodeError:
            pass
    if any(project.rglob("test_*.py")) or any(project.rglob("*_test.py")):
        return ["python3", "-m", "pytest", "-q"]
    return None
