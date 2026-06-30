# hermes-linear-agent

Control a self-hosted [Hermes](https://github.com/NousResearch/hermes-agent) agent from
**Linear** — assign an issue to it or @-mention it, and it replies in the issue — **without
exposing any inbound port** on the machine the agent runs on.

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

## Test

`python3 test_linear_handler.py` — checks signature verification (rejects forged/missing/tampered).

## License

MIT
