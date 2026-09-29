#!/usr/bin/env python3
"""Shared reel pipeline used by the /jai, /sherlock and /peter skills (and anything built on HyperFrames).

    python3 core/reel.py <show> new <slug>          # episode folder (prints its path)
    python3 core/reel.py <show> assets <dir>        # [x]/[ ] checklist of script.json "assets"; exit 1 if any missing
    python3 core/reel.py <show> voicetext <dir>     # the exact line per beat to voice (pronunciation applied)
    python3 core/reel.py <show> build <dir>         # voice timings + captions + sfx + composition (needs the voice files)
    python3 core/reel.py <show> data <dir>          # rebuild the composition from script.json (no re-voice)
    python3 core/reel.py <show> sfx <dir>           # re-place click sounds

Voice files are made by the employee's `voice_line` tool (the Dispatcher picks the show's voice; this script
never chooses a voice): assets/voice/<beat-id>.wav per beat, or one recorded `voiceover` asset (Striker).
Runs inside the sandbox runtime with stdlib + ffmpeg/ffprobe only. Captions are always the script's words.
"""
from __future__ import annotations

import datetime as _dt
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HF_VERSION = "0.8.91"
GSAP = "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"
WPM_GAP = 0.25   # seconds of air between beats

# Locked styles, from each show's skill (the skill is the show bible until brand/DESIGN.md is written).
SHOWS = {
    "jai": {"dir": "shows/jai", "bg": "#FBEFD5", "ink": "#2A1410", "accent": "#B8432B", "label": "#F4B658",
            "head": "Rozha One", "body": "Mukta", "handle": "@jaidhingra_", "captions": "highlight"},
    "sherlock": {"dir": "shows/sherlock", "bg": "#1F3B2D", "ink": "#F3EAD3", "accent": "#C9A45C", "label": "#F3EAD3",
                 "head": "Gloock", "body": "Karla", "handle": "@sherlock_teaches_ai", "captions": "highlight",
                 "character": "character"},
    "brainrot": {"dir": "shows/brainrot", "bg": "#2B0F33", "ink": "#FFFFFF", "accent": "#FF5FA2", "label": "#FF5FA2",
                 "head": "Shrikhand", "body": "Courier Prime", "handle": "", "captions": "pop",
                 "character": "character"},
    "striker": {"dir": "shows/striker", "bg": "#0B3D2E", "ink": "#FFFFFF", "accent": "#D7FF3A", "label": "#D7FF3A",
                "head": "Big Shoulders Display", "body": "Barlow", "handle": "", "captions": "pop"},
}


def die(msg: str, code: int = 1) -> None:
    print(msg)
    sys.exit(code)


def show_of(name: str) -> dict:
    if name not in SHOWS:
        die(f"unknown show {name} (known: {', '.join(SHOWS)})")
    return SHOWS[name]


def load_script(ep: Path) -> dict:
    p = ep / "script.json"
    if not p.exists():
        die(f"no script.json in {ep}")
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError as e:
        die(f"script.json is not valid JSON: {e}")


# ------------------------------------------------------------------------------------------------ new
def cmd_new(show: str, slug: str) -> None:
    s = show_of(show)
    slug = re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-") or "episode"
    ep = Path(s["dir"]) / "episodes" / f"{_dt.date.today().isoformat()}-{slug}"
    (ep / "assets" / "media").mkdir(parents=True, exist_ok=True)
    (ep / "assets" / "voice").mkdir(parents=True, exist_ok=True)
    if not (ep / "script.json").exists():
        (ep / "script.json").write_text(json.dumps({
            "title": slug.replace("-", " ").title(), "show": show,
            "beats": [{"id": "b1", "label": "HOOK", "say": "", "screen": {"headline": ""}}],
            "assets": [], "caption_style": s["captions"], "cover": 1.0, "pronounce": {}}, indent=2))
    (ep / "hyperframes.json").write_text(json.dumps({
        "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
        "paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"},
        "media": {"autoProxy": True}}, indent=2))
    (ep / "meta.json").write_text(json.dumps({"id": slug, "name": slug}, indent=2))
    print(ep)


# ------------------------------------------------------------------------------------------------ assets
def asset_path(ep: Path, a: dict) -> Path:
    return ep / "assets" / "media" / a["file"]


def cmd_assets(ep: Path, quiet: bool = False) -> bool:
    sc = load_script(ep)
    missing = []
    for a in sc.get("assets", []):
        have = asset_path(ep, a).exists()
        if not quiet:
            print(f"[{'x' if have else ' '}] {a['file']} — {a.get('what', '')} ({a.get('why', '')})")
        if not have:
            missing.append(a["file"])
    if not sc.get("assets") and not quiet:
        print("No assets needed.")
    if missing and not quiet:
        print(f"MISSING {len(missing)}: ask the owner for {', '.join(missing)}")
    return not missing


# ------------------------------------------------------------------------------------------------ voice text
def pronounce_map(show: str, sc: dict) -> dict:
    p = Path(show_of(show)["dir"]) / "voice" / "PRONOUNCE.json"
    base = {}
    if p.exists():
        try:
            base = json.loads(p.read_text())
        except json.JSONDecodeError:
            base = {}
    return {**base, **(sc.get("pronounce") or {})}


def voice_text(say: str, pron: dict) -> str:
    t = re.sub(r"(\d)\.(\d)", r"\1 point \2", say)   # "5.6" is not a full stop
    for word, spoken in pron.items():
        if not str(spoken).startswith("/"):            # IPA entries need the Kokoro phoneme path on the runtime
            t = re.sub(rf"\b{re.escape(word)}\b", spoken, t)
    return t


def cmd_voicetext(show: str, ep: Path) -> None:
    sc = load_script(ep)
    pron = pronounce_map(show, sc)
    out = {b["id"]: {"text": voice_text(b.get("say", ""), pron), "out": f"assets/voice/{b['id']}.wav"}
           for b in sc.get("beats", []) if b.get("say")}
    print(json.dumps(out, indent=1))


# ------------------------------------------------------------------------------------------------ build
def duration(path: Path) -> float:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        return float(out)
    except (ValueError, subprocess.SubprocessError, FileNotFoundError):
        return 0.0


def words_of(say: str) -> list[str]:
    return [w for w in re.sub(r"\[pause [\d.]+\]", " ", say).split() if w.strip()]


def time_words(words: list[str], start: float, length: float) -> list[dict]:
    weights = [len(re.sub(r"\W", "", w)) + 2 for w in words] or [1]
    total, t, out = sum(weights), start, []
    for w, k in zip(words, weights):
        d = length * k / total
        out.append({"w": w, "start": round(t, 3), "end": round(t + d, 3)})
        t += d
    return out


def cmd_build(show: str, ep: Path) -> None:
    sc = load_script(ep)
    if not cmd_assets(ep, quiet=True):
        cmd_assets(ep)
        die("BUILD REFUSED: assets missing (ask the owner; never make placeholders)", 1)
    beats = [b for b in sc.get("beats", []) if b.get("say")]
    if not beats:
        die("script.json has no beats with 'say' text")
    recorded = next((a for a in sc.get("assets", []) if a.get("id") == "voiceover"), None)
    timeline, words, t = [], [], 0.0
    if recorded:   # Striker: the owner's own recording, split across beats by word share
        total = duration(asset_path(ep, recorded))
        if total <= 0:
            die("the voiceover file has no audio")
        counts = [len(words_of(b["say"])) or 1 for b in beats]
        for b, n in zip(beats, counts):
            d = total * n / sum(counts)
            timeline.append({"id": b["id"], "start": round(t, 3), "end": round(t + d, 3)})
            words += time_words(words_of(b["say"]), t, d)
            t += d
        shutil.copy(asset_path(ep, recorded), ep / "assets" / "voice.wav")
    else:
        missing = [b["id"] for b in beats if not (ep / "assets" / "voice" / f"{b['id']}.wav").exists()]
        if missing:
            print(f"VOICE MISSING for beats {missing}. Voice each line exactly as `reel.py {show} voicetext <dir>` prints it,")
            die("with your voice_line tool (out = assets/voice/<beat-id>.wav), then build again.", 2)
        parts = []
        for b in beats:
            wav = ep / "assets" / "voice" / f"{b['id']}.wav"
            d = duration(wav)
            if d <= 0:
                die(f"{wav.name} has no audio — voice it again")
            timeline.append({"id": b["id"], "start": round(t, 3), "end": round(t + d, 3)})
            words += time_words(words_of(b["say"]), t, d)
            parts.append((wav, d))
            t += d + WPM_GAP
        concat(ep, parts)
    total = round(t, 3)
    ep_data = {"title": sc.get("title"), "duration": total, "beats": timeline, "words": words}
    (ep / "assets" / "episode.json").write_text(json.dumps(ep_data, indent=1))
    (ep / "assets" / "episode.js").write_text("window.EPISODE = " + json.dumps(ep_data) + ";\n")
    print(f"voice: {len(timeline)} beat(s), {total:.1f}s")
    print("PRONUNCIATION CHECK: needs Whisper on the runtime — listen to assets/voice.wav before rendering")
    cmd_data(show, ep)


def concat(ep: Path, parts: list[tuple[Path, float]]) -> None:
    listing = ep / "assets" / "voice" / "concat.txt"
    silence = ep / "assets" / "voice" / "_gap.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", str(WPM_GAP),
                    str(silence)], check=True, timeout=60)
    lines = []
    for i, (wav, _) in enumerate(parts):
        lines.append(f"file '{wav.name}'")
        if i < len(parts) - 1:
            lines.append(f"file '{silence.name}'")
    listing.write_text("\n".join(lines) + "\n")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-ar", "24000",
                    "-ac", "1", str(ep / "assets" / "voice.wav")], check=True, timeout=300)


# ------------------------------------------------------------------------------------------------ composition
def sfx_files() -> list[Path]:
    d = Path("core/sfx")
    return sorted(p for p in d.glob("*") if p.suffix.lower() in (".mp3", ".wav")) if d.is_dir() else []


def cmd_data(show: str, ep: Path) -> None:
    s = show_of(show)
    sc = load_script(ep)
    epj = ep / "assets" / "episode.json"
    if not epj.exists():
        die("run build first (no timings yet)")
    data = json.loads(epj.read_text())
    total = max(float(data["duration"]), 1.0)
    by_id = {b["id"]: b for b in sc.get("beats", [])}
    assets = {a["id"]: a for a in sc.get("assets", [])}
    faces = font_faces(ep, (s["head"], s["body"]))
    clips, anim, media_clips = [], [], []
    for i, tb in enumerate(data["beats"]):
        b = by_id.get(tb["id"], {})
        start, dur = tb["start"], max(0.1, round(tb["end"] - tb["start"] + (WPM_GAP if i < len(data["beats"]) - 1 else 0), 3))
        scr = b.get("screen") or {}
        media = ""
        m = assets.get(b.get("media") or "")
        if m and Path(m["file"]).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            media = f'<img class="media" src="assets/media/{html.escape(m["file"])}" alt="{html.escape(m.get("what", ""))}">'
        cam = assets.get(b.get("cam") or "")
        if cam:   # camera beat: full-bleed muted clip, timed on the video itself (never inside a timed section)
            media_clips.append(f'<video id="cam-{i}" class="clip cam" src="assets/media/{html.escape(cam["file"])}" '
                               f'data-start="{start}" data-duration="{dur}" data-track-index="2" muted playsinline></video>')
        clips.append(
            f'<section id="beat-{i}" class="clip beat" data-start="{start}" data-duration="{dur}" data-track-index="1">'
            f'<div class="label">{html.escape(b.get("label", ""))}</div>'
            f'<h1 class="headline">{html.escape(scr.get("headline") or "")}</h1>'
            f'<p class="sub">{html.escape(scr.get("sub") or scr.get("quote") or "")}</p>{media}</section>')
        anim.append(f'tl.fromTo("#beat-{i} .headline",{{opacity:0,y:40}},{{opacity:1,y:0,duration:0.45,ease:"expo.out"}},{start});')
        anim.append(f'tl.fromTo("#beat-{i} .sub",{{opacity:0}},{{opacity:1,duration:0.4}},{start + 0.2});')
    style = sc.get("caption_style") or s["captions"]
    caps = []
    for j, w in enumerate(data["words"]):
        caps.append(f'<span id="w{j}" class="w">{html.escape(w["w"])}</span>')
        if style == "pop":
            anim.append(f'tl.set("#w{j}",{{display:"inline-block",scale:1.15}},{w["start"]});'
                        f'tl.to("#w{j}",{{scale:1,duration:0.12}},{w["start"]});'
                        f'tl.set("#w{j}",{{display:"none"}},{w["end"]});')
        else:   # highlight: the phrase stays up, the spoken word is lit
            chunk = j // 4
            anim.append(f'tl.set("#w{j}",{{display:"inline-block"}},{data["words"][chunk * 4]["start"]});'
                        f'tl.set("#w{j}",{{color:"{s["accent"]}"}},{w["start"]});'
                        f'tl.set("#w{j}",{{color:"{s["ink"]}"}},{w["end"]});')
            last = min(len(data["words"]) - 1, chunk * 4 + 3)
            anim.append(f'tl.set("#w{j}",{{display:"none"}},{data["words"][last]["end"]});')
    audio = []
    if (ep / "assets" / "voice.wav").exists():
        vdur = duration(ep / "assets" / "voice.wav") or total
        audio.append(f'<audio id="voice" src="assets/voice.wav" data-start="0" data-duration="{round(vdur, 3)}" '
                     f'data-track-index="10" data-volume="1"></audio>')
    bg = assets.get((sc.get("background") or {}).get("asset") or "")
    if bg:
        media_clips.insert(0, f'<video id="bg" class="clip bgv" src="assets/media/{html.escape(bg["file"])}" data-start="0" '
                              f'data-duration="{total}" data-track-index="0" muted playsinline></video>')
    for k, fx in enumerate(place_sfx(ep, data)):
        audio.append(fx)
    char = ""
    if s.get("character") and (Path(s["dir"]) / s["character"] / "idle.png").exists():
        shutil.copy(Path(s["dir"]) / s["character"] / "idle.png", ep / "assets" / "character-idle.png")
        char = '<img id="character" src="assets/character-idle.png" alt="host">'
    doc = f"""<!doctype html>
<html lang="en" data-resolution="portrait">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=1080, height=1920">
<script src="{GSAP}"></script>
<style>
{faces}
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;overflow:hidden;background:{s['bg']}}}
#root{{position:relative;width:1080px;height:1920px;color:{s['ink']};font-family:'{s['body']}',sans-serif}}
.bgv,.cam{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}
.beat{{position:absolute;left:90px;right:90px;top:360px;display:flex;flex-direction:column;gap:36px}}
.label{{font:700 34px '{s['body']}',sans-serif;letter-spacing:.14em;color:{s['label']}}}
.headline{{font:400 96px/1.05 '{s['head']}',serif;color:{s['ink']}}}
.sub{{font:400 46px/1.3 '{s['body']}',sans-serif;opacity:.9}}
.media{{max-width:100%;max-height:640px;object-fit:contain;border-radius:18px}}
#captions{{position:absolute;left:80px;right:80px;bottom:300px;text-align:center;font:800 76px/1.15 '{s['body']}',sans-serif;
  color:{s['ink']};text-shadow:0 4px 18px rgba(0,0,0,.35)}}
.w{{display:none;margin:0 .18em}}
#handle{{position:absolute;top:70px;right:80px;font:600 34px '{s['body']}',sans-serif;color:{s['accent']}}}
#character{{position:absolute;right:40px;bottom:560px;width:360px}}
</style>
</head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{total}" data-width="1080" data-height="1920">
{chr(10).join(media_clips)}
{chr(10).join(clips)}
<div id="captions" class="clip" data-start="0" data-duration="{total}" data-track-index="3">{''.join(caps)}</div>
{f'<div id="handle" class="clip" data-start="0" data-duration="{total}" data-track-index="4">{html.escape(s["handle"])}</div>' if s['handle'] else ''}
{char}
{chr(10).join(audio)}
</div>
<script>
const tl = gsap.timeline({{ paused: true }});
{chr(10).join(anim)}
window.__timelines = window.__timelines || {{}};
window.__timelines["main"] = tl;
tl.seek(0);
</script>
</body>
</html>
"""
    (ep / "index.html").write_text(doc)
    print(f"composition written: {ep / 'index.html'} ({len(data['beats'])} beats, {len(data['words'])} caption words)")


def font_faces(ep: Path, families) -> str:
    """Locked fonts as local files (core/fonts, from fetch_fonts.py): renders never fetch fonts."""
    src_dir = Path("core/fonts")
    (ep / "assets" / "fonts").mkdir(parents=True, exist_ok=True)
    css = []
    for fam in families:
        files = sorted(src_dir.glob(f"{fam.replace(' ', '')}-*.woff2")) if src_dir.is_dir() else []
        if not files:
            print(f"FONT MISSING: {fam} — run python3 core/fetch_fonts.py on the runtime image")
        for f in files:
            shutil.copy(f, ep / "assets" / "fonts" / f.name)
            weight = f.stem.rsplit("-", 1)[-1]
            css.append(f"@font-face{{font-family:'{fam}';font-weight:{weight};src:url(assets/fonts/{f.name}) format('woff2')}}")
    return "\n".join(css)


def place_sfx(ep: Path, data: dict) -> list[str]:
    fx = sfx_files()
    if not fx:
        print("SFX: core/sfx has no sounds yet — clicks skipped (add the approved pack to core/sfx/)")
        return []
    (ep / "assets" / "sfx").mkdir(parents=True, exist_ok=True)
    click = fx[0]
    shutil.copy(click, ep / "assets" / "sfx" / click.name)
    out = []
    for i, b in enumerate(data["beats"]):
        out.append(f'<audio id="sfx-{i}" src="assets/sfx/{click.name}" data-start="{b["start"]}" data-duration="0.4" '
                   f'data-track-index="11" data-volume="0.5"></audio>')
    return out


def cmd_sfx(show: str, ep: Path) -> None:
    cmd_data(show, ep)


def main(argv: list[str]) -> None:
    if len(argv) < 3:
        die(__doc__, 2)
    show, cmd = argv[0], argv[1]
    show_of(show)
    if cmd == "new":
        cmd_new(show, argv[2])
        return
    ep = Path(argv[2])
    if not ep.is_dir():
        die(f"no episode folder {ep}")
    {"assets": lambda: sys.exit(0 if cmd_assets(ep) else 1), "voicetext": lambda: cmd_voicetext(show, ep),
     "build": lambda: cmd_build(show, ep), "data": lambda: cmd_data(show, ep),
     "sfx": lambda: cmd_sfx(show, ep)}.get(cmd, lambda: die(f"unknown command {cmd}", 2))()


if __name__ == "__main__":
    main(sys.argv[1:])
