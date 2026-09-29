# Open questions — answer before build

Defaults are already written into the config; change them if wrong.

| # | Question | Default chosen |
|---|---|---|
| 1 | Departments for v1? | Marketing, Sales, Recruiting, Ops. Finance/Support/Legal = v2 |
| 2 | Specialist list per dept OK? (see `config/org.yaml`) | As written |
| 3 | Names/personalities OK? | Atlas, Vera, Lex, Maya, Sam, Rhea, Otto + specialists |
| 4 | Human managers per dept, or you approve everything? | You approve everything |
| 5 | Slack: one app with personas, or one app per Lead (real @mentions)? | One app + personas |
| 6 | Small (S) tasks: auto-start or wait for contract 👍? | Auto-start, contract shown |
| 7 | Leads proactive? | Suggest only, never act unasked |
| 8 | Tools/accounts per dept (CRM, ATS, design, video, social, PM)? | Unknown — **need list** (e.g. HubSpot, Apollo, Ashby, Canva, Figma, Descript/Runway, Buffer, Linear/Notion, Google Drive, Gmail) |
| 9 | Image/video/voice providers? | ✅ **HeyGen** (HyperFrames cloud render + TTS). OpenVoice V2 uploaded (self-hosted voice clone) — role being confirmed. Image generator: none chosen yet |
| 10 | Stack: Python/FastAPI + Postgres/pgvector + Claude Managed Agents? | Yes |
| 11 | Hosting? | Frontend + deploy on Vercel wanted — backend split being confirmed |
| 12 | Budget caps per task (S $2 / M $10 / L $50) OK? | Yes |
| 13 | Company L0 facts: brand kit, product docs, price list, ICP — where are they? | Brand kit: **later** (Marketing visual work runs without brand checks until added). Others: **need files** |
| 14 | Who may give tasks? | ✅ **Decided: only you** |
| 15 | Backup approver (required before go-live) | **Need a person** |
| 16 | Which R3 actions may a delegate approve while you're away? | None |
| 17 | Extra trusted-domain list for web fetch | Optional — not needed for research |
| 18 | Hiring regions (NYC / EU / Illinois trigger AI-hiring rules) + legal reviewer | **Need answer** |
| 19 | Selling into EU/Canada? (GDPR / CASL for outreach + enrichment) | **Need answer** |
| 20 | Daily spend caps per employee OK? | As in permissions.yaml |
| 21 | First build scope | ✅ **Core + all 4 departments** |
| 22 | Slack workspace + app | ✅ **Both exist** — owner adds bot token + signing secret as env vars |
