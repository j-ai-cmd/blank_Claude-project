#!/usr/bin/env python3
"""Download every show's locked fonts (Google Fonts, OFL) into core/fonts/ once, so renders never depend on
a network font fetch. Run at image build / setup:  python3 core/fetch_fonts.py"""
import os
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reel import SHOWS  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
OUT = Path(__file__).resolve().parent / "fonts"
VERIFY = os.environ.get("SSL_CERT_FILE") or True


def fetch(family: str) -> int:
    css = httpx.get(f"https://fonts.googleapis.com/css2?family={family.replace(' ', '+')}:wght@400;700&display=swap",
                    headers=UA, verify=VERIFY, timeout=30).text
    n = 0
    for block in re.findall(r"@font-face\s*{[^}]+}", css):
        if "U+0000-00FF" not in block:          # latin subset is enough for English-only shows
            continue
        weight = re.search(r"font-weight:\s*(\d+)", block).group(1)
        url = re.search(r"url\((https://[^)]+\.woff2)\)", block).group(1)
        dest = OUT / f"{family.replace(' ', '')}-{weight}.woff2"
        if not dest.exists():
            dest.write_bytes(httpx.get(url, verify=VERIFY, timeout=60).content)
        n += 1
    return n


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    fams = sorted({s[k] for s in SHOWS.values() for k in ("head", "body")})
    for f in fams:
        print(f, fetch(f), "file(s)")
