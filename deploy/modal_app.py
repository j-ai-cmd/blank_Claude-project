"""The runtime on your Modal account: builds/renders videos, runs code tests, and speaks voice lines.

Deploy (once, from your machine):
    pip install modal && modal setup
    modal secret create workforce-runtime MODAL_RUNTIME_TOKEN=<same long random string as in the server .env>
    modal deploy deploy/modal_app.py        # prints the URL -> MODAL_RUNTIME_URL in the server .env

It holds NO credentials of yours: the Dispatcher sends a project folder + one already-allowlisted command, gets
the folder back. Voices: Kokoro (Sherlock, Peter, non-show videos) and Chatterbox (your cloned voice, Jai only —
the Dispatcher decides who may ask for it; the reference clip is sent per call, never stored here).
"""
import base64
import io
import os
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path

import modal

HF = "0.8.91"
build_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "curl", "ca-certificates", "chromium", "fonts-dejavu-core", "git")
    .run_commands("curl -fsSL https://deb.nodesource.com/setup_22.x | bash -", "apt-get install -y nodejs",
                  f"npm i -g hyperframes@{HF}")
    .pip_install("fastapi[standard]", "pytest")
    .env({"PUPPETEER_EXECUTABLE_PATH": "/usr/bin/chromium", "HYPERFRAMES_SKIP_SKILLS": "1", "DO_NOT_TRACK": "1"})
)
voice_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "espeak-ng", "git")
    .pip_install("kokoro>=0.9.4", "soundfile", "numpy", "chatterbox-tts", "torchaudio", "fastapi[standard]")
)
app = modal.App("workforce-runtime")
secret = modal.Secret.from_name("workforce-runtime")
ALLOWED_HEADS = {"npx", "python3", "npm", "node", "ls", "ffprobe", "pytest"}   # the Dispatcher already allowlisted


def _unpack(b64: str, dest: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(base64.b64decode(b64)), mode="r:gz") as tar:
        tar.extractall(dest, filter="data")


def _pack(src: Path) -> str:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for p in src.rglob("*"):
            if "node_modules" in p.parts or ".home" in p.parts:
                continue
            tar.add(p, arcname=str(p.relative_to(src)), recursive=False)
    return base64.b64encode(buf.getvalue()).decode()


@app.function(image=build_image, secrets=[secret], cpu=4.0, memory=8192, timeout=1800)
def run_exec(argv: list, project_b64: str, timeout: int) -> dict:
    if not argv or argv[0] not in ALLOWED_HEADS or any(re.search(r"[;&|`$<>]", a) for a in argv):
        return {"exit_code": 2, "output": "refused by the runtime allowlist", "project": ""}
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d) / "project"
        proj.mkdir()
        _unpack(project_b64, proj)
        env = {"PATH": os.environ["PATH"], "HOME": d, "LANG": "C.UTF-8", **{k: os.environ[k] for k in
               ("PUPPETEER_EXECUTABLE_PATH", "HYPERFRAMES_SKIP_SKILLS", "DO_NOT_TRACK")}}
        try:
            p = subprocess.run(argv, cwd=proj, env=env, capture_output=True, text=True, timeout=min(timeout, 1700))
            code, out = p.returncode, p.stdout + "\n" + p.stderr
        except subprocess.TimeoutExpired:
            code, out = 124, f"timed out after {timeout}s"
        return {"exit_code": code, "output": out[-6000:], "project": _pack(proj)}


@app.cls(image=voice_image, gpu="T4", secrets=[secret], timeout=900, scaledown_window=120)
class Voice:
    @modal.enter()
    def load(self):
        self._kokoro = {}
        self._chatterbox = None

    def _kokoro_pipe(self, voice_id: str):
        from kokoro import KPipeline
        lang = (voice_id or "a")[0]                 # bm_lewis -> 'b' (British), af_heart -> 'a'
        if lang not in self._kokoro:
            self._kokoro[lang] = KPipeline(lang_code=lang)
        return self._kokoro[lang]

    @modal.method()
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
                    self._chatterbox = ChatterboxTTS.from_pretrained(device="cuda")
                ref = Path(tempfile.mkstemp(suffix=".wav")[1])
                ref.write_bytes(base64.b64decode(reference_b64))
                torch.manual_seed(int(settings.get("seed", 7)))
                wav = self._chatterbox.generate(part, audio_prompt_path=str(ref),
                                                exaggeration=float(settings.get("exaggeration", 0.5)),
                                                cfg_weight=float(settings.get("cfg", 0.5)))
                sr = self._chatterbox.sr
                audio.append(wav.squeeze(0).cpu().numpy().astype(np.float32))
            else:
                raise ValueError(f"unknown engine {engine}")
        buf = io.BytesIO()
        sf.write(buf, np.concatenate(audio) if audio else np.zeros(1, dtype=np.float32), sr, format="WAV")
        return base64.b64encode(buf.getvalue()).decode()


@app.function(image=build_image, secrets=[secret], timeout=1800)
@modal.asgi_app()
def web():
    from fastapi import FastAPI, HTTPException, Request

    api = FastAPI()

    def _auth(req: Request) -> None:
        if req.headers.get("authorization") != f"Bearer {os.environ['MODAL_RUNTIME_TOKEN']}":
            raise HTTPException(401, "bad token")

    @api.post("/exec")
    async def exec_(req: Request):
        _auth(req)
        body = await req.json()
        return run_exec.remote(list(body["argv"]), body["project"], int(body.get("timeout", 900)))

    @api.post("/voice")
    async def voice(req: Request):
        _auth(req)
        b = await req.json()
        wav = Voice().speak.remote(b["engine"], b["text"], b.get("voice_id"), b.get("settings") or {}, b.get("reference"))
        return {"wav": wav}

    return api
