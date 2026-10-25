# curse_bot

**English** | [Русский](README.ru.md)

A Telegram bot that watches CurseForge for new World of Warcraft addons and posts each one
to a channel: an album (logo + screenshots), name, author, categories, game versions
(Retail / Classic / Forever), a short description and a link.

## Setup

1. A CurseForge API key — https://console.curseforge.com.
2. A bot — get a token from @BotFather.
3. Make the bot an admin of the channel (with the right to post messages).
4. `cp .env.example .env` and fill it in. `TELEGRAM_CHAT_ID` is `@channel_name` or a numeric id `-100…`.
   The CurseForge key contains `$` — wrap it in **single** quotes
   (`CURSEFORGE_API_KEY='$2a$10$…'`), otherwise `uv` and `docker compose` mangle the value with
   variable substitution and CurseForge answers 403.

`FLAVORS` selects which versions to announce (`retail`, `classic`, `forever`, comma-separated;
empty means all). An addon passes the filter if, when it is approved, it has files for at least
one of these versions.

How the bot finds new addons: CurseForge search is closed to regular API keys, so the bot
walks new project ids (they grow in order), keeps the WoW projects and announces each one
once CurseForge moderators approve it. That is about 200 addons a day right now — narrow the
stream with `FLAVORS`.

## Running in Docker

```bash
docker compose up -d --build
docker compose logs -f
```

The state (the id cursor and the moderation queue) lives in the `botdata` volume (`/data/bot.db`
in the container). On its very first start the bot only finds the current highest CurseForge
project id (`baseline` in the log) and sends nothing — notifications cover projects created
after that.

Test sending (posts the 2 latest addons once, leaves the database alone):

```bash
docker compose run --rm bot --send-latest 2
```

## Telegram commands

The bot answers private messages only from users listed in `TELEGRAM_ADMIN_IDS`
(`config.adminIds` in the chart). It does not answer anyone else, but logs their id:
`message from a user who is not allowed, id=…`. That is how you find your own id; once you
have access, `/help` shows it too.

| Command | What it does |
|---|---|
| `/status` | last poll, id cursor, how many addons await moderation, how many were posted to the channel in 24 h, version filter |
| `/latest [N]` | the N latest approved addons (3 by default, 10 at most) — to your private chat, not the channel |
| `/pending` | the moderation queue: up to 20 addons, each with its status and how long it has waited |
| `/flavors` | show the version filter; `/flavors forever,retail` sets it, `all` removes it, `reset` restores the configured one |
| `/lang` | reply language: `/lang en`, `/lang ru`, or buttons under `/lang` |
| `/help` | the list of commands and your id |

The bot replies in the language chosen with `/lang` (remembered per user), or else in the
language of your Telegram client: Russian for `ru`, English otherwise. The command menu is
registered in both languages. Channel posts and logs are not translated.

A filter set with `/flavors` is stored in the database and overrides `FLAVORS` from the settings.
The bot long-polls incoming messages (`getUpdates`) between CurseForge cycles, so only one
instance may run per bot token.

## Kubernetes (Helm)

The image `ghcr.io/gera-corp-org/curse-bot` and the chart `oci://ghcr.io/gera-corp-org/charts/curse-bot`
are published by CI. By default secrets come from Vault through the bank-vaults
vault-secrets-webhook (they never land in a Kubernetes Secret):

```bash
vault kv put secret/curse-bot \
  CURSEFORGE_API_KEY='$2a$10$…' TELEGRAM_BOT_TOKEN='…' TELEGRAM_CHAT_ID='…'
helm install curse-bot oci://ghcr.io/gera-corp-org/charts/curse-bot -n curse-bot --create-namespace
```

Without Vault, use an existing Secret with the same three keys:
`--set vault.enabled=false --set existingSecret=<name>`. Other settings are in
[`charts/curse-bot/values.yaml`](charts/curse-bot/values.yaml) (`config.flavors`,
`config.pollInterval`, `config.adminIds`, `persistence.*`).

Run a single instance: two instances (say, in the cluster and in `docker compose`) post every
addon twice.

## Releases

```bash
git tag v0.4.0 && git push origin v0.4.0
```

The tag runs CI: tests → image `0.4.0` (amd64 + arm64) → chart `0.4.0` in GHCR → a GitHub
Release with generated notes. The chart is published only after the image, so ArgoCD with
`targetRevision: 0.*` never sees a version without an image. Every push to `master` builds the
images `latest` and `sha-<commit>`.

## Security

**Image**:
- `gcr.io/distroless/python3-debian13:nonroot`: no shell, package manager or `pip`;
- the process runs as uid 65532;
- code and dependencies are owned by root and read-only, bytecode is precompiled;
- `/data` is the only writable path;
- base images are pinned by digest and GitHub Actions by SHA; Dependabot keeps them current.

**CI**:
- hadolint checks the Dockerfile;
- an SBOM and provenance are attached to the image;
- a Sigstore attestation;
- Trivy reports to GitHub Security, and a `CRITICAL` finding stops the release: no image, no chart.

Verify where an image came from:

```bash
gh attestation verify oci://ghcr.io/gera-corp-org/curse-bot:0.4.0 -o gera-corp-org
```

**Pod** (chart):
- passes Pod Security `restricted`: `runAsNonRoot`, read-only root, `drop: ALL`,
  `seccomp: RuntimeDefault`, no privilege escalation;
- `/tmp` in memory, memory and `ephemeral-storage` limits;
- the ServiceAccount token is mounted only for vault-env;
- a NetworkPolicy denies all ingress and allows egress only to DNS and TCP 443;
- a liveness probe restarts the container if the polling loop hangs, by checking the age of `/tmp/heartbeat`;
- the chart refuses to render with uid 0, without `runAsNonRoot` or without a read-only root.

`docker compose` applies the same restrictions: `read_only`, `cap_drop: ALL`, `no-new-privileges`,
memory and process limits, a heartbeat healthcheck.

## Running without Docker

```bash
uv sync
uv run --env-file .env python -m bot
```

A sample systemd unit (`/etc/systemd/system/curse-bot.service`); adjust the path and user:

```ini
[Unit]
Description=CurseForge WoW addons -> Telegram
After=network-online.target
Wants=network-online.target

[Service]
User=gera
WorkingDirectory=/home/gera/curse_bot
ExecStart=/home/gera/.local/bin/uv run --env-file .env python -m bot
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

## Development

```bash
uv run pytest
uv run --env-file .env python -m scripts.probe   # live check of the CurseForge API
# after changing dependencies, refresh requirements.txt for the image (CI checks it):
uv export --no-dev --no-emit-project --no-header --format requirements-txt -o requirements.txt
```
