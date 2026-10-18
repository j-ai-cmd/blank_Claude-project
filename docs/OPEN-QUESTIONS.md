# Open questions — answer before build

_Updated 2026-10-19: rows 9, 10, 11 and 23 now show what was built (several early answers were replaced later). Org v3 questions: end of `docs/ORG-V3-PROPOSAL.md`._

Defaults are already written into the config; change them if wrong.

| # | Question | Default chosen |
|---|---|---|
| 1 | Departments? | ✅ v2: Studio, Sales, Talent, Engineering, Ops (+ core: Atlas, Vera, Proof, Lex) |
| 2 | Specialist list per dept OK? (see `config/org.yaml`) | As written |
| 3 | Names/personalities OK? | Atlas, Vera, Lex, Maya, Sam, Rhea, Otto + specialists |
| 4 | Human managers per dept, or you approve everything? | You approve everything |
| 5 | Slack: one app with personas, or one app per Lead (real @mentions)? | One app + personas |
| 6 | Small (S) tasks: auto-start or wait for contract 👍? | Auto-start, contract shown |
| 7 | Leads proactive? | Suggest only, never act unasked |
| 8 | Tools/accounts per dept (CRM, ATS, design, video, social, PM)? | Unknown — **need list** (e.g. HubSpot, Apollo, Ashby, Canva, Figma, Descript/Runway, Buffer, Linear/Notion, Google Drive, Gmail) |
| 9 | Image/video/voice providers? | ✅ HyperFrames renders on the runtime service (HeyGen dropped). ✅ Voices: **Chatterbox** (your clone, Jai only) + **Kokoro** base voices (OpenVoice dropped). ✅ **No image generation for now** |
| 10 | Stack | ✅ Python/FastAPI + Postgres + **Claude Agent SDK** on your plan (Managed Agents not used: the Dispatcher orchestrates, `docs/DESIGN-MAP.md` §4) |
| 11 | Hosting? | ✅ Vercel Hobby (Live Office frontend) + **one Oracle Cloud Always Free machine** (backend, Postgres, runtime service for voices and renders). AWS and the Modal-first plan dropped; Modal stays optional (`deploy/modal_app.py`) |
| 12 | LLM billing | ✅ **Owner's Claude Pro plan → $20/mo Agent SDK credit**, usage credits off (never charges). Per-task caps S $0.5 / M $2 / L $6 |
| 13 | Company L0 facts: brand kit, product docs, price list, ICP — where are they? | Brand kit: **later** (Marketing visual work runs without brand checks until added). Others: **need files** |
| 14 | Who may give tasks? | ✅ **Decided: only you** |
| 15 | Backup approver (required before go-live) | **Need a person** |
| 16 | Which R3 actions may a delegate approve while you're away? | None |
| 17 | Extra trusted-domain list for web fetch | Optional — not needed for research |
| 18 | Hiring regions | ✅ n/a — you don't hire people (Talent designs AI employees) |
| 19 | Selling into EU/Canada? (GDPR / CASL for outreach + enrichment) | **Need answer** |
| 20 | Daily spend caps per employee OK? | As in permissions.yaml |
| 21 | First build scope | ✅ **Core + all 4 departments** |
| 22 | Slack workspace + app | ✅ **Both exist** — owner adds bot token + signing secret as env vars |
| 23 | Voices | ✅ jai = your Chatterbox clone; sherlock = Kokoro `bm_lewis`; peter = original Kokoro base voice (never a clone); striker = you record it; non-show videos = Kokoro base |
| 24 | Use | ✅ Personal / non-commercial |
| 25 | Show bibles (CHARACTER.md + DESIGN.md for jai, sherlock, brainrot, striker) | **Need yours** — all four are placeholders; show work stops and asks until filled |
| 26 | Rate card, CV, provable results | **Need yours** — see docs/TRAINING-CHECKLIST.md "Do these first" |
| 27 | Upload store for CV/statements (owner_profile.read, finance.read_uploads) | Not built — paste into the request meanwhile |
