"""Free-tier LLM calls (ORG-V3 §3b, tier F) for public-web text only: summaries, rankings, first drafts.

OpenAI-compatible chat completions over httpx. Providers are tried in order (config/org.yaml `free_llm`); a provider
without its key in the environment is skipped, and a rate limit, server error or timeout moves on to the next.
Callers (the Dispatcher's llm_free tool) decide WHAT may be sent; this module only sends it.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import httpx


class FreeLLMUnavailable(Exception):
    pass


@dataclass
class FreeAnswer:
    provider: str
    model: str
    text: str


def complete(providers: list[dict], instruction: str, text: str, timeout: float = 60.0,
             max_tokens: int = 2048) -> FreeAnswer:
    tried = []
    for p in providers:
        key = os.environ.get(p.get("key_env", ""), "")
        if not key:
            tried.append(f"{p['name']}: no {p.get('key_env')}")
            continue
        try:
            r = httpx.post(p["base_url"].rstrip("/") + "/chat/completions",
                           headers={"Authorization": f"Bearer {key}"}, timeout=timeout,
                           json={"model": p["model"], "max_tokens": max_tokens, "temperature": 0.2,
                                 "messages": [{"role": "system", "content": instruction},
                                              {"role": "user", "content": text}]})
        except httpx.HTTPError as e:
            tried.append(f"{p['name']}: {type(e).__name__}")
            continue
        if r.status_code == 429 or r.status_code >= 500:
            tried.append(f"{p['name']}: HTTP {r.status_code}")
            continue
        if r.status_code != 200:
            tried.append(f"{p['name']}: HTTP {r.status_code} {r.text[:120]}")
            continue
        try:
            out = r.json()["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError):
            tried.append(f"{p['name']}: unreadable response")
            continue
        return FreeAnswer(p["name"], p["model"], out)
    raise FreeLLMUnavailable("; ".join(tried) or "no free providers configured")
