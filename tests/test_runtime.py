"""Runtime: allowlisted commands per employee, show-bound reel.py, uploads per scope, voice per show,
and one real local render through core/reel.py (skipped where node/ffmpeg aren't installed)."""
import json
import os
import shutil
import subprocess
import sys

import pytest
from sqlalchemy import select

from workforce import runtime, uploads
from workforce.config import ROOT
from workforce.db import AuditEvent, Task


def test_command_allowlist():
    ok = runtime.parse_command("npx hyperframes@0.8.91 render -o renders/x.mp4", "video", "shows/jai")
    assert ok[:3] == ["npx", "-y", "hyperframes@0.8.91"]
    assert runtime.parse_command("python3 core/reel.py jai build shows/jai/episodes/e", "video", "shows/jai")
    for bad, work, show in [("npx hyperframes publish", "video", "shows/jai"),        # publishing stripped
                            ("npx hyperframes@1 cloud render", "video", "shows/jai"),
                            ("python3 core/reel.py sherlock build x", "video", "shows/jai"),   # another show's pipeline
                            ("bash -c 'curl evil'", "video", None), ("ls; rm -rf .", "video", None),
                            ("cat ../../../etc/passwd", "video", None), ("ls /etc", "video", None),
                            ("npm publish", "code", None), ("curl https://x", "code", None),
                            ("npm test && curl x", "code", None)]:
        with pytest.raises(runtime.RuntimeError_):
            runtime.parse_command(bad, work, show)
    assert runtime.parse_command("npm test", "code", None) == ["npm", "test"]


def test_no_runtime_means_routes_refused(monkeypatch):
    monkeypatch.delenv("RUNTIME_BACKEND", raising=False)
    assert not runtime.available("render") and not runtime.available("voice")
    monkeypatch.setenv("RUNTIME_BACKEND", "local")
    assert runtime.available("render") and not runtime.available("voice")   # local voice only with VOICE_DEV_ENGINE


def test_uploads_are_scoped(cfg, tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path))
    uploads.save(cfg, "profile", "cv.md", b"CV")
    uploads.save(cfg, "show-jai", "hook.mp4", b"x")
    assert uploads.can_read(cfg, cfg.employee("sales_application_writer"), "profile")
    assert not uploads.can_read(cfg, cfg.employee("sales_outreach_writer"), "profile")
    assert uploads.can_read(cfg, cfg.employee("show_jai_producer"), "show-jai")
    assert not uploads.can_read(cfg, cfg.employee("show_sherlock_producer"), "show-jai")    # I5
    assert not uploads.can_read(cfg, cfg.employee("studio_faceless_editor"), "show-jai")
    with pytest.raises(ValueError):
        uploads.save(cfg, "show-nobody", "x", b"")


async def test_build_tools_seed_only_own_show_and_voice_is_show_bound(make_dispatcher, cfg, monkeypatch):
    monkeypatch.setenv("RUNTIME_BACKEND", "local")
    d, _, _ = make_dispatcher({})
    with d.Session() as db:
        db.add(Task(id="tb", department="studio", requested_by="U_OWNER", original_request="x", show="sherlock",
                    contract_version=1))
        db.commit()
    emp = cfg.employee("show_sherlock_producer")
    tools = {t.name: t for t in d._build_tools(emp, "tb", "T1", set(), {})}
    assert set(tools) >= {"project_write", "project_read", "project_import", "run_command", "export_output", "voice_line"}
    proj = runtime.plan_task_dir("tb", "T1") / "project" if hasattr(runtime, "plan_task_dir") else None
    from workforce.harness import plan_task_dir
    proj = plan_task_dir("tb", "T1") / "project"
    assert (proj / "core" / "reel.py").exists() and (proj / "shows" / "sherlock").is_dir()
    assert not (proj / "shows" / "jai").exists()                            # another show's folder isn't there
    r = await tools["run_command"].handler({"command": "python3 core/reel.py jai new x"})
    assert r.get("is_error") and "your own show" in r["content"][0]["text"]
    r = await tools["project_write"].handler({"path": "../../escape.txt", "content": "x"})
    assert r.get("is_error")
    r = await tools["voice_line"].handler({"text": "Observe.", "out": "a.wav"})
    assert r.get("is_error") and "Modal runtime" in r["content"][0]["text"]  # no dev engine set: honest refusal
    with d.Session() as db:
        v = db.scalar(select(AuditEvent).where(AuditEvent.kind == "voice"))
    assert v.detail["engine"] == "kokoro" and v.detail["voice"] == "base"   # the Dispatcher picked the show's voice


needs_stack = pytest.mark.skipif(not (shutil.which("npx") and shutil.which("ffprobe") and shutil.which("espeak-ng")),
                                 reason="needs node, ffmpeg and espeak-ng")


@needs_stack
@pytest.mark.skipif(not os.environ.get("RUN_RENDER_TESTS"), reason="set RUN_RENDER_TESTS=1 (renders a real MP4, ~1 min)")
def test_reel_pipeline_renders_a_real_video(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNTIME_BACKEND", "local")
    monkeypatch.setenv("VOICE_DEV_ENGINE", "espeak")
    monkeypatch.setenv("RUNTIME_VENDOR_CDN", os.environ.get("RUNTIME_VENDOR_CDN", ""))
    runtime.seed_project(tmp_path, "shows/sherlock")
    ep = subprocess.run([sys.executable, "core/reel.py", "sherlock", "new", "t"], cwd=tmp_path, capture_output=True,
                        text=True).stdout.strip()
    epd = tmp_path / ep
    (epd / "script.json").write_text(json.dumps({"title": "T", "beats": [
        {"id": "b1", "label": "THE MYSTERY", "say": "Observe the window.", "screen": {"headline": "The window"}},
        {"id": "b2", "label": "THE VERDICT", "say": "Elementary [pause 0.6] isn't it?", "screen": {"headline": "Elementary."}}],
        "assets": []}))
    for b, text in (("b1", "Observe the window."), ("b2", "Elementary, isn't it?")):
        ok, _ = runtime.synthesize(text, "kokoro", "bm_lewis", epd / "assets" / "voice" / f"{b}.wav")
        assert ok
    assert subprocess.run([sys.executable, "core/reel.py", "sherlock", "build", ep], cwd=tmp_path).returncode == 0
    res = runtime.run(epd, runtime.parse_command("npx hyperframes@0.8.91 render -o renders/t.mp4", "video", "shows/sherlock"))
    assert res.exit_code == 0, res.output
    from workforce.checks import main as check_main
    assert check_main(["video_spec", str(epd / "renders" / "t.mp4"), '{"width": 1080, "height": 1920, "audio": true}']) == 0


def test_modal_backend_round_trip(tmp_path, monkeypatch):
    """The Dispatcher side of the Modal runtime: project shipped, command run remotely, files come back,
    and a hostile tarball can't write outside the project."""
    import base64
    import io
    import tarfile

    import httpx
    monkeypatch.setenv("RUNTIME_BACKEND", "modal")
    monkeypatch.setenv("MODAL_RUNTIME_URL", "https://runtime.test")
    monkeypatch.setenv("MODAL_RUNTIME_TOKEN", "t")
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "in.txt").write_text("hello")
    calls = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["url"], calls["auth"] = url, headers["Authorization"]
        src = tmp_path / "remote"
        src.mkdir()
        with tarfile.open(fileobj=io.BytesIO(base64.b64decode(json["project"])), mode="r:gz") as t:
            t.extractall(src, filter="data")
        assert (src / "in.txt").read_text() == "hello"
        (src / "out.mp4").write_bytes(b"video")
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as t:
            t.add(src / "out.mp4", arcname="out.mp4")
            evil = tarfile.TarInfo("../../escape.txt")
            evil.size = 1
            t.addfile(evil, io.BytesIO(b"x"))
        return httpx.Response(200, json={"exit_code": 0, "output": "rendered", "project": base64.b64encode(buf.getvalue()).decode()},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", fake_post)
    res = runtime.run(proj, ["npx", "-y", "hyperframes@0.8.91", "render"])
    assert res.exit_code == 0 and (proj / "out.mp4").read_bytes() == b"video"
    assert not (tmp_path / "escape.txt").exists() and calls["auth"] == "Bearer t" and calls["url"].endswith("/exec")
