"""Connectors: the only code that touches the outside world. Employees never hold credentials — they ask,
the Policy checks, you approve (R2/R3), then THIS code runs the action with keys from the environment.

Built in:
  email.read            IMAP, read-only (IMAP_HOST, IMAP_USER, IMAP_PASSWORD — e.g. a Gmail app password)
  email.send_external   SMTP if SMTP_HOST/SMTP_USER/SMTP_PASSWORD are set, else the OUTBOX (a .eml you send yourself)
  social.publish        OUTBOX (the post package: account, video, caption) unless you register an Instagram connector
  invoice.send          SMTP like email, else OUTBOX
Add your own: `register("code.push", my_fn)` in a module listed in WORKFORCE_CONNECTORS (comma-separated import
paths). fn(params: dict) -> (delivered_via: str, detail: str). It runs only after policy + your approval.
"""
from __future__ import annotations

import email
import email.policy
import imaplib
import importlib
import json
import os
import re
import smtplib
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

from .config import ROOT

_REGISTRY: dict = {}


def register(action: str, fn) -> None:
    _REGISTRY[action] = fn


def _load_user_connectors() -> None:
    for mod in filter(None, (os.environ.get("WORKFORCE_CONNECTORS") or "").split(",")):
        importlib.import_module(mod.strip())


def outbox_dir() -> Path:
    d = Path(os.environ.get("OUTBOX_DIR", ROOT / "outbox"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _message(params: dict) -> EmailMessage:
    m = EmailMessage()
    m["To"] = str(params.get("to", ""))
    m["Subject"] = str(params.get("subject", ""))
    m["From"] = os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER") or "me"
    m.set_content(str(params.get("body") or params.get("text") or ""))
    for att in params.get("attachments") or []:   # artifact paths resolved by the Dispatcher
        p = Path(att)
        if p.is_file():
            m.add_attachment(p.read_bytes(), maintype="application", subtype="octet-stream", filename=p.name)
    return m


def _to_outbox(action: str, params: dict) -> tuple[str, str]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}-{action.replace('.', '-')}-{uuid.uuid4().hex[:6]}"
    if action in ("email.send_external", "invoice.send"):
        p = outbox_dir() / f"{name}.eml"
        p.write_bytes(bytes(_message(params)))
    else:
        p = outbox_dir() / f"{name}.json"
        p.write_text(json.dumps({k: v for k, v in params.items() if k != "approval_id"}, indent=2))
    return "outbox", f"saved to outbox/{p.name} — send it yourself (no sending connector configured)"


def _smtp(params: dict) -> tuple[str, str]:
    host, user, pw = os.environ["SMTP_HOST"], os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASSWORD", "")
    with smtplib.SMTP_SSL(host, int(os.environ.get("SMTP_PORT", "465")), timeout=60) as s:
        if user:
            s.login(user, pw)
        s.send_message(_message(params))
    return "smtp", f"sent to {params.get('to')}"


def execute(action: str, params: dict) -> tuple[str, str]:
    """Run an APPROVED action. Returns (delivered_via, human message). Raises on connector failure."""
    _load_user_connectors()
    if action in _REGISTRY:
        return _REGISTRY[action](params)
    if action in ("email.send_external", "invoice.send") and os.environ.get("SMTP_HOST"):
        return _smtp(params)
    if action in ("email.send_external", "invoice.send", "social.publish"):
        return _to_outbox(action, params)
    return "none", f"no connector configured for {action} — nothing was sent"


# ---------------------------------------------------------------------------------------------- email read
class EmailReader:
    """Read-only IMAP. list_recent never returns bodies; open() returns one message's text."""

    def configured(self) -> bool:
        return bool(os.environ.get("IMAP_HOST") and os.environ.get("IMAP_USER") and os.environ.get("IMAP_PASSWORD"))

    def _conn(self) -> imaplib.IMAP4_SSL:
        c = imaplib.IMAP4_SSL(os.environ["IMAP_HOST"], int(os.environ.get("IMAP_PORT", "993")))
        c.login(os.environ["IMAP_USER"], os.environ["IMAP_PASSWORD"])
        c.select(os.environ.get("IMAP_FOLDER", "INBOX"), readonly=True)   # readonly: never marks as read
        return c

    def list_recent(self, hours: int) -> list[dict]:
        since = (datetime.now(timezone.utc) - timedelta(hours=hours))
        c = self._conn()
        try:
            _, data = c.uid("search", None, f'(SINCE "{since.strftime("%d-%b-%Y")}")')
            out = []
            for uid in (data[0] or b"").split():
                _, msg = c.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                hdr = email.message_from_bytes(msg[0][1], policy=email.policy.default)
                try:
                    when = email.utils.parsedate_to_datetime(hdr["Date"])
                except (TypeError, ValueError):
                    when = None
                if when is not None and when.tzinfo and when < since:
                    continue
                out.append({"id": uid.decode(), "from": str(hdr["From"] or ""), "subject": str(hdr["Subject"] or ""),
                            "date": str(hdr["Date"] or "")})
            return out
        finally:
            c.logout()

    def open(self, msg_id: str) -> dict:
        if not re.fullmatch(r"\d+", msg_id):
            raise ValueError("bad id")
        c = self._conn()
        try:
            _, msg = c.uid("fetch", msg_id, "(BODY.PEEK[])")
            m = email.message_from_bytes(msg[0][1], policy=email.policy.default)
            part = m.get_body(preferencelist=("plain", "html"))
            body = part.get_content() if part else ""
            body = re.sub(r"<[^>]+>", " ", body) if part and part.get_content_type() == "text/html" else body
            return {"id": msg_id, "from": str(m["From"] or ""), "subject": str(m["Subject"] or ""),
                    "date": str(m["Date"] or ""), "body": body[:20_000]}
        finally:
            c.logout()
