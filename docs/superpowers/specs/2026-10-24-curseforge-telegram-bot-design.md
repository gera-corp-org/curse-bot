# CurseForge → Telegram: a bot for new WoW addons

Date: 2026-10-24 (revised after the live API check the same day; commands added in 0.3.0)

## Goal

The bot watches CurseForge for **new** World of Warcraft addons and posts each one to a single
Telegram channel/chat: name, author, categories, supported game versions
(Retail / Classic / Forever), a short description, a link and images (logo + screenshots).

Commands in private messages (since 0.3.0), for users from `TELEGRAM_ADMIN_IDS` only:
`/status`, `/latest [N]`, `/pending`, `/flavors`, `/help`. Incoming messages are fetched with
`getUpdates` (long polling, up to 30 s) instead of sleeping between CurseForge polls — in the
same thread; the last processed update is stored in `meta.tg_offset`. The filter set with
`/flavors` is stored in `meta.flavors` and overrides `FLAVORS`.

Out of scope: notifications about updates of existing addons, per-user subscriptions,
notifications that an addon later gained support for another game version.

## Decisions

| Question | Decision |
|---|---|
| Game versions | Labels in every message + a filter in the config |
| Recipients | One channel/chat, set by `TELEGRAM_CHAT_ID` |
| Hosting | Kubernetes (Helm chart, ArgoCD) or any host with Docker/systemd; a long-running process |
| Format | Album: logo + up to 3 screenshots, caption on the first image |
| What counts as "new" | Scanning new project ids (`POST /v1/mods`); new = a WoW project with an id above the cursor, announced once approved |
| Volume | Every new addon that passes `FLAVORS` (about 200 a day as of 2026-10) |
| Late version support | Not tracked: labels and filter are evaluated when the addon is approved |

## Data source: the CurseForge API

- Base URL `https://api.curseforge.com`, key in the `x-api-key` header
  (issued at console.curseforge.com). WoW: `gameId=1`.
- **Search, `GET /v1/mods/search`, is forbidden for the user's key** (403 for any game) while
  other endpoints work, so search is not used.
- Mods by id: `POST /v1/mods` with `{"modIds": [...]}` (up to 1000 ids per request) returns
  only existing ones; if none exist, the answer is **404** (= an empty list).
- Project ids are shared by all CurseForge games and grow in order (max ≈ 1 763 684 on
  2026-10-24; ~2 000 new ids a day, ~200 of them WoW; ~17% of ids are gaps).
  Projects are visible right after creation, before moderation.
- Mod statuses: 1 New, 2 ChangesRequired, 4 Approved, 5 Rejected, 6 ChangesMade, 9 Deleted.
  Approved = `status == 4` and `isAvailable == true`.
- `Mod.dateReleased` is the date of the **latest file**, not of the project (DBM: created
  2008, `dateReleased` today), so dates cannot tell what is new.
- Version types: `GET /v1/games/1/version-types` (confirmed live): Retail 517,
  Classic Era 67408, TBC 73246, Wrath 73713, Titan 81212, Cata 77522, MoP 79434,
  **Forever 88568** (`'WoW Forever'`, slug `wow-forever`).
- Mod fields used: `id`, `gameId`, `status`, `isAvailable`, `name`, `summary`,
  `links.websiteUrl`, `authors[].name`, `categories[].name`, `logo.url`, `screenshots[].url`,
  `dateCreated`, `latestFilesIndexes[].gameVersionTypeId`.

`scripts/probe.py` is the live check: the version-type table, the current highest id and
statistics for the last ~10 000 ids (per game, WoW per day, statuses, how many have Forever files).

## Layout

```
curse_bot/
  bot/
    config.py      — settings from the environment (.env)
    curseforge.py  — CurseForge HTTP client: mods by id, highest-id search, version types
    flavors.py     — gameVersionTypeId → group/label, filter (pure functions)
    storage.py     — SQLite: moderation queue, cursor, sent log, meta values
    formatter.py   — caption and image selection (pure functions)
    telegram.py    — Bot API: sending with fallback and 429 handling, getUpdates, setMyCommands
    commands.py    — private-chat commands and the long-polling wait between cycles
    main.py        — the polling loop, CLI flags
  scripts/probe.py — live check of the CurseForge API
  charts/curse-bot — Helm chart
  tests/
  Dockerfile, docker-compose.yml, .env.example, README.md, README.ru.md
```

Stack: Python 3.13 (same as the distroless image), `httpx`, `sqlite3` from the standard
library, `pytest`. The Telegram Bot API is called directly through `httpx`, no framework.

## Configuration

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `CURSEFORGE_API_KEY` | yes | — | CurseForge key |
| `TELEGRAM_BOT_TOKEN` | yes | — | bot token |
| `TELEGRAM_CHAT_ID` | yes | — | channel/chat (the bot must be a channel admin) |
| `FLAVORS` | no | empty = all | comma-separated groups: `retail,classic,forever` |
| `POLL_INTERVAL` | no | `600` | seconds between cycles |
| `DB_PATH` | no | `data/bot.db` | SQLite path |
| `TELEGRAM_ADMIN_IDS` | no | empty | comma-separated user ids the bot answers commands from; empty disables commands |
| `HEARTBEAT_FILE` | no | — | file the bot touches after every cycle (liveness probe); empty means do not write |

An unknown `FLAVORS` value or a missing required variable is a startup error. Empty
`POLL_INTERVAL` / `DB_PATH` fall back to the defaults. Values containing `$` (a CurseForge key
looks like `$2a$10$…`) must be wrapped in **single** quotes in `.env`, otherwise `uv` and
`docker compose` treat `$…` as variable substitution.

## Game versions (flavors.py)

Groups come from a built-in table of known ids (see above):

- **Retail** — 517;
- **Classic** — 67408 (Era), 73246 (TBC), 73713 (Wrath), 81212 (Titan), 77522 (Cata), 79434 (MoP);
- **Forever** — 88568.

At startup the version types are also loaded from the API. Types missing from the table are
recognised by name/slug: "forever" → Forever, "classic" → Classic, otherwise no group.
If the types cannot be loaded, the built-in table is used.

The label in a message: groups joined with ` · `, Classic with its specific versions in
parentheses: `Retail · Classic (Era, MoP) · Forever`. A type outside every group is shown
under its API name and logged as `unknown version type`; when a filter is set, `FLAVORS`
does not let it through. An addon passes the filter if at least one of its groups is in `FLAVORS`.

## Data flow

**First start** (no `next_id` cursor in the `meta` table): find the current highest id
(exponential + binary search in windows of 1000 ids), cursor = highest + 1, send nothing.

**`--send-latest N`**: post the N latest approved WoW addons once (walking ids back from the
cursor) and exit; the database is untouched and no filter applies.

**Cycle:**
1. Forward scan: mods with ids `[next_id, next_id+1000)`; cursor → highest id found + 1.
   If the window is almost full (the bot was down for a while), take the next window, at most
   20 per cycle (beyond that, a warning in the log). WoW projects found (`gameId == 1`) go to
   the `pending` queue (id + time first seen).
2. Recheck the queue with one request (per 1000 ids), in ascending id order; an error while
   processing one addon is logged and does not affect the others (the addon stays queued):
   - approved and passes `FLAVORS` → post it; remove it from the queue **only after a
     successful post**, and record it in the sent log;
   - approved, `FLAVORS` set, but no files (versions) yet → wait;
   - approved, but its versions do not pass `FLAVORS` → remove without posting;
   - rejected / deleted (`status` 5, 9) → remove;
   - not approved (or not returned by the API) for more than 14 days → remove with a log line.
3. A ~3 s pause between messages; then wait `POLL_INTERVAL` — answering commands during the
   wait when `TELEGRAM_ADMIN_IDS` is set, sleeping otherwise. The heartbeat file is touched
   after every cycle.

## Message (formatter.py, telegram.py)

Images: `logo.url` + the first 3 `screenshots[].url` (full size, not thumbnails),
no duplicates, 4 at most.

- ≥2 images → `sendMediaGroup`, caption on the first;
- 1 image → `sendPhoto`;
- 0 images → `sendMessage`.

Caption (`parse_mode=HTML`, at most 1024 characters; `sendMessage` uses the same text):

```
🆕 <b>Name</b>
👤 Author1, Author2 · 📂 Category1, Category2
🎮 Retail · Classic (Era, MoP) · Forever

summary

🔗 https://www.curseforge.com/wow/addons/slug
```

Every API field is escaped (`html.escape`). When over the limit, only `summary` is cut
(with `…`); the other lines stay.

## Error handling

| Situation | Behavior |
|---|---|
| CurseForge: network, timeout, 5xx | log, skip the cycle; the database is unchanged |
| CurseForge: 403 | log "invalid or revoked API key", the process keeps running |
| Telegram: 429 | wait `retry_after`, retry (up to 3 times) |
| Telegram: album failure (an image could not be fetched, etc.) | fallback: `sendPhoto` with the logo → `sendMessage` |
| Telegram: other errors (wrong chat_id, etc.) | log, the addon stays queued, retried next cycle |
| Telegram: `getUpdates` fails | log, pause 10 s, keep waiting |
| Malformed data (null fields, `data` not a list, non-JSON) | `CurseForgeError` / skip one addon with `log.exception`; the loop does not crash |
| Any other unexpected exception in the loop | `log.exception`, wait, next cycle |
| A command fails | `log.exception`; the update offset has already moved, so it is not retried forever |
| Process crash | restart by Kubernetes / Docker (`restart: unless-stopped`, `init: true`) / systemd; state is in SQLite |

Logs go to stdout with time and level. The bot token never reaches the logs: the `httpx`
logger is raised to `WARNING`, since at `INFO` it prints request URLs, and Telegram URLs
contain the token.

## Testing (pytest)

- `flavors`: known ids map to groups; unknown types are recognised by name; filter; label
  format; unknown type.
- `formatter`: escaping, cutting to 1024, image selection (logo + 3 screenshots, no
  screenshots, no logo, logo duplicated among screenshots).
- `curseforge`: `POST /v1/mods` request shape, chunks of 1000, 404 → empty, errors,
  highest-id search on a model with gaps.
- `storage`: queue, cursor, sent log, persistence across restarts.
- `main` (with fake clients): the first start sets the cursor and sends nothing; a new WoW
  project waits for approval and is posted once; non-WoW is ignored; catch-up after downtime
  and the window cap; rejected/deleted/stale entries are removed; the `FLAVORS` filter and its
  `/flavors` override; on a Telegram error the addon is retried next cycle; heartbeat.
- `commands`: access control (only admins, only private chats), every command, long polling
  with a stored offset, survival of Telegram and command errors.
- Manual: `scripts/probe.py` and a live `--send-latest 2` run to the user's chat.
