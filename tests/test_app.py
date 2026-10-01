import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from workforce import app as app_mod


def _sign(body: bytes, secret="s3cret"):
    ts = str(int(time.time()))
    sig = "v0=" + hmac.new(secret.encode(), f"v0:{ts}:".encode() + body, hashlib.sha256).hexdigest()
    return {"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig}


@pytest.fixture
def client(monkeypatch, make_dispatcher):
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "s3cret")
    monkeypatch.setenv("WORKFORCE_API_TOKEN", "tok")
    d, _, _ = make_dispatcher({})
    app_mod.app.state.dispatcher = d
    yield TestClient(app_mod.app)
    del app_mod.app.state.dispatcher


def test_rejects_unsigned(client):
    r = client.post("/slack/events", content=b'{"type":"url_verification","challenge":"x"}')
    assert r.status_code == 401


def test_url_verification(client):
    body = json.dumps({"type": "url_verification", "challenge": "abc"}).encode()
    r = client.post("/slack/events", content=body, headers=_sign(body))
    assert r.status_code == 200 and r.text == "abc"


def test_bot_event_acked_but_ignored(client):
    body = json.dumps({"type": "event_callback", "event_id": "E1", "event": {
        "type": "message", "bot_id": "B1", "text": "hi", "channel": "C1", "ts": "1"}}).encode()
    r = client.post("/slack/events", content=body, headers=_sign(body))
    assert r.status_code == 200


def test_slash_command_owner_only(client):
    body = urlencode({"user_id": "U_GUEST", "text": "pause-all"}).encode()
    r = client.post("/slack/commands", content=body, headers={**_sign(body), "Content-Type": "application/x-www-form-urlencoded"})
    assert "Only the owner" in r.json()["text"]
    body = urlencode({"user_id": "U_OWNER", "text": "status"}).encode()
    r = client.post("/slack/commands", content=body, headers={**_sign(body), "Content-Type": "application/x-www-form-urlencoded"})
    assert "Plan credit used" in r.json()["text"]


def test_api_requires_token(client):
    assert client.get("/api/tasks").status_code == 401
    assert client.get("/api/tasks", headers={"Authorization": "Bearer tok"}).json() == []


def test_uploads_api(client):
    assert client.post("/api/uploads/profile?name=cv.md", content=b"CV").status_code == 401
    h = {"Authorization": "Bearer tok"}
    r = client.post("/api/uploads/profile?name=cv.md", content=b"My CV", headers=h)
    assert r.status_code == 201 and r.json()["name"] == "cv.md"
    assert client.post("/api/uploads/show-nobody?name=x", content=b"x", headers=h).status_code == 404
    assert client.post("/api/uploads/lane-company?name=spec.md", content=b"x", headers=h).status_code == 201
    listing = client.get("/api/uploads", headers=h).json()
    assert listing["profile"] == ["cv.md"] and listing["lane-company"] == ["spec.md"]
