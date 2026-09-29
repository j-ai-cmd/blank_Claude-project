# Deploy on the AWS free plan (single small server)

⚠ The AWS free plan ends after **6 months or when the $100–200 credit runs out** — then the account closes unless you upgrade. Export the database before then (step 8).

Layout: one EC2 instance runs Docker Compose → `api` (Dispatcher) + `db` (Postgres 16) + `caddy` (HTTPS for Slack). No RDS, no load balancer (they burn credits faster).

1. **Create the instance**: EC2 → Launch → Ubuntu 24.04, a free-plan-eligible small type (e.g. t3.micro / t4g.small if offered), 20 GB disk. Security group: allow 22 (your IP only), 80, 443.
2. **Swap** (1 GB RAM is tight — each agent session starts a Claude CLI process):
   `sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile`
3. **Docker**: `curl -fsSL https://get.docker.com | sh && sudo usermod -aG docker ubuntu` (log out/in).
4. **Code**: `git clone <this repo> workforce && cd workforce`
5. **Secrets**: `cp .env.example .env && nano .env` — fill every value (see the file). Never commit `.env`.
6. **HTTPS host name**: Slack needs HTTPS. Without a domain use `<public-ip-with-dashes>.sslip.io`, e.g. `3-120-4-5.sslip.io`. Create `Caddyfile`:
   ```
   3-120-4-5.sslip.io {
     reverse_proxy api:8000
   }
   ```
   and add to `docker-compose.yml` under `services:`:
   ```yaml
   caddy:
     image: caddy:2
     ports: ["80:80", "443:443"]
     volumes: ["./Caddyfile:/etc/caddy/Caddyfile", "caddy:/data"]
     depends_on: [api]
   ```
   (add `caddy:` under `volumes:` too, and remove the `ports` line from `api`).
7. **Start**: `docker compose up -d --build` → `curl https://<host>/health` should print `{"ok":true}`.
   The container validates `config/` at boot and refuses to start if the design files contradict each other.
8. **Slack**: paste `deploy/slack-manifest.yaml` into your app's manifest (replace `YOUR-HOST`), reinstall, invite the bot to `#hq #studio #sales #talent #engineering #ops #approvals #agent-log`.
9. **Backups / leaving AWS**: `docker compose exec db pg_dump -U workforce workforce > backup.sql` (weekly, and before month 6).

Kill switch any time: `/wf pause-all` in Slack.
