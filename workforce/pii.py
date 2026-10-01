"""Deterministic personal-data detection (no LLM). Used by checks and the egress filter."""
from __future__ import annotations

import re

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{8,}\d)(?!\w)")
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

PATTERNS = {"email": EMAIL, "phone": PHONE, "card": CARD, "iban": IBAN, "ssn": SSN}


RESERVED = re.compile(r"@([\w-]+\.)*(example\.(com|org|net)|[\w-]+\.(test|example|invalid|localhost))$", re.I)


def find_pii(text: str) -> list[tuple[str, str]]:
    hits = []
    for kind, rx in PATTERNS.items():
        for m in rx.finditer(text or ""):
            val = m.group(0)
            if kind == "email" and RESERVED.search(val):
                continue   # RFC 2606 placeholder addresses are not anyone's data
            if kind == "phone" and sum(c.isdigit() for c in val) < 9:
                continue
            if kind == "card" and not _luhn(re.sub(r"\D", "", val)):
                continue
            hits.append((kind, val))
    return hits


def _luhn(digits: str) -> bool:
    if not 13 <= len(digits) <= 19:
        return False
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0

