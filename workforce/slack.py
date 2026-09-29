"""Slack gateway: request signing, event filtering (loop guard), and a small Web API client.

Agents never talk through Slack to each other. Only allowlisted humans create/steer tasks.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass

import httpx

SLACK_API = "https://slack.com/api"


def verify_signature(signing_secret: str, timestamp: str, body: bytes, signature: str,
                     now: float | None = None, tolerance_s: int = 300) -> bool:
    """Slack v0 signature: HMAC-SHA256('v0:{ts}:{body}'). Rejects replays older than 5 minutes."""
    if not (signing_secret and timestamp and signature):
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs((now or time.time()) - ts) > tolerance_s:
        return False
    base = b"v0:" + timestamp.encode() + b":" + body
    expected = "v0=" + hmac.new(signing_secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@dataclass
class InboundMessage:
    event_id: str
    user: str
    channel: str
    channel_name: str | None
    text: str
    ts: str
    thread_ts: str | None
    is_dm: bool


IGNORED_SUBTYPES = {"bot_message", "message_changed", "message_deleted", "channel_join", "channel_leave",
                    "message_replied", "thread_broadcast"}


def parse_event(payload: dict) -> InboundMessage | None:
    """Returns a human message worth handling, or None (bots, apps, edits, joins are dropped)."""
    ev = payload.get("event") or {}
    if ev.get("type") not in ("message", "app_mention"):
        return None
    if ev.get("bot_id") or ev.get("app_id") or ev.get("subtype") in IGNORED_SUBTYPES or ev.get("subtype"):
        return None
    if not ev.get("user") or not (ev.get("text") or "").strip():
        return None
    return InboundMessage(
        event_id=payload.get("event_id") or ev.get("client_msg_id") or ev.get("ts"),
        user=ev["user"], channel=ev.get("channel", ""), channel_name=None, text=ev.get("text", ""),
        ts=ev.get("ts", ""), thread_ts=ev.get("thread_ts"),
        is_dm=ev.get("channel_type") == "im",
    )


class SlackClient:
    """Thin Web API client. With no token (tests/dev) it records calls instead of sending."""

    def __init__(self, token: str | None = None):
        self.token = token if token is not None else os.environ.get("SLACK_BOT_TOKEN", "")
        self.sent: list[dict] = []
        self._channel_names: dict[str, str] = {}

    @property
    def live(self) -> bool:
        return bool(self.token)

    def _call(self, method: str, payload: dict) -> dict:
        if not self.live:
            self.sent.append({"method": method, **payload})
            return {"ok": True, "ts": f"dry-{len(self.sent)}", "channel": payload.get("channel")}
        r = httpx.post(f"{SLACK_API}/{method}", headers={"Authorization": f"Bearer {self.token}"},
                       json=payload, timeout=20)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"slack {method} failed: {data.get('error')}")
        return data

    def post(self, channel: str, text: str, thread_ts: str | None = None, persona: dict | None = None,
             blocks: list | None = None) -> dict:
        payload: dict = {"channel": channel, "text": text[:39000], "unfurl_links": False}
        if thread_ts:
            payload["thread_ts"] = thread_ts
        if blocks:
            payload["blocks"] = blocks
        if persona:  # requires chat:write.customize
            payload["username"] = persona.get("name")
            if persona.get("icon_url"):
                payload["icon_url"] = persona["icon_url"]
            elif persona.get("icon_emoji"):
                payload["icon_emoji"] = persona["icon_emoji"]
        return self._call("chat.postMessage", payload)

    def channel_name(self, channel_id: str) -> str | None:
        if channel_id in self._channel_names:
            return self._channel_names[channel_id]
        if not self.live:
            return None
        r = httpx.get(f"{SLACK_API}/conversations.info", params={"channel": channel_id},
                      headers={"Authorization": f"Bearer {self.token}"}, timeout=20).json()
        name = "#" + r["channel"]["name"] if r.get("ok") else None
        if name:
            self._channel_names[channel_id] = name
        return name

    def resolve_channel_id(self, name: str) -> str:
        """'#studio' -> channel id (live), or the name itself in dry mode."""
        if not self.live:
            return name
        for cid, n in self._channel_names.items():
            if n == name:
                return cid
        cursor = None
        while True:
            params = {"limit": 200, "types": "public_channel,private_channel"}
            if cursor:
                params["cursor"] = cursor
            r = httpx.get(f"{SLACK_API}/conversations.list", params=params,
                          headers={"Authorization": f"Bearer {self.token}"}, timeout=20).json()
            for c in r.get("channels", []):
                self._channel_names[c["id"]] = "#" + c["name"]
                if "#" + c["name"] == name:
                    return c["id"]
            cursor = (r.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                raise RuntimeError(f"channel {name} not found or bot not invited")


def button(text: str, action_id: str, value: dict, style: str | None = None) -> dict:
    b = {"type": "button", "text": {"type": "plain_text", "text": text}, "action_id": action_id,
         "value": json.dumps(value)}
    if style:
        b["style"] = style
    return b


def approval_blocks(title: str, body: str, approval_id: str, action_hash: str | None = None,
                    checkboxes: list[tuple[str, str]] | None = None) -> list[dict]:
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": title[:150]}},
        {"type": "section", "text": {"type": "mrkdwn", "text": body[:2900]}},
    ]
    if checkboxes:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*Save to memory?* (⚠ = came from email/web/CRM text)"}})
        blocks.append({"type": "actions", "block_id": "memory", "elements": [
            {"type": "checkboxes", "action_id": "memory_ticks", "options": [
                {"text": {"type": "mrkdwn", "text": label[:75]}, "value": val} for val, label in checkboxes[:10]]}]})
    v = {"approval_id": approval_id, "action_hash": action_hash}
    blocks.append({"type": "actions", "elements": [
        button("✅ Approve", "approve", v, "primary"), button("❌ Reject", "reject", v, "danger")]})
    return blocks
