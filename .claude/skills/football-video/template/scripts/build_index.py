"""Writes index.html (scene slots, frame chrome, whip transitions, audio) and
compositions/captions.html (sentence captions with a live word tracker) from the
VO transcript and the timing tables in build_scenes.py."""
import json

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build_scenes as B  # noqa: E402

P = B.PROJ
# EPISODE: Jai's VO file and its exact length (ffprobe)
VO = "assets/audio/vo.wav"
VO_DUR = 64.22
TOTAL = B.TOTAL
BG, VOLT, FG, MUTED = B.BG, B.VOLT, B.FG, B.MUTED

# EPISODE: ASR mis-hearings -> approved script spelling (timing stays real). Read the transcript, list every wrong name.
FIX = {"Mane": "Mané", "Joao": "João", "Phoenix": "Félix.", "Rithik": "Hrithik", "call": "call-up",
       "2025-26": "2025–26"}
DROP_AFTER = {"call": "up"}  # merge "call" + "up"


def words():
    raw = json.loads((P / "assets/audio/transcript.json").read_text())
    raw = raw if isinstance(raw, list) else raw["words"]
    out, skip = [], False
    for i, w in enumerate(raw):
        if skip:
            out[-1]["end"] = w["end"]; skip = False; continue
        txt = FIX.get(w["text"], w["text"])
        if w["text"] in DROP_AFTER and i + 1 < len(raw) and raw[i + 1]["text"] == DROP_AFTER[w["text"]]:
            skip = True
        out.append({"text": txt, "start": w["start"], "end": w["end"]})
    return out


PREF = {"and", "so", "if", "from", "before", "a", "was"}


def _split(ws, max_words=8):
    if len(ws) <= max_words:
        return [ws]
    mid = len(ws) / 2
    best = min(range(2, len(ws) - 1),
               key=lambda i: (abs(i - mid) - (1.5 if ws[i]["text"].lower() in PREF else 0), abs(i - mid), i))
    return _split(ws[:best], max_words) + _split(ws[best:], max_words)


def groups(ws):
    sents, cur = [], []
    for w in ws:
        cur.append(w)
        if w["text"][-1] in ".?!":
            sents.append(cur); cur = []
    if cur:
        sents.append(cur)
    out = []
    for s in sents:
        key = " ".join(w["text"] for w in s)
        if key in MANUAL:
            cuts = [0] + MANUAL[key] + [len(s)]
            out += [s[a:b] for a, b in zip(cuts, cuts[1:])]
        else:
            out += _split(s)
    return out


# EPISODE: hand-set break points where the balanced split reads badly
MANUAL = {"This time it's a 24-year-old six-foot-three goalkeeper from Assam.": [5]}


def captions_html(gs):
    body, js = [], []
    for gi, g in enumerate(gs):
        spans = "".join(f'<span class="w" id="w{gi}_{wi}" data-layout-allow-overlap>{w["text"]}</span> ' for wi, w in enumerate(g))
        body.append(f'<div class="cg" id="g{gi}">{spans}</div>')
        g_end = gs[gi + 1][0]["start"] if gi + 1 < len(gs) else g[-1]["end"] + 0.4
        g_end = min(g_end, g[-1]["end"] + 0.6)
        js.append(f'tl.set("#g{gi}", {{ opacity: 1 }}, {g[0]["start"]:.2f}); tl.set("#g{gi}", {{ opacity: 0 }}, {g_end:.2f});')
        for wi, w in enumerate(g):
            nxt = g[wi + 1]["start"] if wi + 1 < len(g) else w["end"]
            js.append(f'on("#w{gi}_{wi}", {w["start"]:.2f}, {max(nxt, w["start"] + 0.08):.2f});')
    return f"""<!doctype html>
<html>
  <head><meta charset="UTF-8" /></head>
  <body>
    <template>
      <style>
      @font-face {{ font-family: "Barlow"; src: url("assets/fonts/Barlow-700.woff2") format("woff2"); font-weight: 600 900; font-display: block; }}
        #root {{ position: absolute; inset: 0; pointer-events: none; font-family: "Barlow", sans-serif; }}
        .cg {{ position: absolute; left: 80px; right: 80px; bottom: 436px; text-align: center; opacity: 0;
              font-weight: 800; font-size: 42px; line-height: 1.22; text-transform: uppercase; color: {FG}; }}
        .w {{ display: inline-block; background: {BG}; padding: 1px 9px; margin: 0 -2px 4px; }}
      </style>
      <div id="root" data-composition-id="captions" data-width="1080" data-height="1920">
        {"".join(body)}
      </div>
      <script>
        (function () {{
          var tl = gsap.timeline({{ paused: true }});
          function on(sel, a, b) {{
            tl.set(sel, {{ backgroundColor: "{VOLT}", color: "{BG}" }}, a);
            tl.set(sel, {{ backgroundColor: "{BG}", color: "{FG}" }}, b);
          }}
          {chr(10).join("          " + j for j in js)}
          window.__timelines["captions"] = tl;
        }})();
      </script>
    </template>
  </body>
</html>
"""


def beat(k):
    return B.BEATS[k]


SFX = [  # EPISODE: (file, global time, dur, volume). Clicks only: cuts 0.7, slams 0.8. Chime/sparkle on trophy beats.
    ("click", beat("mane"), 0.3, 0.8), ("click", beat("felix"), 0.3, 0.8),
    ("click", beat("before") - .1, 0.3, 0.7), ("click", beat("now") - .05, 0.3, 0.8),
    ("click", beat("welcome") - .2, 0.3, 0.7), ("click", beat("welcome"), 0.3, 0.8),
    ("click", B.SCENES["subject-intro"][0] - .2, 0.3, 0.7), ("click", beat("tiwari"), 0.3, 0.8),
    ("click", B.SCENES["grind"][0] - .2, 0.3, 0.7), ("click-soft", beat("years"), .37, .5), ("click-soft", beat("years") + .16, .37, .5),
    ("click", B.SCENES["breakout"][0] - .2, 0.3, 0.7), ("click", beat("season") - .1, 0.3, 0.8),
    ("riser", beat("s10") - 1.0, 7.0, .3),
    ("click", beat("s10"), 0.3, 0.8), ("click", beat("s5"), 0.3, 0.8), ("click", beat("s7"), 0.3, 0.8),
    ("click", beat("s78") - .1, 0.3, 0.8), ("click", B.SCENES["caveat"][0] - .2, 0.3, 0.7),
    ("click", B.SCENES["payoff"][0] - .2, 0.3, 0.7), ("chime", beat("gg"), 2.5, .7), ("sparkle", beat("gg"), 1.8, .55),
    ("click", beat("callup") - .15, 0.3, 0.7), ("click", beat("thisweek") - .2, 0.3, 0.7), ("click", beat("odisha"), 0.3, 0.8),
    ("click", B.SCENES["theline"][0] - .2, 0.3, 0.7), ("click", beat("one") - .1, 0.3, 0.8),
    ("click", B.SCENES["cta"][0] - .2, 0.3, 0.7),
]


def index_html():
    slots = "".join(
        f'      <div id="el-{k}" data-composition-id="{k}" data-composition-src="compositions/{k}.html" data-start="{s:.2f}" data-duration="{d:.2f}" data-track-index="1" data-width="1080" data-height="1920"></div>\n'
        for k, (s, d) in B.SCENES.items())
    c0 = B.SCENES["series-intro"][0]
    cav0, cav1 = B.SCENES["caveat"][0], B.SCENES["payoff"][0]
    sfx = "".join(
        f'      <audio id="sfx-{i}" src="assets/audio/sfx/{f}.mp3" data-start="{t:.2f}" data-duration="{d}" data-track-index="{20 + i}" data-volume="{v}"></audio>\n'
        for i, (f, t, d, v) in enumerate(SFX))
    cuts = [round(s, 2) for k, (s, d) in B.SCENES.items() if k != "hook"]
    return f"""<!doctype html>
<html lang="en" data-resolution="portrait" data-composition-variables='[{{"id":"sceneOpacity","type":"number","label":"Scene layer opacity (tests only)","default":1}}]'>
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <title>Rising ISL Talents — Ep.1: Hrithik Tiwari</title>
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      @font-face {{ font-family: "Barlow"; src: url("assets/fonts/Barlow-700.woff2") format("woff2"); font-weight: 600 900; font-display: block; }}
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ width: 1080px; height: 1920px; overflow: hidden; background: {BG}; }}
      #root {{ position: relative; width: 100%; height: 100%; overflow: hidden; font-family: "Barlow", sans-serif; }}
      [data-composition-id="root"] > div[data-composition-src] {{ position: absolute; inset: 0; }}
      [data-composition-id="root"] > div[data-composition-src]:not(#el-captions), .chrome, #whip {{ opacity: var(--sceneOpacity, 1); }}
      .chrome {{ position: absolute; left: 72px; right: 72px; z-index: 50; display: flex; justify-content: space-between; align-items: center; font-weight: 700; font-size: 26px; letter-spacing: 0.14em; text-transform: uppercase; color: {MUTED}; }}
      #hdr {{ top: 150px; }}
      #ftr {{ bottom: 360px; padding-top: 22px; border-top: 2px solid {MUTED}; }}
      #ftr .who {{ color: {VOLT}; }}
      #whip {{ position: absolute; inset: 0; z-index: 60; pointer-events: none; overflow: hidden; }}
      #whip i {{ position: absolute; top: -200px; bottom: -200px; width: 520px; left: -700px; transform: skewX(-16deg); }}
      #whip i:nth-child(1), #whip i:nth-child(3) {{ background: {VOLT}; }} #whip i:nth-child(2) {{ background: {BG}; }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="root" data-width="1080" data-height="1920" data-duration="{TOTAL}">
{slots}
      <div id="el-captions" data-composition-id="captions" data-composition-src="compositions/captions.html" data-track-kind="captions" data-start="0" data-duration="{VO_DUR + 0.6:.2f}" data-track-index="3" data-width="1080" data-height="1920"></div>
      <div id="hdr" class="chrome clip" data-start="{c0}" data-duration="{TOTAL - c0:.2f}" data-track-index="4"><span>Rising ISL Talents</span><span>Ep. 01</span></div>
      <div id="ftr" class="chrome clip" data-start="{c0}" data-duration="{TOTAL - c0:.2f}" data-track-index="5"><span>Scouting report</span><span class="who" id="who">&nbsp;</span></div>
      <div id="whip" class="clip" data-layout-allow-overflow data-start="0" data-duration="{TOTAL}" data-track-index="6"><i data-layout-allow-overflow></i><i data-layout-allow-overflow></i><i data-layout-allow-overflow></i></div>

      <audio id="el-vo" src="{VO}" data-start="0" data-duration="{VO_DUR}" data-track-index="10" data-volume="1"></audio>
      <audio id="el-bgm" src="assets/audio/music.wav" data-start="0" data-duration="{TOTAL}" data-track-index="11" data-volume="0.12"></audio>
      <audio id="el-crowd-a" src="assets/audio/crowd-bed.wav" data-start="0" data-duration="{cav0:.2f}" data-track-index="12" data-volume="0.16"></audio>
      <audio id="el-crowd-b" src="assets/audio/crowd-bed.wav" data-start="{cav0:.2f}" data-media-start="{cav0:.2f}" data-duration="{cav1 - cav0:.2f}" data-track-index="13" data-volume="0.05"></audio>
      <audio id="el-crowd-c" src="assets/audio/crowd-bed.wav" data-start="{cav1:.2f}" data-media-start="{cav1:.2f}" data-duration="{TOTAL - cav1:.2f}" data-track-index="14" data-volume="0.18"></audio>
{sfx}    </div>
    <script>
      const tl = gsap.timeline({{ paused: true }});
      tl.call(function () {{ document.getElementById("who").innerHTML = "&nbsp;"; }}, null, 0);
      tl.call(function () {{ document.getElementById("who").textContent = "Hrithik Tiwari · GK"; }}, null, {beat("tiwari") + 0.5:.2f});
      gsap.set("#whip i", {{ x: 0 }});
      {cuts}.forEach(function (c) {{
        tl.fromTo("#whip i", {{ x: 0 }}, {{ x: 2400, duration: 0.42, ease: "expo.inOut", stagger: 0.05, immediateRender: false }}, c - 0.24);
      }});
      window.__timelines["root"] = tl;
    </script>
  </body>
</html>
"""


if __name__ == "__main__":
    B.write_all()
    gs = groups(words())
    (P / "compositions/captions.html").write_text(captions_html(gs))
    (P / "index.html").write_text(index_html())
    (P / "assets/audio/caption-groups.json").write_text(json.dumps([[w["text"] for w in g] for g in gs], ensure_ascii=False))
    print("captions groups:", len(gs))
    for g in gs:
        print(" ", f'{g[0]["start"]:5.2f}', " ".join(w["text"] for w in g))
