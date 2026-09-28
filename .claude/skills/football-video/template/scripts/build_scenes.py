"""Pitch + Volt scene generator. Reference episode: Hrithik Tiwari (Rising ISL Talents Ep.1).

Reuse as-is: BASE_CSS, JS_LIB, split(), photo(), L()/D(), page(). Rewrite per episode:
SCENES, BEATS (from the VO transcript), TOTAL, and every OUT[...] scene block.


All beat times live in BEATS (global seconds, from the VO transcript) and SCENES
(start, duration). Scene scripts use local time = global - scene start, so a new
voiceover only needs these two tables updated.
"""
import math
from pathlib import Path

PROJ = Path(__file__).resolve().parents[1]
COMP = PROJ / "compositions"

SCENES = {
    "hook": (0.0, 9.46), "series-intro": (9.46, 4.35), "subject-intro": (13.81, 7.12),
    "grind": (20.93, 3.98), "breakout": (24.91, 16.45), "caveat": (41.36, 4.85),
    "payoff": (46.21, 7.38), "theline": (53.59, 5.56), "cta": (59.15, 7.05),
}
TOTAL = 66.2
BEATS = {
    "mane": 0.25, "felix": 2.05, "before": 3.40, "starting": 4.88, "now": 6.53, "golden_h": 7.53, "gk_h": 8.42,
    "welcome": 9.46, "isl": 12.24,
    "age": 14.67, "height": 15.82, "position": 16.89, "assam": 18.22, "hrithik": 19.28, "tiwari": 19.90,
    "three": 20.93, "years": 21.27, "backup": 21.92, "nospot": 23.52,
    "season": 25.07, "s10": 28.77, "s5": 30.02, "s7": 31.89, "fewest": 34.08, "s78": 36.06, "best": 38.65,
    "just10": 41.68, "fullseason": 43.49,
    "gg": 47.68, "callup": 48.83, "india": 49.81, "thisweek": 50.78, "odisha": 52.53,
    "bench3": 53.59, "one": 55.83, "change": 57.98,
    "follow": 59.15, "wefind": 60.90, "rising": 61.71, "soyou": 62.64,
}

VOLT, BG, FG, MUTED, LINE = "#e1fe67", "#0f1a11", "#eef1e6", "#b3baad", "#3d4a3f"
CUT = "assets/photos/cut/"

BASE_CSS = f"""
      @font-face {{ font-family: "Big Shoulders Display"; src: url("assets/fonts/BigShouldersDisplay-800.woff2") format("woff2"); font-weight: 800; font-display: block; }}
      @font-face {{ font-family: "Barlow"; src: url("assets/fonts/Barlow-500.woff2") format("woff2"); font-weight: 400 500; font-display: block; }}
      @font-face {{ font-family: "Barlow"; src: url("assets/fonts/Barlow-700.woff2") format("woff2"); font-weight: 600 900; font-display: block; }}
        #root {{ position: absolute; inset: 0; background: {BG}; overflow: hidden; color: {FG}; font-family: "Barlow", sans-serif; }}
        #s {{ position: absolute; inset: 0; opacity: var(--sceneOpacity, 1); }}
        .d {{ font-family: "Big Shoulders Display", sans-serif; font-weight: 800; text-transform: uppercase; line-height: 0.9; }}
        .lab {{ font-family: "Barlow", sans-serif; font-weight: 700; font-size: 30px; letter-spacing: 0.14em; text-transform: uppercase; color: {MUTED}; }}
        .ln {{ display: block; overflow: hidden; padding-top: 0.06em; }}
        .ch {{ display: inline-block; }}
        .ln > span {{ display: inline-block; padding-top: 0.16em; }}
        .volt {{ color: {VOLT}; }}
        .ab {{ position: absolute; }}
        .ph {{ position: absolute; }}
        .ph img, .ph .sh, .ph .g1, .ph .g2 {{ position: absolute; inset: 0; width: 100%; height: 100%; }}
        .ph img {{ object-fit: contain; object-position: 50% 100%; }}
        .ph .sh, .ph .g1, .ph .g2 {{ -webkit-mask-size: contain; mask-size: contain; -webkit-mask-repeat: no-repeat; mask-repeat: no-repeat; -webkit-mask-position: 50% 100%; mask-position: 50% 100%; }}
        .ph .sh {{ background: {VOLT}; transform: translate(26px, 20px); }}
        .ph .sh.dark {{ background: {BG}; }}
        .ph .g1 {{ background: {VOLT}; opacity: 0; }}
        .ph .g2 {{ background: {FG}; opacity: 0; }}
        .out {{ color: {BG}; -webkit-text-stroke: 3px #2e3d31; }}
        .row {{ display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 2px solid {LINE}; overflow: hidden; }}
        .blk {{ position: absolute; background: {VOLT}; color: {BG}; clip-path: inset(100% 0 0 0); }}
        .blk .lab {{ color: {BG}; }}
        .tag {{ display: inline-block; background: {VOLT}; color: {BG}; font-family: "Barlow", sans-serif; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; }}
"""

JS_LIB = """
          var tl = gsap.timeline({ paused: true });
          function shake(t, a) { a = a || 14;
            tl.to("#s", { x: -a, y: a * 0.4, duration: 0.035, ease: "none" }, t);
            tl.to("#s", { x: a * 0.7, y: -a * 0.3, duration: 0.035, ease: "none" }, t + 0.04);
            tl.to("#s", { x: 0, y: 0, duration: 0.035, ease: "none" }, t + 0.08); }
          function chars(sel, t, st) {
            tl.fromTo(sel + " .ch", { yPercent: 115, rotate: 10 }, { yPercent: 0, rotate: 0, duration: 0.5, ease: "expo.out", stagger: st || 0.022 }, t); }
          function rise(sel, t, d) { tl.fromTo(sel, { yPercent: 110 }, { yPercent: 0, duration: d || 0.22, ease: "power4.out" }, t); }
          function show(sel, t) { tl.set(sel, { opacity: 1 }, t); }
          function hide(sel, t) { tl.set(sel, { opacity: 0 }, t); }
          function wipe(sel, t, d) { tl.fromTo(sel, { clipPath: "inset(100% 0 0 0)" }, { clipPath: "inset(0% 0 0 0)", duration: d || 0.22, ease: "expo.out" }, t); }
          function slideIn(sel, t, fx, fy, d) {
            tl.fromTo(sel, { x: fx || 0, y: fy || 0, filter: "blur(14px)" }, { x: 0, y: 0, filter: "blur(0px)", duration: d || 0.5, ease: "expo.out" }, t); }
          function slideOut(sel, t, tx, d) { tl.to(sel, { x: tx, filter: "blur(14px)", duration: d || 0.28, ease: "expo.in" }, t); }
          function punch(sel, t, s) { tl.fromTo(sel, { scale: s || 1.14 }, { scale: 1, duration: 0.45, ease: "power3.out" }, t); }
          function glitch(id, t) {
            var a = "#" + id + " .g1", b = "#" + id + " .g2";
            [[0, 16, -10], [0.04, -12, 14], [0.08, 8, -6], [0.12, 0, 0]].forEach(function (k) {
              tl.set(a, { opacity: k[1] ? 0.85 : 0, x: k[1] }, t + k[0]);
              tl.set(b, { opacity: k[2] ? 0.6 : 0, x: k[2] }, t + k[0]); }); }
          function count(sel, to, t, d, dec, suf) {
            var el = document.querySelector(sel), o = { v: 0 }; suf = suf || "";
            tl.fromTo(o, { v: 0 }, { v: to, duration: d, ease: "power2.out", onUpdate: function () {
              el.textContent = (dec ? o.v.toFixed(dec) : Math.round(o.v)) + suf; } }, t); }
          function draw(sel, t, d, axis, ease) {
            var p = {}; p[axis || "scaleX"] = 0; var q = {}; q[axis || "scaleX"] = 1;
            q.duration = d || 0.4; q.ease = ease || "expo.out"; tl.fromTo(sel, p, q, t); }
"""


def split(text, cls=""):
    out = []
    for c in text:
        out.append('<span class="ch" data-layout-allow-overlap>&nbsp;</span>' if c == " " else f'<span class="ch" data-layout-allow-overlap>{c}</span>')
    return f'<span class="{cls}">{"".join(out)}</span>'


def photo(pid, name, box, shadow="volt", glitch=False, extra=""):
    src = CUT + name + ".png"
    mask = f'style="-webkit-mask-image:url({src});mask-image:url({src})"'
    sh = "" if shadow is None else f'<div class="sh{" dark" if shadow == "dark" else ""}" {mask}></div>'
    gl = f'<div class="g1" {mask}></div><div class="g2" {mask}></div>' if glitch else ""
    return f'<div class="ph" id="{pid}" style="{box}" data-layout-allow-overflow>{sh}<img id="{pid}-img" src="{src}" {extra} />{gl}</div>'


def D(scene):
    return SCENES[scene][1]


def L(scene, beat):
    """local time of a global beat inside a scene"""
    return round(BEATS[beat] - SCENES[scene][0], 3)


def page(cid, css, body, js):
    return f"""<!doctype html>
<html>
  <head><meta charset="UTF-8" /></head>
  <body>
    <template>
      <style>{BASE_CSS}{css}
      </style>
      <div id="root" data-composition-id="{cid}" data-width="1080" data-height="1920">
        <div id="s">
{body.replace('<div class="ln"', '<div class="ln" data-layout-allow-overlap')}
        </div>
      </div>
      <script>
        (function () {{{JS_LIB}
{js}
          window.__timelines["{cid}"] = tl;
        }})();
      </script>
    </template>
  </body>
</html>
"""


OUT = {}

# ---------------------------------------------------------------- HOOK
h = "hook"
OUT[h] = page(h, f"""
        .bgw {{ position: absolute; left: -40px; top: 180px; font-size: 560px; white-space: nowrap; opacity: 0; }}
        .nm {{ position: absolute; left: 72px; bottom: 600px; opacity: 0; }}
        .nm .lab {{ margin-bottom: 14px; }}
        .nm .d {{ font-size: 250px; }}
        #mane, #felix {{ opacity: 0; }}
        #vs {{ position: absolute; left: 72px; right: 72px; top: 250px; height: 440px; opacity: 0; display: flex; gap: 24px; }}
        .tile {{ flex: 1; position: relative; border: 3px solid {VOLT}; overflow: hidden; }}
        .tile .ph {{ left: 0; right: 0; top: 20px; bottom: 0; }}
        .tile .lab {{ position: absolute; left: 16px; bottom: 12px; color: {BG}; background: {VOLT}; padding: 4px 10px; }}
        #q {{ position: absolute; left: 72px; top: 770px; font-size: 360px; opacity: 0; transform-origin: 50% 50%; }}
        #ql {{ position: absolute; left: 470px; top: 860px; opacity: 0; }}
        #jl {{ position: absolute; left: 72px; top: 1120px; opacity: 0; }}
        #jl .d {{ font-size: 104px; }}
        #hk {{ left: 0; right: 0; top: 0; bottom: 0; }}
        #hkt {{ position: absolute; left: 72px; right: 72px; top: 250px; color: {BG}; }}
        #hkt .d {{ font-size: 170px; }}
        #roar {{ left: 330px; right: -90px; top: 880px; bottom: 0; opacity: 0; }}
        #tro {{ left: 60px; top: 1060px; width: 280px; height: 380px; opacity: 0; }}
""", f"""
          <div class="d out bgw" data-layout-allow-overlap id="bw1">Mané Mané</div>
          <div class="d out bgw" data-layout-allow-overlap id="bw2">Félix Félix</div>
          {photo("mane", "mane-lfc-a", "left:260px;right:-120px;top:420px;bottom:0", shadow=None, glitch=True)}
          {photo("felix", "felix-barca", "left:-80px;right:-140px;top:560px;bottom:0", shadow=None, glitch=True)}
          <div class="nm" id="n1"><div class="lab">He faced</div><div class="ln">{split("Mané.", "d")}</div></div>
          <div class="nm" id="n2"><div class="lab">And</div><div class="ln">{split("Félix.", "d volt")}</div></div>
          <div id="vs">
            <div class="tile">{photo("t1", "mane-bayern-studio", "", shadow=None)}<span class="lab">Mané</span></div>
            <div class="tile">{photo("t2", "felix-atleti", "", shadow=None)}<span class="lab">Félix</span></div>
          </div>
          <div class="d out" id="q" style="-webkit-text-stroke: 5px {VOLT}">??</div>
          <div class="lab" id="ql">Shirt number<br />unassigned</div>
          <div id="jl">
            <div class="ln">{split("Before he had", "d")}</div>
            <div class="ln" id="jl2">{split("a starting jersey", "d volt")}</div></div>
          <div class="blk" id="hk"></div>
          {photo("roar", "hrithik-roar", "", shadow="dark", glitch=True)}
          {photo("tro", "golden-glove-trophy", "", shadow=None)}
          <div id="hkt">
            <div class="ln"><span class="lab" style="color:{BG}">Now he's</span></div>
            <div class="ln" id="hk1">{split("India's", "d")}</div>
            <div class="ln" id="hk2">{split("Golden Glove", "d")}</div>
            <div class="ln" id="hk3">{split("Goalkeeper", "d")}</div>
          </div>
""", f"""
          gsap.set("#hkt", {{ opacity: 0 }});
          var m = {L(h,'mane')}, f = {L(h,'felix')}, b = {L(h,'before')}, n = {L(h,'now')};
          show("#bw1", m); tl.fromTo("#bw1", {{ x: 0 }}, {{ x: -600, duration: 1.1, ease: "none" }}, m);
          show("#mane", m); slideIn("#mane", m, 500, 0, 0.45); glitch("mane", m + 0.12); shake(m + 0.1);
          show("#n1", m); chars("#n1", m + 0.05);
          slideOut("#mane", f - 0.06, -1100); hide("#n1", f); hide("#bw1", f);
          show("#bw2", f); tl.fromTo("#bw2", {{ x: -500 }}, {{ x: 100, duration: 0.95, ease: "none" }}, f);
          show("#felix", f); slideIn("#felix", f, -600, 0, 0.45); glitch("felix", f + 0.12); shake(f + 0.1, 18);
          show("#n2", f); chars("#n2", f + 0.05);
          hide("#felix", b - 0.07); hide("#n2", b - 0.07); hide("#bw2", b - 0.07);
          show("#vs", b - 0.07); tl.fromTo("#vs .tile", {{ yPercent: 40, opacity: 0 }}, {{ yPercent: 0, opacity: 1, duration: 0.4, ease: "expo.out", stagger: 0.08 }}, b - 0.07);
          show("#q", b); tl.fromTo("#q", {{ rotateY: 90, scale: 0.6, transformPerspective: 900 }}, {{ rotateY: 0, scale: 1, duration: 0.6, ease: "expo.out" }}, b);
          tl.to("#q", {{ rotate: -6, duration: 1.6, ease: "none" }}, b + 0.6);
          show("#jl", b); chars("#jl .ln:nth-of-type(1)", b + 0.1); show("#ql", b + 0.3); chars("#jl2", {L(h,'starting')} - 0.05);
          wipe("#hk", n - 0.06, 0.18); hide("#vs", n); hide("#q", n); hide("#jl", n); hide("#ql", n);
          show("#roar", n); slideIn("#roar", n, 0, 700, 0.55); glitch("roar", n + 0.2); shake(n + 0.1, 18);
          show("#hkt", n); chars("#hk1", n + 0.02); chars("#hk2", {L(h,'golden_h')} - 0.1); chars("#hk3", {L(h,'gk_h')} - 0.1);
          show("#tro", {L(h,'golden_h')}); tl.fromTo("#tro", {{ scale: 0.3, rotate: -25 }}, {{ scale: 1, rotate: 8, duration: 0.6, ease: "expo.out" }}, {L(h,'golden_h')});
          punch("#s", n, 1.08);
""")

# ---------------------------------------------------------------- SERIES INTRO
h = "series-intro"
OUT[h] = page(h, f"""
        #big01 {{ position: absolute; right: -60px; top: 200px; font-size: 900px; }}
        #ttl {{ position: absolute; left: 72px; right: 72px; top: 330px; }}
        #ttl .d {{ font-size: 230px; }}
        #bar {{ height: 18px; background: {VOLT}; margin-top: 36px; transform-origin: 0 50%; }}
        #mq {{ position: absolute; left: 0; right: 0; top: 1230px; height: 110px; background: {VOLT}; overflow: hidden; clip-path: inset(0 100% 0 0); }}
        #mqt {{ position: absolute; left: 0; top: 14px; white-space: nowrap; color: {BG}; font-size: 92px; }}
""", f"""
          <div class="d out" id="big01" data-layout-allow-overlap>01</div>
          <div id="ttl">
            <div class="lab">Episode 01</div>
            <div class="ln" id="t1">{split("Rising", "d")}</div>
            <div class="ln" id="t2">{split("ISL", "d volt")}</div>
            <div class="ln" id="t3">{split("Talents", "d")}</div>
            <div id="bar"></div>
          </div>
          <div id="mq"><div class="d" id="mqt">{" — ".join(["Scouting report", "Ep 01", "Hrithik Tiwari", "Goalkeeper"] * 3)}</div></div>
""", f"""
          tl.fromTo("#big01", {{ x: 400 }}, {{ x: 0, duration: {D(h)}, ease: "power2.out" }}, 0);
          chars("#t1", 0.02); chars("#t2", 0.12); chars("#t3", 0.22); shake(0.3, 10);
          draw("#bar", {L(h,'isl')} - 0.1, 0.4);
          tl.to("#mq", {{ clipPath: "inset(0 0% 0 0)", duration: 0.35, ease: "expo.out" }}, 0.5);
          tl.fromTo("#mqt", {{ x: 0 }}, {{ x: -1900, duration: {D(h) - 0.5}, ease: "none" }}, 0.5);
""")

# ---------------------------------------------------------------- SUBJECT INTRO
h = "subject-intro"
OUT[h] = page(h, f"""
        #hr {{ left: 380px; right: -110px; top: 300px; bottom: 580px; }}
        #bgn {{ position: absolute; left: -20px; top: 230px; font-size: 380px; line-height: 0.82; }}
        #col {{ position: absolute; left: 72px; width: 470px; top: 260px; }}
        #col .row {{ padding: 16px 0 10px; opacity: 0; }}
        #col .v {{ font-size: 104px; }}
        #ruler {{ position: absolute; left: 1004px; top: 330px; bottom: 580px; width: 4px; background: {VOLT}; transform-origin: 50% 100%; }}
        #ruler i {{ position: absolute; left: -16px; width: 36px; height: 3px; background: {VOLT}; }}
        #rl {{ position: absolute; right: 90px; top: 300px; padding: 6px 12px; font-size: 34px; opacity: 0; }}
        #xh, #xv {{ position: absolute; background: {VOLT}; }}
        #xh {{ left: 0; right: 0; top: 1060px; height: 3px; transform-origin: 0 50%; }}
        #xv {{ left: 300px; top: 250px; bottom: 580px; width: 3px; transform-origin: 50% 0; }}
        #geo {{ position: absolute; left: 318px; top: 1070px; font-size: 30px; opacity: 0; }}
        #nm {{ position: absolute; left: 72px; right: 72px; bottom: 590px; }}
        #nm .d {{ font-size: 200px; }}
""", f"""
          <div class="d out" id="bgn" data-layout-allow-overlap>Hrithik<br />Tiwari</div>
          {photo("hr", "hrithik-goa-studio", "", glitch=True)}
          <div id="ruler">{"".join(f'<i style="top:{p}%"></i>' for p in range(0, 101, 10))}</div>
          <div class="tag" id="rl">6'3"</div>
          <div id="col">
            <div class="lab" style="margin-bottom:14px">Scouting report — 001</div>
            <div class="row" id="r1"><span class="lab">Age</span><span class="d v volt" id="age">0</span></div>
            <div class="row" id="r2"><span class="lab">Height</span><span class="d v">6'3"</span></div>
            <div class="row" id="r3"><span class="lab">Pos</span><span class="d v">GK</span></div>
            <div class="row" id="r4"><span class="lab">From</span><span class="d v">Assam</span></div>
          </div>
          <div id="xh"></div><div id="xv"></div>
          <div class="lab" id="geo">26.2°N · 92.9°E — Assam, India</div>
          <div id="nm"><div class="ln" id="nm1">{split("Hrithik", "d")}</div><div class="ln" id="nm2">{split("Tiwari", "d volt")}</div></div>
""", f"""
          slideIn("#hr", 0.02, 700, 0, 0.6); glitch("hr", 0.4);
          tl.fromTo("#bgn", {{ y: 40 }}, {{ y: -80, duration: {D(h)}, ease: "none" }}, 0);
          var a = {L(h,'age')}, ht = {L(h,'height')}, p = {L(h,'position')}, s = {L(h,'assam')}, n = {L(h,'hrithik')};
          show("#r1", a); rise("#r1 .v", a); count("#age", 24, a, 0.6);
          show("#r2", ht); rise("#r2 .v", ht); draw("#ruler", ht - 0.1, 0.6, "scaleY");
          show("#rl", ht + 0.4); tl.fromTo("#rl", {{ scale: 1.6 }}, {{ scale: 1, duration: 0.25, ease: "power4.out" }}, ht + 0.4);
          show("#r3", p); rise("#r3 .v", p);
          show("#r4", s); rise("#r4 .v", s);
          draw("#xh", s - 0.05, 0.35); draw("#xv", s, 0.35, "scaleY"); show("#geo", s + 0.2);
          tl.to("#xh, #xv, #geo", {{ opacity: 0, duration: 0.15 }}, n - 0.2);
          chars("#nm1", n - 0.05); chars("#nm2", {L(h,'tiwari')} - 0.05); shake({L(h,'tiwari')}, 14); punch("#hr", n, 1.08);
""")

# ---------------------------------------------------------------- GRIND (no accent, grey)
h = "grind"
OUT[h] = page(h, f"""
        #root {{ background: #141715; color: #9ca197; }}
        .lab {{ color: #6f756c; }}
        #gt {{ left: 360px; right: -80px; top: 380px; bottom: 580px; opacity: 0.55; }}
        #n {{ position: absolute; left: 72px; top: 300px; font-size: 460px; color: #c3c7bf; line-height: 0.8; }}
        #ny {{ position: absolute; left: 72px; top: 800px; }}
        .yrs {{ position: absolute; left: 72px; right: 72px; top: 860px; display: flex; gap: 16px; }}
        .yr {{ flex: 1; height: 110px; border: 3px solid #4a4f48; position: relative; }}
        .yr b {{ position: absolute; inset: 0; background: #4a4f48; transform-origin: 0 50%; }}
        .yr span {{ position: absolute; left: 12px; bottom: 8px; }}
        #k {{ position: absolute; left: 72px; top: 1040px; }}
        #k .d {{ font-size: 96px; line-height: 1.05; color: #9ca197; }}
        #goa {{ position: absolute; right: 72px; top: 1050px; width: 150px; opacity: 0; }}
""", f"""
          {photo("gt", "hrithik-goa-training", "", shadow=None)}
          <div class="d" id="n">1</div>
          <div class="lab" id="ny">Years as backup</div>
          <div class="yrs">{"".join(f'<div class="yr" id="y{i}"><b></b><span class="lab">Yr {i}</span></div>' for i in (1, 2, 3))}</div>
          <div id="k"><div class="ln" id="k1">{split("Backup · FC Goa", "d")}</div><div class="ln" id="k2">{split("No settled spot", "d")}</div></div>
          <img id="goa" src="assets/logos/fc-goa.png" />
""", f"""
          var el = document.getElementById("n");
          tl.fromTo("#gt", {{ scale: 1.06 }}, {{ scale: 1, duration: {D(h)}, ease: "none" }}, 0);
          tl.call(function () {{ el.textContent = "1"; }}, null, 0);
          tl.fromTo("#y1 b", {{ scaleX: 0 }}, {{ scaleX: 1, duration: 0.15, ease: "none" }}, 0.02);
          tl.call(function () {{ el.textContent = "2"; }}, null, {L(h,'years') + 0.01});
          tl.fromTo("#y2 b", {{ scaleX: 0 }}, {{ scaleX: 1, duration: 0.15, ease: "none" }}, {L(h,'years')});
          tl.call(function () {{ el.textContent = "3"; }}, null, {L(h,'years') + 0.16});
          tl.fromTo("#y3 b", {{ scaleX: 0 }}, {{ scaleX: 1, duration: 0.15, ease: "none" }}, {L(h,'years') + 0.15});
          chars("#k1", {L(h,'backup')}, 0.012); show("#goa", {L(h,'backup')} + 0.3);
          chars("#k2", {L(h,'nospot')}, 0.012);
""")

# ---------------------------------------------------------------- BREAKOUT
h = "breakout"
R = 300
C = round(2 * math.pi * R, 1)
OUT[h] = page(h, f"""
        #yb {{ left: 72px; right: 72px; top: 250px; bottom: 580px; }}
        #yt {{ position: absolute; left: 52px; top: 40px; }}
        #yt .d {{ font-size: 230px; }}
        #gl {{ left: 150px; right: -90px; top: 640px; bottom: 580px; opacity: 0; }}
        #stats {{ position: absolute; left: 72px; right: 72px; top: 250px; opacity: 0; }}
        .st {{ padding: 6px 0 14px; opacity: 0; justify-content: flex-start; gap: 28px; }}
        .st .d {{ font-size: 240px; width: 250px; }}
        .st .t {{ font-weight: 700; font-size: 44px; line-height: 1.05; text-transform: uppercase; padding-bottom: 26px; }}
        #fw {{ font-size: 26px; padding: 8px 14px; margin-top: 12px; opacity: 0; }}
        #gl2 {{ left: 560px; right: -120px; top: 680px; bottom: 580px; opacity: 0; }}
        #hb {{ left: 72px; right: 72px; top: 250px; bottom: 580px; }}
        #ring {{ position: absolute; left: 50%; top: 380px; width: 680px; height: 680px; margin-left: -340px; margin-top: -340px; }}
        #ring circle {{ fill: none; stroke-width: 34; }}
        #pct {{ position: absolute; left: 0; right: 0; top: 280px; text-align: center; font-size: 220px; }}
        #hbl {{ position: absolute; left: 52px; top: 40px; }}
        #hbs {{ position: absolute; left: 52px; right: 420px; bottom: 44px; }}
        #hbs .d {{ font-size: 96px; }}
        #th {{ right: -40px; width: 470px; top: 560px; bottom: 580px; opacity: 0; }}
""", f"""
          <div class="blk" id="yb"><div id="yt"><div class="lab">Finally, his run</div><div class="ln" id="yr">{split("2025–26", "d")}</div></div></div>
          {photo("gl", "hrithik-goa-green-gloves", "", shadow="dark", glitch=True)}
          <div id="stats">
            <div class="row st" id="s1"><span class="d volt" id="c1">0</span><span class="t">Appearances</span></div>
            <div class="row st" id="s2"><span class="d volt" id="c2">0</span><span class="t">Clean sheets</span></div>
            <div class="row st" id="s3"><span class="d volt" id="c3">0</span><span class="t">Goals conceded<br /><span class="tag" id="fw">Fewest in league</span></span></div>
          </div>
          {photo("gl2", "hrithik-roar", "", glitch=True)}
          <div class="blk" id="hb">
            <div class="lab" id="hbl">Save rate</div>
            <svg id="ring" viewBox="0 0 680 680"><circle cx="340" cy="340" r="{R}" stroke="#c9e85a" /><circle id="arc" cx="340" cy="340" r="{R}" stroke="{BG}" stroke-dasharray="{C}" stroke-dashoffset="{C}" transform="rotate(-90 340 340)" /></svg>
            <div class="d" id="pct">0%</div>
            <div id="hbs"><div class="ln" id="hb1">{split("Best of any keeper", "d")}</div><div class="lab" style="color:{BG}">Indian Super League · 2025–26</div></div>
          </div>
          {photo("th", "hrithik-thumbs", "", shadow="dark")}
""", f"""
          var s = {L(h,'season')} - 0.1;
          wipe("#yb", s, 0.2); chars("#yr", s + 0.04, 0.03); shake(s + 0.1, 18);
          show("#gl", s + 0.15); slideIn("#gl", s + 0.15, 0, 700, 0.55); glitch("gl", s + 0.4);
          var st = {L(h,"s10")} - 0.3;
          tl.to("#yb, #gl", {{ opacity: 0, duration: 0.12 }}, st - 0.05);
          show("#stats", st); show("#gl2", st); slideIn("#gl2", st, 600, 0, 0.5);
          [["#s1", "#c1", 10, {L(h,'s10')}], ["#s2", "#c2", 5, {L(h,'s5')}], ["#s3", "#c3", 7, {L(h,'s7')}]].forEach(function (p) {{
            show(p[0], p[3] - 0.04); slideIn(p[0], p[3] - 0.04, -300, 0, 0.35); count(p[1], p[2], p[3] - 0.04, 0.5); shake(p[3], 12); }});
          glitch("gl2", {L(h,'s7')});
          show("#fw", {L(h,'fewest')}); tl.fromTo("#fw", {{ scale: 1.8, rotate: -8 }}, {{ scale: 1, rotate: -3, duration: 0.25, ease: "power4.out" }}, {L(h,'fewest')});
          var hz = {L(h,'s78')} - 0.1;
          tl.to("#stats, #gl2", {{ opacity: 0, duration: 0.1 }}, hz);
          wipe("#hb", hz, 0.2); shake(hz + 0.1, 22);
          tl.to("#arc", {{ strokeDashoffset: {round(C * (1 - 0.781), 1)}, duration: 1.3, ease: "expo.out" }}, hz + 0.1);
          count("#pct", 78.1, hz + 0.1, 1.3, 1, "%");
          show("#th", hz + 0.5); slideIn("#th", hz + 0.5, 400, 300, 0.55);
          chars("#hb1", {L(h,'best')} - 0.1, 0.018);
""")

# ---------------------------------------------------------------- CAVEAT (calm)
h = "caveat"
OUT[h] = page(h, f"""
        #pw {{ position: absolute; inset: 0; transform-origin: 50% 40%; }}
        #cv {{ position: absolute; left: 72px; right: 72px; top: 360px; }}
        #cv .big {{ font-size: 230px; color: #c3c7bf; }}
        .grid {{ display: grid; grid-template-columns: repeat(13, 1fr); gap: 10px; margin-top: 60px; }}
        .c {{ height: 64px; border: 3px solid {LINE}; position: relative; }}
        .c b {{ position: absolute; inset: 0; background: #c3c7bf; transform-origin: 50% 100%; }}
        #l2 .d {{ font-size: 88px; color: #9ca197; }}
""", f"""
          <div id="pw"><div id="cv">
            <div class="lab">Sample size</div>
            <div class="ln" id="l1">{split("10 games", "d big")}</div>
            <div class="grid">{"".join(f'<div class="c">{"<b></b>" if i < 10 else ""}</div>' for i in range(26))}</div>
            <div class="lab" style="margin-top:26px">10 of 26 league games</div>
            <div class="ln" id="l2" style="margin-top:60px">{split("A full season will tell", "d")}</div>
          </div></div>
""", f"""
          tl.fromTo("#pw", {{ scale: 1.08 }}, {{ scale: 1, duration: {D(h)}, ease: "power1.out" }}, 0);
          chars("#l1", 0.04, 0.03);
          tl.fromTo(".c b", {{ scaleY: 0 }}, {{ scaleY: 1, duration: 0.2, ease: "power2.out", stagger: 0.05 }}, 0.3);
          chars("#l2", {L(h,'fullseason')} - 0.05, 0.015);
""")

# ---------------------------------------------------------------- PAYOFF
h = "payoff"
OUT[h] = page(h, f"""
        #list {{ position: absolute; left: 72px; right: 72px; top: 250px; }}
        .it {{ padding: 12px 0 8px; opacity: 0; justify-content: flex-start; gap: 22px; }}
        .it .i {{ font-weight: 700; font-size: 28px; color: {MUTED}; letter-spacing: 0.1em; width: 50px; padding-bottom: 14px; }}
        .it .d {{ font-size: 110px; }}
        .it.on {{ background: {VOLT}; color: {BG}; padding-left: 16px; }}
        .it.on .i {{ color: {BG}; }}
        #stage {{ position: absolute; left: 72px; right: 72px; top: 720px; bottom: 580px; }}
        #tr {{ left: 0; right: 0; top: 0; bottom: 0; opacity: 0; }}
        #ind {{ position: absolute; left: 50%; top: 10px; width: 420px; margin-left: -210px; opacity: 0; }}
        #tf {{ position: absolute; inset: 0; opacity: 0; }}
        #tf img {{ position: absolute; top: 90px; width: 250px; }}
        #ga {{ left: 0; opacity: 0.55; }}
        #od {{ right: 0; }}
        #ar {{ position: absolute; left: 290px; right: 290px; top: 230px; height: 14px; background: {VOLT}; transform-origin: 0 50%; }}
        #ar:after {{ content: ""; position: absolute; right: -30px; top: -22px; border-left: 36px solid {VOLT}; border-top: 29px solid transparent; border-bottom: 29px solid transparent; }}
        #wk {{ position: absolute; left: 50%; top: 420px; margin-left: -190px; width: 380px; text-align: center; font-size: 52px; padding: 14px 0; opacity: 0; }}
""", f"""
          <div id="list">
            <div class="lab" style="margin-bottom:16px">What one season got him</div>
            <div class="row it" id="i1"><span class="i">01</span>{split("Golden Glove", "d")}</div>
            <div class="row it" id="i2"><span class="i">02</span>{split("India call-up", "d")}</div>
            <div class="row it" id="i3"><span class="i">03</span>{split("New deal · Odisha FC", "d")}</div>
          </div>
          <div id="stage">
            {photo("tr", "golden-glove-trophy", "", shadow="volt")}
            <img id="ind" src="assets/logos/india-aiff.png" />
            <div id="tf"><img id="ga" src="assets/logos/fc-goa.png" /><div id="ar"></div><img id="od" src="assets/logos/odisha-fc.png" /></div>
            <div class="tag" id="wk">This week</div>
          </div>
""", f"""
          var g = {L(h,'gg')} - 0.05, c = {L(h,'callup')} - 0.05, o = {L(h,'thisweek')} - 0.1;
          show("#i1", g); tl.set("#i1", {{ backgroundColor: "{VOLT}", color: "{BG}", paddingLeft: 16 }}, g); tl.set("#i1 .i", {{ color: "{BG}" }}, g); chars("#i1", g, 0.02); shake(g + 0.05, 12);
          show("#tr", g); tl.fromTo("#tr", {{ scale: 0.3, rotate: -30, y: 200 }}, {{ scale: 1, rotate: 0, y: 0, duration: 0.6, ease: "expo.out" }}, g);
          tl.to("#tr", {{ rotate: 4, duration: 0.8, ease: "sine.inOut" }}, g + 0.6);
          tl.to("#tr", {{ x: -900, filter: "blur(14px)", duration: 0.28, ease: "expo.in" }}, c - 0.2);
          tl.set("#i1", {{ backgroundColor: "transparent", color: "{FG}", paddingLeft: 0 }}, c); tl.set("#i1 .i", {{ color: "{MUTED}" }}, c);
          show("#i2", c); tl.set("#i2", {{ backgroundColor: "{VOLT}", color: "{BG}", paddingLeft: 16 }}, c); tl.set("#i2 .i", {{ color: "{BG}" }}, c); chars("#i2", c, 0.02); shake(c + 0.05, 12);
          show("#ind", c); tl.fromTo("#ind", {{ rotateY: 90, scale: 0.7, transformPerspective: 900 }}, {{ rotateY: 0, scale: 1, duration: 0.5, ease: "expo.out" }}, c);
          tl.to("#ind", {{ x: 900, filter: "blur(14px)", duration: 0.28, ease: "expo.in" }}, o - 0.2);
          tl.set("#i2", {{ backgroundColor: "transparent", color: "{FG}", paddingLeft: 0 }}, o); tl.set("#i2 .i", {{ color: "{MUTED}" }}, o);
          show("#i3", o); tl.set("#i3", {{ backgroundColor: "{VOLT}", color: "{BG}", paddingLeft: 16 }}, o); tl.set("#i3 .i", {{ color: "{BG}" }}, o); chars("#i3", o, 0.015);
          tl.set("#tf", {{ opacity: 1 }}, o);
          slideIn("#ga", o, -400, 0, 0.4); draw("#ar", o + 0.3, 0.5);
          tl.fromTo("#od", {{ scale: 0.2, rotate: 20 }}, {{ scale: 1, rotate: 0, duration: 0.5, ease: "expo.out" }}, {L(h,'odisha')} - 0.25);
          shake({L(h,'odisha')}, 16);
          show("#wk", o + 0.2); tl.fromTo("#wk", {{ scale: 2.2, rotate: -12 }}, {{ scale: 1, rotate: -4, duration: 0.22, ease: "power4.out" }}, o + 0.2);
""")

# ---------------------------------------------------------------- THE LINE
h = "theline"
OUT[h] = page(h, f"""
        #b1 {{ position: absolute; left: 72px; right: 72px; top: 250px; height: 470px; border: 3px solid #4a4f48; overflow: hidden; background: #141715; }}
        #b1 .d {{ position: absolute; left: 40px; bottom: 112px; font-size: 260px; color: #9ca197; }}
        #b1 .lab {{ position: absolute; left: 44px; bottom: 26px; color: #6f756c; }}
        #gt {{ right: -40px; width: 480px; top: 30px; bottom: 0; opacity: 0.7; }}
        #b2 {{ left: 72px; right: 72px; top: 780px; height: 560px; clip-path: inset(0 100% 0 0); }}
        #b2 .d {{ position: absolute; left: 40px; bottom: 112px; font-size: 330px; }}
        #b2 .lab {{ position: absolute; left: 44px; bottom: 26px; }}
        #rr {{ left: 360px; right: -60px; top: 560px; bottom: 580px; opacity: 0; }}
""", f"""
          <div id="b1">{photo("gt", "hrithik-goa-training", "", shadow=None)}<span class="d">3 yrs</span><span class="lab">On the bench</span></div>
          <div class="blk" id="b2"><span class="d">1</span><span class="lab">Season to change it</span></div>
          {photo("rr", "hrithik-roar", "", shadow="dark", glitch=True)}
""", f"""
          tl.fromTo("#b1", {{ x: -900 }}, {{ x: 0, duration: 0.45, ease: "expo.out" }}, 0);
          tl.fromTo("#gt", {{ x: 60 }}, {{ x: 0, duration: {D(h)}, ease: "none" }}, 0);
          var o = {L(h,'one')} - 0.12;
          tl.to("#b2", {{ clipPath: "inset(0 0% 0 0)", duration: 0.35, ease: "expo.inOut" }}, o);
          show("#rr", o + 0.2); slideIn("#rr", o + 0.2, 0, 500, 0.5); glitch("rr", o + 0.45); shake(o + 0.3, 16);
          punch("#b2", {L(h,'change')}, 1.05);
""")

# ---------------------------------------------------------------- CTA
h = "cta"
OUT[h] = page(h, f"""
        #cb {{ left: 72px; right: 72px; top: 250px; bottom: 580px; }}
        #ct {{ position: absolute; left: 52px; top: 40px; }}
        #ct .d {{ font-size: 220px; }}
        #sub {{ position: absolute; left: 52px; width: 470px; bottom: 50px; font-weight: 700; font-size: 44px; line-height: 1.15; text-transform: uppercase; }}
        #sub span {{ display: block; opacity: 0; }}
        #cp {{ right: -30px; width: 440px; top: 760px; bottom: 580px; opacity: 0; }}
""", f"""
          <div class="blk" id="cb">
            <div id="ct"><div class="lab">Rising ISL Talents</div><div class="ln" id="c1">{split("Follow", "d")}</div><div class="ln" id="c2">{split("for more", "d")}</div></div>
            <div id="sub"><span id="u1">We find the best</span><span id="u2">rising talents,</span><span id="u3">so you don't have to.</span></div>
          </div>
          {photo("cp", "hrithik-goa-studio", "", shadow="dark")}
""", f"""
          wipe("#cb", 0, 0.2); chars("#c1", 0.05, 0.03); chars("#c2", 0.25, 0.025); shake(0.3, 12);
          show("#cp", 0.35); slideIn("#cp", 0.35, 500, 0, 0.6);
          show("#u1", {L(h,'wefind')}); show("#u2", {L(h,'rising')}); show("#u3", {L(h,'soyou')});
""")

def write_all():
    for cid, html in OUT.items():
        (COMP / f"{cid}.html").write_text(html)
    print("wrote", ", ".join(OUT))


if __name__ == "__main__":
    write_all()
