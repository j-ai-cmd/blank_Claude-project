# Open questions — what's decided and what still needs you

Defaults are already written into the config; change them if wrong.

| # | Question | Default chosen |
|---|---|---|
| 1 | Departments? | ✅ v4: Studio, Sales, Engineering, Ops (+ head office: Atlas, Mason, Vera, Proof, Lex) |
| 2 | Specialist list per dept OK? (see `config/org.yaml`) | As written |
| 3 | Names/personalities OK? | Atlas, Mason, Vera, Proof, Lex, Maya, Sam, Forge, Otto + specialists |
| 4 | Human managers per dept, or you approve everything? | You approve everything |
| 5 | Slack: one app with personas, or one app per Lead (real @mentions)? | One app + personas |
| 6 | Small (S) tasks: auto-start or wait for contract 👍? | Auto-start, contract shown |
| 7 | Leads proactive? | Suggest only, never act unasked |
| 8 | Tools/accounts per dept (CRM, ATS, design, video, social, PM)? | Unknown — **need list** (e.g. HubSpot, Apollo, Ashby, Canva, Figma, Descript/Runway, Buffer, Linear/Notion, Google Drive, Gmail) |
| 9 | Image/video/voice providers? | ✅ v4: **HyperFrames** renders locally on the runtime (no HeyGen). Voice: **Kokoro** for Sherlock only; Jai + football = your recorded voiceover. No voice cloning, no image generation |
| 10 | Stack | ✅ Python/FastAPI + Postgres + **Claude Agent SDK** on your Claude plan (one fresh session per employee per step) |
| 11 | Hosting? | ✅ **Oracle Cloud Always Free** (one 4-core / 24 GB ARM machine: API + Postgres + runtime in Docker, Caddy for HTTPS) + **Vercel Hobby** (Live Office). `deploy/modal_app.py` is an optional alternative runtime. See `docs/DEPLOY-GUIDE.md` |
| 12 | LLM billing | ✅ **Owner's Claude Pro plan → $20/mo Agent SDK credit**, usage credits off (never charges). Per-task caps S $0.5 / M $2 / L $6 |
| 13 | Company L0 facts: brand kit, product docs, price list, ICP — where are they? | Brand kit: **later** (Marketing visual work runs without brand checks until added). Others: **need files** |
| 14 | Who may give tasks? | ✅ **Decided: only you** |
| 15 | Backup approver | ✅ **Decided: not needed** — you approve from Slack or the Live Office (`permissions.yaml` `backup: []`). Add one only if someone should approve while you're away |
| 16 | Which R3 actions may a delegate approve while you're away? | None |
| 17 | Extra trusted-domain list for web fetch | Optional — not needed for research |
| 18 | Hiring regions | ✅ n/a — you don't hire people (Atlas + Mason design AI employees) |
| 19 | Selling into EU/Canada? (GDPR / CASL for outreach + enrichment) | **Need answer** |
| 20 | Daily spend caps per employee OK? | As in permissions.yaml |
| 21 | First build scope | ✅ **Core + all 4 departments** |
| 22 | Slack workspace + app | ✅ **Both exist** — owner adds bot token + signing secret as env vars |
| 23 | Voices | ✅ v4: sherlock = Kokoro bm_lewis (base); jai + football = you record the voiceover; no voice is cloned |
| 24 | Use | ✅ Personal / non-commercial |
| 25 | Show bibles (CHARACTER.md + DESIGN.md for sherlock, jai, football) | **Need yours** — placeholders stop show work and ask until filled |
| 26 | Rate card, CV, provable results | **Need yours** — see `docs/TRAINING-CHECKLIST.md` |
| 27 | Upload store for CV/statements | ✅ Built: `uploads/<scope>/` via the API, the Live Office, or the folder (scopes in `docs/TRAINING-CHECKLIST.md`) |
