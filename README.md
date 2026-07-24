# hermes-linear-agent

Control a self-hosted [Hermes](https://github.com/NousResearch/hermes-agent) agent from
**Linear** — assign an issue to it or @-mention it, and it replies in the issue — **without
exposing any inbound port** on the machine the agent runs on. A companion
[GitHub relay](#github-relay) does the same for @-mentions in GitHub issue/PR comments.

Linear webhooks come from the public internet; your agent box stays private. A tiny
Cloudflare Worker is the only public surface, and your box dials *out* to it over a
WebSocket. The Worker is dumb transport — the handler HMAC-verifies every webhook, so
neither the Worker nor Cloudflare can forge an event.

```
Linear ──webhook──▶ Cloudflare Worker (/linear)        ← only public surface
                      │  Durable Object, acks Linear <5s
                      ▼ pushes down a held-open WebSocket
agent box: relay client ◀── dials OUT ──┘   (no inbound port)
        │ replays with original headers
        ▼
   handler :8645 ── HMAC-verify ──▶ hermes -z ──▶ reply via Linear agentActivityCreate
```

## Components

| File | Runs on | Role |
|---|---|---|
| `cf-worker/` | Cloudflare (free `*.workers.dev`) | public ingress; bridges the webhook to a held-open WebSocket via a Durable Object |
| `relay-client/client.js` | agent box | dials out to the Worker, replays events to the local handler (Node 18+, no deps — built-in `WebSocket`) |
| `linear_agent_handler.py` | agent box | verifies `Linear-Signature`, acks, runs `hermes -z`, replies via Linear GraphQL (Python 3, stdlib only) |
| `oauth_install.py` | anywhere with a browser | one-time `actor=app` OAuth install → prints the agent access token |

## Setup

1. **Deploy the Worker** (`cd cf-worker && npx wrangler deploy`) → note its `…workers.dev` URL.
2. **Create a Linear OAuth app** (Settings → API → OAuth applications): redirect URI
   `http://localhost:8744/callback`; enable the **Agent session events** webhook with URL
   `https://<your-worker>.workers.dev/linear`. Copy Client ID / Secret / Webhook signing secret.
3. **Get the access token:** `CLIENT_ID=… CLIENT_SECRET=… python3 oauth_install.py`, authorize
   in the browser (workspace admin), copy the printed token.
4. **Configure + run the handler** on the agent box (see `linear-agent.env.example`):
   set `LINEAR_WEBHOOK_SECRET`, `LINEAR_ACCESS_TOKEN`, then run `python3 linear_agent_handler.py`.
5. **Run the relay client:** `WORKER_WS=wss://<your-worker>.workers.dev/connect node relay-client/client.js`.
6. **Use it:** assign a Linear issue to the agent (or @-mention it) → it replies.

Run both the handler and the relay client as services (systemd units are trivial; both restart-on-failure).

## Security notes

- All secrets are read from env vars — nothing is committed. HMAC verification (`Linear-Signature`)
  means the Worker is untrusted transport.
- Linear workspaces are private, so the input authors are your teammates — but the agent still
  runs `hermes -z` on issue text, so scope the agent's tools/credentials to least privilege.

## GitHub relay

Same idea for **GitHub**: @-mention the agent's GitHub App in an issue comment or inline PR
review comment on a public repo, and the agent acts and replies as the App's bot user. Built
for an open-source repo where *anyone* can comment but only the owner may command the agent.

```
GitHub App ──webhook──▶ Cloudflare Worker (/github)     ← only public surface
    rate limit (per-IP) → HMAC verify → event filter → author allowlist → KV queue
agent box: poller ── GET /drain (Bearer token, outbound only) ──▶ replays event
    with original headers ──▶ Hermes webhook route :8644 (re-verifies HMAC)
    ──▶ reply via `gh` wrapper as <app>[bot] (installation token minted from the App PEM)
```

| File | Runs on | Role |
|---|---|---|
| `github-relay/` | Cloudflare (free `*.workers.dev`) | public ingress; queues allowlisted events in KV (24h TTL), serves `/drain` |
| `ct143-github/whispera-hooks-poller.py` | agent box | drains the Worker every 30s, replays to the local Hermes webhook route (stdlib only) |
| `ct143-github/whispera-agent-token.py` | agent box | mints + caches GitHub App installation tokens (openssl RS256, no deps) |
| `ct143-github/gh-wrapper.sh` | agent box | installed as `whispera-gh`; calls through it act as the App's bot user (plain `gh` keeps its own auth) |

Abuse resistance, layered: Cloudflare edge DDoS protection → per-IP rate limit (20 req/min,
Workers ratelimit binding) + 512 KB body cap → constant-time HMAC check (only GitHub, holding
the webhook secret, passes) → event-type filter → **author allowlist enforced before queueing**
(`ALLOWED_AUTHORS` var), so nobody else's comment ever reaches the agent or its LLM → the
Hermes route re-verifies the HMAC and its prompt independently re-checks repo owner, @-mention,
and author.

Setup mirrors the Linear side:

1. `cd github-relay && npx wrangler kv namespace create EVENTS` → put the id in `wrangler.toml`;
   set `ALLOWED_AUTHORS`; `wrangler secret put WEBHOOK_SECRET` / `POLL_TOKEN`; `npx wrangler deploy`.
2. Create a GitHub App: webhook URL `https://<worker>.workers.dev/github` + the same secret;
   permissions Issues RW, Pull requests RW, Contents R; subscribe to `issue_comment` and
   `pull_request_review_comment`. Install it on your repo(s); download the private key PEM.
3. On the agent box: PEM → `~/.hermes/<app>.pem` (0600), install the poller + token minter +
   `whispera-gh` wrapper, fill `whispera-hooks.env` (see example), enable the systemd unit,
   and add the matching Hermes `platforms.webhook` routes (same secret).

## Test

`python3 test_linear_handler.py` — checks signature verification (rejects forged/missing/tampered).

## License

MIT
