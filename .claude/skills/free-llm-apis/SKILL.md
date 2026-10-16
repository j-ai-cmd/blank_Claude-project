---
name: free-llm-apis
description: Use when the user asks which free LLM API or model to use, how to get a free API key, free tiers or rate limits for Gemini, Groq, Mistral, OpenRouter, NVIDIA NIM, Cloudflare, Cohere, Hugging Face, Ollama Cloud and similar, or says "free llm", "free api", "free model". Picks a provider by need and walks through setup from a bundled snapshot of github.com/mnfst/awesome-free-llm-apis (CC0).
---

# free-llm-apis

Reference skill. Snapshot of mnfst/awesome-free-llm-apis (CC0). Commit and date in `references/SOURCE_COMMIT.txt`. Runs no code.

## Files

| File | Use |
|---|---|
| `references/README.md` | Full list: providers, base URLs, model tables, rate limits, footnote caveats |
| `references/data.json` | Same data, structured. Query this for filters (no-signup, commercial OK, model name) |
| `references/setup-guides/provider-apis.md` | Step-by-step key setup + code, provider APIs |
| `references/setup-guides/inference-providers.md` | Step-by-step key setup + code, inference providers |
| `references/license` | CC0 |

Setup guides are older than the README and can name providers the README dropped. The README and `data.json` win on limits and availability.

## Workflow

1. Ask what matters: speed, rate limit, biggest model, long context, no signup, commercial use, EU, coding, vision.
2. Filter `data.json` or the README tables. Suggest 1 to 2 providers with a one-line reason each.
3. Give base URL, key page link, model name, and rate limit from the README.
4. Walk through key setup using the matching setup guide. Offer a curl or OpenAI-SDK test call with placeholders.
5. State caveats that apply: non-commercial, training on prompts, phone or ID verification, region blocks, retiring models.

## Rules

- Free tiers change often. Say the snapshot date. For "is X still free" or exact current limits, check the live repo or provider page.
- Never ask for, type, or store the user's API key. Use `$ENV_VAR` placeholders and tell them where to put the key.
- Most endpoints are OpenAI-compatible: `api_key` + `base_url` in the OpenAI SDK, unless the README says otherwise.
- Do not recommend trial-credit or time-limited promos as "free tier". The list excludes them.
- Do not make production-reliability promises. Free tiers have low limits and can vanish.
