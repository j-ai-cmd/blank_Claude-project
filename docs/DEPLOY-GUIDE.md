# Deploy guide: everything on one Oracle Cloud Always Free machine, Live Office on Vercel

> **How to use this with ChatGPT:** paste this whole file and say:
> "Walk me through this guide one step at a time. Wait for me to confirm each step, and help me fix any errors I paste back."
> Never paste a secret (token, password, key) into ChatGPT. When a step needs one, type it straight into the server or the website.

---

## 0. What you are deploying

| Part | What it is | Where it runs | Cost |
|---|---|---|---|
| **Backend** (`workforce/`) | The Dispatcher: a FastAPI app that receives Slack messages and Live Office requests, runs the AI employees (Claude Agent SDK on your Claude plan) and enforces every rule | One Oracle Cloud Ampere A1 machine (4 ARM cores, 24 GB RAM), in Docker, with Postgres beside it and Caddy for HTTPS | Oracle Always Free (no time limit) |
| **Runtime** (`deploy/runtime_server.py`) | Where videos are built and rendered, voices are spoken (Kokoro and Chatterbox) and code tests run. It holds none of your credentials | A locked-down container on the same machine (no published port, no secrets, no Linux capabilities) | Included |
| **Live Office** (`frontend/`) | The 3D office UI. It talks to the backend over HTTPS (REST + live events) | Vercel (Hobby) | Free |
| **Slack** | Where you give tasks and approve things | Your existing workspace and app | Free |

```
You ── Slack ─────────────┐
You ── Live Office (Vercel) ── HTTPS ──> Caddy ──> api (FastAPI) ──> Postgres
                                                     │
                                                     ├──> Claude (your plan, via CLAUDE_CODE_OAUTH_TOKEN)
                                                     └──> runtime container (render, voice, tests)
```

Endpoints the backend exposes (for reference):
- **Health:** `GET /health`
- **Slack:** `POST /slack/events`, `POST /slack/interactions`, `POST /slack/commands`
- **Office:** `GET /api/office`, `GET /api/office/state`, `GET /api/live` (Server-Sent Events, `?token=`)
- **Actions:** `POST /api/desks/{id}/prompt`, `POST /api/tasks/{id}/reply`, `POST /api/approvals/{id}`, `POST /api/commands`
- **Files:** `POST /api/uploads/{scope}?name=`, `GET /api/uploads`

Every `/api/*` call needs the header `Authorization: Bearer <WORKFORCE_API_TOKEN>`.

---

## 1. Accounts and things to have ready

1. **Oracle Cloud** account (cloud.oracle.com → Start for free). A card is asked for identity only; Always Free resources are never charged. Pick a **home region** close to you: you can't change it later, and Always Free machines only run there.
2. **GitHub** access to this repository (`j-ai-cmd/blank_Claude-project`), branch `claude/busy-franklin-ni0781` (or `main` once merged).
3. **Claude Pro/Max** plan, plus the Claude Code CLI on your laptop (`npm i -g @anthropic-ai/claude-code`).
4. **Slack:** your workspace and your existing Slack app.
6. **Vercel** account (Hobby).
7. Optional: a **Gmail app password** (Google Account → Security → 2-Step Verification → App passwords), for the 9 am inbox scan and for sending.

---

## 2. Create the secrets (on your laptop)

| Secret | How to get it | Goes into |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | On your laptop run `claude setup-token`, log in, copy the token it prints. In claude.ai settings, keep **usage credits OFF** | server `.env` |
| `SLACK_BOT_TOKEN` | Slack app → OAuth & Permissions → Bot User OAuth Token (`xoxb-…`). It appears after you install the app (step 6) | server `.env` |
| `SLACK_SIGNING_SECRET` | Slack app → Basic Information → Signing Secret | server `.env` |
| `OWNER_SLACK_ID` | In Slack: your profile → ⋮ → Copy member ID (`U…`) | server `.env` |
| `WORKFORCE_API_TOKEN` | Run `openssl rand -hex 32` | server `.env` **and** the Live Office connect dialog |
| `POSTGRES_PASSWORD` | Run `openssl rand -hex 24` | server `.env` |
| `RUNTIME_TOKEN` | Run `openssl rand -hex 32` | server `.env` (shared only by the api and runtime containers) |

---

## 3. Create the server (Oracle Cloud console)

1. ☰ → **Compute → Instances → Create instance**. Name: `workforce`.
2. **Image and shape → Edit**:
   - Image: **Canonical Ubuntu 24.04** (the aarch64 build is picked automatically for Ampere).
   - Shape: **Ampere → VM.Standard.A1.Flex**, **4 OCPUs, 24 GB memory** (the whole Always Free allowance).
   - If you get "Out of capacity", try another availability domain in the same form, or try again later. This is common for free Ampere machines.
3. **Networking**: keep "Create new virtual cloud network" and **Assign a public IPv4 address**.
4. **SSH keys**: "Generate a key pair for me" → **Save private key**.
5. **Boot volume**: set **100 GB** (Always Free includes 200 GB). Voice models and video renders need the space.
6. Create, then note the **Public IP address**, e.g. `129.146.20.5`.
7. Open the web ports in Oracle's network: the instance → **Subnet** link → **Default Security List** → **Add Ingress Rules**:
   - Source `0.0.0.0/0`, TCP, destination port **80**
   - Source `0.0.0.0/0`, TCP, destination port **443**
   (Port 22 for SSH is open already.)
8. Recommended: make the IP permanent so your HTTPS name never changes. Instance → **Attached VNICs** → the VNIC → **IPv4 Addresses** → edit → **Reserved public IP** (one is free).
9. Connect: `chmod 400 ssh-key.key && ssh -i ssh-key.key ubuntu@<PUBLIC-IP>`

## 4. Prepare the server (run on the server)

```bash
# Oracle's Ubuntu image also blocks web ports in the server's own firewall: open 80 and 443
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save

# a little swap as a safety net for voice-model loading
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker ubuntu
exit            # log out, then ssh back in so the docker group applies
```

```bash
# code (private repo: use a GitHub fine-grained token with read access when git asks for a password)
git clone https://github.com/j-ai-cmd/blank_Claude-project.git workforce
cd workforce
git checkout claude/busy-franklin-ni0781
mkdir -p uploads outbox proposals
```

## 5. Configure the backend (on the server, inside `~/workforce`)

```bash
cp .env.example .env
nano .env
```
Fill in these values (from step 2):
```
CLAUDE_CODE_OAUTH_TOKEN=...
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
OWNER_SLACK_ID=U...
WORKFORCE_API_TOKEN=...
POSTGRES_PASSWORD=...
WORKFORCE_BILLING=plan
WORKFORCE_FRONTEND_ORIGIN=https://<your-vercel-app>.vercel.app    # fill after step 9; leave empty for now
SITE_HOST=129-146-20-5.sslip.io                                   # your IP with dashes, or your domain
RUNTIME_BACKEND=remote
RUNTIME_TOKEN=...
IMAP_HOST=imap.gmail.com     # optional (9 am scan)
IMAP_USER=you@gmail.com
IMAP_PASSWORD=<gmail app password>
SMTP_HOST=                   # optional; empty = approved emails go to outbox/ for you to send
```
Also set your Slack ID in the config:
```bash
sed -i 's/U_OWNER/<your U... id>/' config/org.yaml config/permissions.yaml
```

**HTTPS host name.**
- **Without a domain:** use `<ip-with-dashes>.sslip.io`. For `129.146.20.5` that's `129-146-20-5.sslip.io`.
- **With a domain:** add an `A` record pointing at the IP and use that name.

Put it in `.env` as `SITE_HOST`; `deploy/Caddyfile` reads it from there.

## 6. Start the backend

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build    # first build ~15 min (voice libraries)
docker compose logs -f api        # look for "0 error(s), 41 employees checked" and "Uvicorn running"; Ctrl+C to stop following
curl https://<YOUR-HOST>/health   # -> {"ok":true}
```
If the API exits right away, `docker compose logs api` shows the config validation error.

## 7. Connect Slack

1. Slack app → **App Manifest**: paste `deploy/slack-manifest.yaml`, replace every `https://YOUR-HOST` with `https://<YOUR-HOST>`, save.
2. Slack verifies the Events URL. It must show **Verified**; if not, check step 6.
3. **Install / Reinstall** to the workspace. Copy the `xoxb-` token into `.env` if it changed, then `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`.
4. Create the channels if they don't exist, then in each one type `/invite @Workforce`:
   `#hq #studio #sales #talent #engineering #ops #approvals #agent-log`
5. Test: in #sales type `write one short caption for a video about why sleep matters. No numbers.`
   Sam should post a contract in the thread, and a delivery card should follow. `/wf status` lists tasks.

## 8. Check the runtime (videos, voices, code tests)

The runtime container started with everything else in step 6. It has no published port: only the API can reach it.

```bash
docker compose exec api python -c "import httpx,os; print(httpx.get('http://runtime:8080/health').json())"   # {'ok': True}
docker compose logs runtime
```

- **First voice request:** it downloads the voice models (a few GB) into the `models` volume. That takes several minutes, once.
- **Voice speed:** there's no GPU on the free tier, so voices run on the processor. Kokoro is quick. Your cloned voice (Chatterbox) takes a few minutes per reel.
- **Using Modal instead:** run `modal deploy deploy/modal_app.py` from your laptop, then set `RUNTIME_URL=<the .modal.run URL>` in `.env`. Modal's free credit needs a card on file.

## 9. Deploy the Live Office on Vercel and connect it

1. vercel.com → **Add New → Project** → import the GitHub repo.
2. **Root Directory: `frontend`**. Framework: Vite (auto-detected; `frontend/vercel.json` sets build `npm run build` and output `dist`).
3. Environment variable (optional, pre-fills the connect dialog): `VITE_API_URL = https://<YOUR-HOST>`. Deploy.
4. Copy the site URL (e.g. `https://live-office-xyz.vercel.app`). On the server set `WORKFORCE_FRONTEND_ORIGIN=<that URL>` in `.env` (no trailing slash; separate several with commas), then restart.
5. Open the site → click the **status bar** at the top → **Connect backend** → URL `https://<YOUR-HOST>` → token = your `WORKFORCE_API_TOKEN` → Connect. The status should turn **live**, and the office should show the 41 employees.
6. Test: click Sam's desk → give a short task → watch the note walk across the office; approve in the decision card.

The token is stored only in that browser. Use "Disconnect" on shared computers.

## 10. Final checklist

- [ ] `https://<YOUR-HOST>/health` returns `{"ok":true}`
- [ ] The Slack Events URL shows Verified; a message in #sales gets Sam's contract
- [ ] `/wf status` answers
- [ ] The Live Office shows **live** and can give a task
- [ ] A Studio video request is accepted (it's refused with "isn't set up yet" if the runtime isn't reachable)
- [ ] At 09:00 IST the inbox scan posts in #sales (it asks for IMAP if not configured)

## 11. Day-to-day

| Need | Command (on the server in `~/workforce`) |
|---|---|
| Logs | `docker compose logs -f api` |
| Update to the latest code | `git pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build` |
| Stop everything immediately | `/wf pause-all` in Slack (or `docker compose stop api`) |
| Back up the database | `docker compose exec db pg_dump -U workforce workforce > backup-$(date +%F).sql` (weekly; copy it off the machine) |
| Add a file for an employee | `curl -X POST "https://<HOST>/api/uploads/profile?name=cv.md" -H "Authorization: Bearer <token>" --data-binary @cv.md` (scopes: `profile`, `finance`, `general`, `show-jai`, `show-sherlock`, `show-peter`, `show-striker`, `lane-company`) |
| Hire a proposed employee | `/wf hire <file in proposals/>` |

## 12. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `curl /health` fails | Ports 80/443 not open (Oracle security list in step 3 **and** the iptables rules in step 4), Caddy can't get a certificate (wrong `SITE_HOST`), or the API crashed: `docker compose logs caddy api` |
| Slack says the URL didn't respond | HTTPS not working yet, or `SLACK_SIGNING_SECRET` wrong (the API answers 401) |
| Bot doesn't answer in a channel | The bot isn't invited (`/invite @Workforce`), or the message wasn't from `OWNER_SLACK_ID` (only you can give tasks) |
| "Couldn't reach Claude (Authentication error…)" | `CLAUDE_CODE_OAUTH_TOKEN` expired or rotated: run `claude setup-token` again, update `.env`, restart |
| Live Office stuck on "reconnecting" | `WORKFORCE_FRONTEND_ORIGIN` doesn't exactly match the Vercel URL, or the token in the connect dialog is wrong |
| "needs the render runtime … isn't set up yet" | `RUNTIME_TOKEN` missing from `.env`, or the runtime container isn't running: `docker compose ps runtime` |
| Out of memory / very slow | Check the machine is the 4-core / 24 GB shape and swap is on (`free -h`); a cloned-voice reel is slow on CPU by nature |
| Oracle stops the machine as "idle" | Always Free machines with very low use for 7 days can be reclaimed. Normal daily use avoids it; upgrading the account to Pay-As-You-Go (still free within the limits) removes the rule |
