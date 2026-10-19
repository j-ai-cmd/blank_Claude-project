"""Constants and small helpers shared by the Dispatcher and its mixins."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
BUILTINS = {"WebSearch": "web.search", "WebFetch": "web.fetch"}
CRITERION_CHECKS = {"automatic", "verifier", "owner_taste"}
TOOL_ACTIONS = {
    "workspace_write": "workspace.write", "workspace_read": "workspace.read", "memory_read": "memory.read_scoped",
    "slack_post": "slack.post_own_thread", "submit_contract": "submit_contract", "submit_plan": "submit_plan",
    "submit_return": "submit_return", "submit_verdict": "submit_verdict", "submit_delivery": "submit_delivery",
    "submit_factcheck": "submit_factcheck", "skill_read": "skill.read", "peer_ask": "peer.ask",
    "submit_answer": "submit_return",
}
SIZE_LIMIT = {"S": 1, "M": 3, "L": 20}
CLAIM = re.compile(r"(\$\s?\d|€\s?\d|£\s?\d|₹\s?\d|\b\d+(?:\.\d+)?\s?%|\b(?:19|20)\d{2}\b|\b\d{2,}(?:[.,]\d+)?\b)")
VERIFY = re.compile(r"\b(verify|verified|verifier|vera|double[- ]check)\b", re.I)
STANDING = re.compile(r"\b(always|from now on|going forward|never|every time|in future|by default)\b", re.I)
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
URL = re.compile(r"https?://\S+")
PROSE_SUFFIXES = {"", ".md", ".txt", ".html", ".csv", ".srt", ".vtt"}   # json/yaml project files aren't claims
PIPELINE_STATUSES = {"sent", "ready_to_send", "replied_positive", "replied_negative", "no_reply", "follow_up_sent",
                     "interview", "offer", "closed"}
PIPELINE_KIND = {("*", "email.send_external"): "pitch", ("*", "apply.submit"): "application", ("*", "invoice.send"): "invoice"}
FOLLOW_UP_DAYS = {"pitch": 5, "application": 7, "follow_up": 7, "invoice": 14}
INFRA = re.compile(r"authenticat|unauthori[sz]ed|401|403|rate.?limit|overloaded|network|timed? ?out|connection|"
                   r"CLINotFound|ProcessError|budget exhausted|paused", re.I)
RESUME_WORDS = {"resume", "retry", "continue", "go on"}
LOW_CONFIDENCE = 0.6
IN_FLIGHT = ("PLANNED", "IN_PROGRESS", "VERIFYING", "REVISION")
SKILL_TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".py", ".sh", ".js", ".ts", ".html", ".css"}
TEXT_SUFFIXES = {"", ".md", ".txt", ".json", ".html", ".csv", ".srt", ".vtt", ".yaml", ".yml"}


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt
_ID_LISTS = ("criteria", "inputs_from")
CHITCHAT = re.compile(r"^\W*(thanks|thank you|thx|ok|okay|cool|nice|great|lol|haha|yes|no|👍|🙏)\W*$", re.I)


def normalize_ids(obj):
    """L2: models send ids as numbers (1) or strings ("1"); everything downstream compares strings."""
    if isinstance(obj, list):
        return [normalize_ids(x) for x in obj]
    if not isinstance(obj, dict):
        return obj
    out = {}
    for k, v in obj.items():
        if k in ("id", "criterion_id", "deliverable") and isinstance(v, (int, float)):
            v = str(int(v)) if float(v).is_integer() else str(v)
        elif k in _ID_LISTS and isinstance(v, list):
            v = [str(int(x)) if isinstance(x, (int, float)) and float(x).is_integer() else x for x in v]
        else:
            v = normalize_ids(v)
        out[k] = v
    return out
