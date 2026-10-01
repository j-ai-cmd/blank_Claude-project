"""Self-hosted runtime: builds/renders videos, runs code tests and speaks voice lines.

Same two endpoints as the Modal app (deploy/modal_app.py), so the Dispatcher can't tell them apart:
    POST /exec   {argv, project (tar.gz base64), timeout}  -> {exit_code, output, project}
    POST /voice  {engine, text, voice_id, settings, reference?} -> {wav (base64)}

Runs as its own container (deploy/runtime.Dockerfile) next to the API on the Oracle box. It holds NO credentials
of yours — only RUNTIME_TOKEN, which the API must present. It isn't published on any port; only the API can reach it.
Voices run on the CPU (no GPU on the free tier): Kokoro is quick, the Chatterbox clone takes a few minutes per reel.
"""
from __future__ import annotations

import base64
import io
import os
import re
import subprocess
import tarfile
import tempfile
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

ALLOWED_HEADS = {"npx", "python3", "npm", "node", "ls", "ffprobe", "pytest"}   # the Dispatcher already allowlisted
PASS_ENV = ("PATH", "PUPPETEER_EXECUTABLE_PATH", "HYPERFRAMES_SKIP_SKILLS", "DO_NOT_TRACK")
MAX_TIMEOUT = 1700

app = FastAPI(title="Workforce runtime")
_voice_lock = threading.Lock()   # one voice model in memory at a time; requests queue instead of running out of RAM


def _auth(req: Request) -> None:
    token = os.environ.get("RUNTIME_TOKEN", "")
    if not token or req.headers.get("authorization") != f"Bearer {token}":
        raise HTTPException(401, "bad token")


def _unpack(b64: str, dest: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(base64.b64decode(b64)), mode="r:gz") as tar:
        tar.extractall(dest, filter="data")   # "data" filter: no absolute paths, no escaping the folder, no devices


def _pack(src: Path) -> str:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for p in src.rglob("*"):
            if "node_modules" in p.parts or ".home" in p.parts:
                continue
            tar.add(p, arcname=str(p.relative_to(src)), recursive=False)
    return base64.b64encode(buf.getvalue()).decode()


def run_exec(argv: list[str], project_b64: str, timeout: int) -> dict:
    if not argv or argv[0] not in ALLOWED_HEADS or any(re.search(r"[;&|`$<>]", a) for a in argv):
        return {"exit_code": 2, "output": "refused by the runtime allowlist", "project": ""}
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d) / "project"
        proj.mkdir()
        _unpack(project_b64, proj)
        env = {"HOME": d, "LANG": "C.UTF-8", **{k: os.environ[k] for k in PASS_ENV if k in os.environ}}
        try:
            p = subprocess.run(argv, cwd=proj, env=env, capture_output=True, text=True, timeout=min(timeout, MAX_TIMEOUT))
            code, out = p.returncode, p.stdout + "\n" + p.stderr
        except subprocess.TimeoutExpired:
            code, out = 124, f"timed out after {timeout}s"
        except FileNotFoundError as e:
            code, out = 127, f"not installed on the runtime: {e.filename}"
        return {"exit_code": code, "output": out[-6000:], "project": _pack(proj)}


class Voice:
    """Kokoro (show and company voices) and Chatterbox (your cloned voice — the Dispatcher decides who may ask)."""

    def __init__(self) -> None:
        self._kokoro: dict = {}
        self._chatterbox = None

    def _kokoro_pipe(self, voice_id: str):
        from kokoro import KPipeline
        lang = (voice_id or "a")[0]                 # bm_lewis -> 'b' (British), af_heart -> 'a'
        if lang not in self._kokoro:
            self._kokoro[lang] = KPipeline(lang_code=lang)
        return self._kokoro[lang]

    def speak(self, engine: str, text: str, voice_id: str | None, settings: dict, reference_b64: str | None) -> str:
        import numpy as np
        import soundfile as sf
        chunks = re.split(r"\[pause ([\d.]+)\]", text)   # "a [pause 0.6] b" -> ["a", "0.6", "b"]
        sr = 24000
        audio = []
        for i, part in enumerate(chunks):
            if i % 2 == 1:
                audio.append(np.zeros(int(float(part) * sr), dtype=np.float32))
                continue
            if not part.strip():
                continue
            if engine == "kokoro":
                pipe = self._kokoro_pipe(voice_id or "af_heart")
                for _, _, a in pipe(part, voice=voice_id or "af_heart", speed=float(settings.get("speed", 1.0))):
                    audio.append(np.asarray(a, dtype=np.float32))
            elif engine == "chatterbox":
                import torch
                from chatterbox.tts import ChatterboxTTS
                if not reference_b64:
                    raise ValueError("chatterbox needs the consented reference clip")
                if self._chatterbox is None:
                    self._chatterbox = ChatterboxTTS.from_pretrained(device="cuda" if torch.cuda.is_available() else "cpu")
                with tempfile.NamedTemporaryFile(suffix=".wav") as ref:
                    ref.write(base64.b64decode(reference_b64))
                    ref.flush()
                    torch.manual_seed(int(settings.get("seed", 7)))
                    wav = self._chatterbox.generate(part, audio_prompt_path=ref.name,
                                                    exaggeration=float(settings.get("exaggeration", 0.5)),
                                                    cfg_weight=float(settings.get("cfg", 0.5)))
                sr = self._chatterbox.sr
                audio.append(wav.squeeze(0).cpu().numpy().astype(np.float32))
            else:
                raise ValueError(f"unknown engine {engine}")
        buf = io.BytesIO()
        sf.write(buf, np.concatenate(audio) if audio else np.zeros(1, dtype=np.float32), sr, format="WAV")
        return base64.b64encode(buf.getvalue()).decode()


_voice = Voice()


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/exec")
def exec_(req: Request, body: dict):
    _auth(req)
    return run_exec(list(body["argv"]), body["project"], int(body.get("timeout", 900)))


@app.post("/voice")
def voice(req: Request, body: dict):
    _auth(req)
    try:
        with _voice_lock:
            wav = _voice.speak(body["engine"], body["text"], body.get("voice_id"), body.get("settings") or {}, body.get("reference"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"wav": wav}
