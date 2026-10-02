"""Files you add as you go: your CV, statements, and each show's assets.

Each file lives in one scope. Who can see a scope is decided here, in code:
  profile        your CV / portfolio / work history   -> employees holding owner_profile.read (Letter)
  finance        statements, invoices                 -> employees holding finance.read_uploads (Ledger)
  show-<name>    one show's scripts, photos, clips, voiceover -> that show's own employees only (I5)
  lane-<name>    one lane's material (e.g. lane-company) -> that lane's own employees only
  general        anything else                        -> every specialist
Add files with the API (POST /api/uploads/<scope>), the Live Office, or by dropping them in uploads/<scope>/.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .config import ROOT, Config, Employee

SAFE = re.compile(r"[^A-Za-z0-9._-]+")
MAX_BYTES = 500 * 1024 * 1024


def root() -> Path:
    return Path(os.environ.get("UPLOADS_DIR", ROOT / "uploads"))


def valid_scope(cfg: Config, scope: str) -> bool:
    return scope in ("profile", "finance", "general") or (scope[:5] in ("show-", "lane-") and scope[5:] in cfg.shows
                                                          and cfg.shows[scope[5:]]["kind"] == scope[:4])


def can_read(cfg: Config, emp: Employee, scope: str) -> bool:
    if scope == "profile":
        return "owner_profile.read" in emp.tools
    if scope == "finance":
        return "finance.read_uploads" in emp.tools
    if scope[:5] in ("show-", "lane-"):
        return emp.show == scope[5:]
    return scope == "general" and emp.kind == "specialist"


def scopes_for(cfg: Config, emp: Employee) -> list[str]:
    all_ = ["profile", "finance", "general"] + [f"{v['kind']}-{k}" for k, v in cfg.shows.items()]
    return [s for s in all_ if can_read(cfg, emp, s)]


def safe_name(name: str) -> str:
    return SAFE.sub("_", name.split("/")[-1])[:120] or "file"


def save(cfg: Config, scope: str, name: str, data: bytes) -> Path:
    if not valid_scope(cfg, scope):
        raise ValueError(f"unknown scope {scope}")
    if len(data) > MAX_BYTES:
        raise ValueError("file too large (500 MB)")
    d = root() / scope
    d.mkdir(parents=True, exist_ok=True)
    p = d / safe_name(name)
    p.write_bytes(data)
    return p


def listing(scope: str) -> list[str]:
    d = root() / scope
    return sorted(p.name for p in d.iterdir() if p.is_file()) if d.is_dir() else []


def path(scope: str, name: str) -> Path | None:
    p = root() / scope / safe_name(name)
    return p if p.is_file() else None
