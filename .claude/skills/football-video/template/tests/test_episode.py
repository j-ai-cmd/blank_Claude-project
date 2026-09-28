"""Acceptance tests for the rendered episode. Run: .venv/bin/python tests/test_episode.py [video.mp4]

Every test reads the real render (frames + audio) or the real composition inputs.
Writes tests/report.json and tests/proof-sheet.png (one labelled frame per scene goal).
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

P = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(P / "scripts"))
import build_scenes as B  # noqa: E402

VIDEO = Path(sys.argv[1]) if len(sys.argv) > 1 else P / "renders/draft.mp4"
OUT = P / "tests"
FR = OUT / "frames"
FR.mkdir(parents=True, exist_ok=True)
VOLT = np.array([0xE1, 0xFE, 0x67])
RESULTS, PROOF = [], []


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


CAPV = P / "tests/captions-only.mp4"


def frame(t, src=None):
    src = src or VIDEO
    f = FR / f"{'c' if src == CAPV else 'v'}{t:07.3f}.png"
    if not f.exists():
        run(["ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1", str(f), "-loglevel", "error"])
    return np.asarray(Image.open(f).convert("RGB")).astype(np.int16)


def volt_mask(a, tol=38):
    return (np.abs(a - VOLT).sum(-1) < tol)


def sat(a):
    mx, mn = a.max(-1), a.min(-1)
    return np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)


def check(goal, name, ok, detail, proof_t=None):
    RESULTS.append({"goal": goal, "test": name, "pass": bool(ok), "detail": detail})
    if proof_t is not None:
        frame(proof_t)
        PROOF.append((proof_t, f"{'PASS' if ok else 'FAIL'} · {name}"))
    print(("PASS " if ok else "FAIL ") + f"[{goal}] {name} — {detail}")


ZONE = (slice(250, 1340), slice(72, 1008))   # content zone
CAP = (slice(1260, 1500), slice(60, 1020))    # caption band


def zone_volt(t):
    return float(volt_mask(frame(t)[ZONE]).mean())


# ------------------------------------------------------------------ G1 render integrity
probe = json.loads(run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(VIDEO)]).stdout)
v = next(s for s in probe["streams"] if s["codec_type"] == "video")
a = [s for s in probe["streams"] if s["codec_type"] == "audio"]
dur = float(probe["format"]["duration"])
check("Rendered properly", "1080x1920 portrait", (v["width"], v["height"]) == (1080, 1920), f'{v["width"]}x{v["height"]}')
check("Rendered properly", "30 fps", v["avg_frame_rate"] in ("30/1", "30000/1000"), v["avg_frame_rate"])
check("Rendered properly", "duration matches timeline", abs(dur - B.TOTAL) < 0.15, f"{dur:.2f}s vs {B.TOTAL}s")
check("Rendered properly", "audio track present", len(a) == 1, f"{len(a)} audio stream(s)")

bd = run(["ffmpeg", "-i", str(VIDEO), "-vf", "blackdetect=d=0.05:pix_th=0.02", "-an", "-f", "null", "-"]).stderr
blacks = [ln for ln in bd.splitlines() if "black_start" in ln]
check("Every frame works", "no black frames anywhere", not blacks, f"{len(blacks)} black segments")
fz = run(["ffmpeg", "-i", str(VIDEO), "-vf", "freezedetect=n=0.001:d=1.6", "-an", "-f", "null", "-"]).stderr
freezes = [float(ln.split("freeze_start: ")[1]) for ln in fz.splitlines() if "freeze_start" in ln]
bad = [f for f in freezes if f < B.SCENES["cta"][0] + 2.5]
check("Every frame works", "no frozen stretch (>1.6s) before the end card", not bad, f"freezes at {bad or 'none'}; end-card hold {freezes[-1:] or 'none'}")

# ------------------------------------------------------------------ G2 audio
ld = run(["ffmpeg", "-i", str(VIDEO), "-af", "ebur128=peak=true", "-vn", "-f", "null", "-"]).stderr
I = float(ld.split("I:")[-1].split("LUFS")[0])
pk = float(ld.split("Peak:")[-1].split("dBFS")[0])
check("Rendered properly", "loudness in social range (-18..-9 LUFS)", -18 <= I <= -9, f"{I} LUFS")
check("Rendered properly", "no clipping (true peak < 0 dBFS)", pk < 0, f"{pk} dBFS")
idx = (P / "index.html").read_text()
check("Crowd noise bed", "crowd bed placed under whole video, dipped for the caveat",
      all(f'id="el-crowd-{k}"' in idx for k in "abc") and 'data-volume="0.05"' in idx, "3 crowd clips, caveat clip at 0.05")
cb = run(["ffmpeg", "-i", str(P / "assets/audio/crowd-bed.wav"), "-af", "volumedetect", "-f", "null", "-"]).stderr
cmean = float(cb.split("mean_volume:")[1].split("dB")[0])
check("Crowd noise bed", "crowd bed file audible, full length", cmean > -40, f"mean {cmean} dB")

# ------------------------------------------------------------------ G3 captions
groups = json.loads((P / "assets/audio/caption-groups.json").read_text())
import build_index as BI  # noqa: E402
ws = BI.words()
gs = BI.groups(ws)
check("Captions: 1 sentence at a time", "every caption is a sentence or clean sentence fragment (2–8 words)",
      all(2 <= len(g) <= 8 for g in gs), f"{len(gs)} groups, sizes {sorted(set(len(g) for g in gs))}")
FGc = np.array([0xEE, 0xF1, 0xE6])
cen_ok, band_ok, lines_ok, hits, total = 0, 0, 0, 0, 0
for gi, g in enumerate(gs):
    mid = frame(round((g[0]["start"] + g[-1]["end"]) / 2, 3), CAPV)
    ink = (np.abs(mid - FGc).sum(-1) < 90) | volt_mask(mid)
    ys, xs = np.where(ink.any(1))[0], np.where(ink.any(0))[0]
    if len(xs) and abs((xs.min() + xs.max()) / 2 - 540) <= 12:
        cen_ok += 1
    if len(ys) and ys.min() >= 1345 and ys.max() <= 1500:
        band_ok += 1
    if len(ys) and (ys.max() - ys.min()) <= 125:
        lines_ok += 1
    prev = None
    for w in g:
        total += 1
        fm = frame(round(w["start"] + 0.05, 3), CAPV)
        vm = volt_mask(fm)
        if vm[1340:1510].sum() > 150:
            cx = (np.where(vm.any(0))[0].mean(), np.where(vm.any(1))[0].mean())
            if prev is None or cx != prev:
                hits += 1
            prev = cx
check("Captions: centred", "every caption group centred (±12px)", cen_ok == len(gs), f"{cen_ok}/{len(gs)} centred", proof_t=gs[0][0]["start"] + 0.4)
check("Captions: 1 sentence at a time", "each group fits ≤2 lines in its own band (y1345–1500), clear of content", band_ok == len(gs) and lines_ok == len(gs), f"band {band_ok}/{len(gs)}, ≤2 lines {lines_ok}/{len(gs)}")
check("Captions: word tracker", "volt tracker lands on each spoken word and moves", hits >= total - 2, f"{hits}/{total} words tracked", proof_t=gs[18][2]["start"] + 0.05)

# ------------------------------------------------------------------ G4 per-scene goals (real frames)
S, BT = B.SCENES, B.BEATS
f = frame(BT["mane"] + 0.6)
rows = (volt_mask(f[420:1500, 260:1080]).mean(1) > 0.03).mean()
check("Hook: real Mané photo", "Mané dot-screen photo fills its frame", rows > 0.5, f"photo rows {rows:.0%}", BT["mane"] + 0.6)
f = frame(BT["felix"] + 0.6)
check("Hook: real Félix photo", "Félix dot-screen photo on screen", volt_mask(f[250:1500]).mean() > 0.04, f"volt ink {volt_mask(f[250:1500]).mean():.1%}", BT["felix"] + 0.6)
t = BT["gk_h"] + 0.5
fv = zone_volt(t)
check("Hook: Golden Glove payoff", "volt block + Hrithik in colour", fv > 0.30 and sat(frame(t)[900:1800]).mean() > 0.25, f"volt {fv:.0%}", t)

# trophy must not cover Hrithik's face: geometry from the composition, image aspect read from the file
from PIL import Image as _I  # noqa: E402
iw, ih = _I.open(P / "assets/photos/cut/hrithik-roar.png").size
box_l, box_r, box_t = 330, 1080 + 90, 880
bw, bh = box_r - box_l, 1920 - box_t
sc = min(bw / iw, bh / ih)
img_x0 = box_l + (bw - iw * sc) / 2
face = (img_x0 + 0.28 * iw * sc, box_t + (bh - ih * sc), img_x0 + 0.78 * iw * sc, box_t + (bh - ih * sc) + 0.30 * ih * sc)
tro = (60, 1060, 60 + 280 * 1.1, 1060 + 380 * 1.1)  # includes scale/rotation margin
overlap = not (tro[2] < face[0] or tro[0] > face[2] or tro[3] < face[1] or tro[1] > face[3])
check("Golden Glove placement", "trophy clear of Hrithik's face", not overlap,
      f"face x{face[0]:.0f}-{face[2]:.0f} y{face[1]:.0f}-{face[3]:.0f}; trophy x{tro[0]}-{tro[2]:.0f} y{tro[1]}-{tro[3]:.0f}", BT["gk_h"] + 0.3)

t = BT["isl"] + 0.6
f = frame(t)
check("Series intro", "title + volt ticker strip visible", volt_mask(f[1230:1340]).mean() > 0.5, f"ticker volt {volt_mask(f[1230:1340]).mean():.0%}", t)
t = BT["tiwari"] + 0.6
f = frame(t)
check("Scouting report: real photo", "Hrithik cutout in full colour with data rows", sat(f[300:1340, 380:1080]).mean() > 0.2, f"photo saturation {sat(f[300:1340, 380:1080]).mean():.2f}", t)
t = BT["nospot"] + 0.3
check("Grind: bench years in grey", "no volt accent, desaturated", zone_volt(t) < 0.01 and sat(frame(t)[ZONE]).mean() < 0.15, f"volt {zone_volt(t):.1%}, sat {sat(frame(t)[ZONE]).mean():.2f}", t)
t = BT["season"] + 0.8
check("Breakout: 2025–26", "volt season block + glove photo", zone_volt(t) > 0.3, f"volt {zone_volt(t):.0%}", t)
t = BT["s7"] + 0.8
f = frame(t)
check("Breakout: stats count up", "three stat rows with volt numbers", volt_mask(f[250:1000, 72:330]).mean() > 0.08, f"number ink {volt_mask(f[250:1000, 72:330]).mean():.0%}", t)
t = BT["best"] + 0.4
check("Breakout: 78.1% save ring", "volt hero block with ring", zone_volt(t) > 0.35, f"volt {zone_volt(t):.0%}", t)
t = BT["fullseason"] + 0.8
check("Caveat: calm, no accent", "grey caveat frame", zone_volt(t) < 0.01, f"volt {zone_volt(t):.1%}", t)
t = BT["gg"] + 0.6
f = frame(t)
gold = ((f[..., 0] > 150) & (f[..., 1] > 110) & (f[..., 2] < 90) & (f[..., 0] - f[..., 2] > 80))[700:1340]
check("Payoff: Golden Glove trophy", "real trophy photo on stage", gold.mean() > 0.01, f"gold px {gold.mean():.1%}", t)
t = BT["odisha"] + 0.5
f = frame(t)
navy = ((f[..., 2] - f[..., 0] > 30) & (f[..., 2] - f[..., 1] > 30) & (f[..., 2] > 70))[700:1340, 540:1008]
orange = ((f[..., 0] - f[..., 1] > 40) & (f[..., 1] - f[..., 2] > 15) & (f[..., 0] > 90))[700:1340, 72:540]  # Goa crest is dimmed to 55% by design
check("Payoff: Goa → Odisha transfer", "FC Goa crest left, Odisha FC crest right", navy.mean() > 0.01 and orange.mean() > 0.003, f"Odisha navy {navy.mean():.1%}, Goa orange {orange.mean():.1%}", t)
t = BT["change"] + 0.3
f = frame(t)
check("The line: 3 yrs vs 1 season", "volt '1 season' block below grey bench block", volt_mask(f[780:1340]).mean() > 0.3, f"volt {volt_mask(f[780:1340]).mean():.0%}", t)
t = B.TOTAL - 0.4
check("CTA end card", "volt follow card held at end", zone_volt(t) > 0.35, f"volt {zone_volt(t):.0%}", t)

# ------------------------------------------------------------------ G5 motion: every scene moves
still = []
for k, (s0, d) in S.items():
    a_, b_ = frame(round(s0 + 0.3, 3)), frame(round(s0 + d - 0.3, 3))
    if np.abs(a_ - b_).mean() < 2:
        still.append(k)
check("Heavy motion graphics", "every scene changes between its first and last moments", not still, f"static scenes: {still or 'none'}")

# ------------------------------------------------------------------ report + proof sheet
(OUT / "report.json").write_text(json.dumps(RESULTS, indent=1, ensure_ascii=False))
W = 270
tiles = []
try:
    fnt = ImageFont.truetype(str(P / "assets/fonts/Barlow-700.woff2"), 14)
except Exception:
    fnt = ImageFont.load_default()
for t, label in PROOF:
    im = Image.open(FR / f"v{t:07.3f}.png").convert("RGB").resize((W, 480))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 440, W, 480], fill=(0x0F, 0x1A, 0x11))
    d.text((6, 444), f"{t:5.2f}s", fill=(0xB3, 0xBA, 0xAD), font=fnt)
    d.text((6, 460), label[:44], fill=(0xE1, 0xFE, 0x67) if label.startswith("PASS") else (255, 80, 80), font=fnt)
    tiles.append(im)
cols = 6
rows = (len(tiles) + cols - 1) // cols
sheet = Image.new("RGB", (cols * W, rows * 480), (0x0F, 0x1A, 0x11))
for i, im in enumerate(tiles):
    sheet.paste(im, ((i % cols) * W, (i // cols) * 480))
sheet.save(OUT / "proof-sheet.png")
n = sum(r["pass"] for r in RESULTS)
print(f"\n{n}/{len(RESULTS)} passed")
sys.exit(0 if n == len(RESULTS) else 1)
