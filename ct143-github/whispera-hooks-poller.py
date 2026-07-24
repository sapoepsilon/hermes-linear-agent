#!/usr/bin/env python3
"""Drains GitHub events from the Cloudflare relay (outbound only) and hands
them to the local Hermes webhook route. Nothing inbound ever reaches this box."""
import json
import os
import time
import urllib.request

WORKER = os.environ["WORKER_URL"]
TOKEN = os.environ["POLL_TOKEN"]
HERMES_ROUTES = {
    "pull_request_review_comment": "http://127.0.0.1:8644/webhooks/whispera-pr-review",
}
HERMES_DEFAULT = os.environ.get(
    "HERMES_URL", "http://127.0.0.1:8644/webhooks/whispera-pr-assistant"
)
INTERVAL = int(os.environ.get("INTERVAL", "30"))


def drain():
    req = urllib.request.Request(
        WORKER + "/drain",
        headers={
            "Authorization": "Bearer " + TOKEN,
            # Cloudflare 403s python-urllib's default User-Agent.
            "User-Agent": "whispera-hooks-poller/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp).get("events", [])


def forward(event):
    body = event["body"].encode()
    req = urllib.request.Request(
        HERMES_ROUTES.get(event["event"], HERMES_DEFAULT),
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": event["event"],
            "X-GitHub-Delivery": event.get("delivery", ""),
            "X-Hub-Signature-256": event["signature"],
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        print(f"forwarded {event.get('delivery', '?')} -> {resp.status}", flush=True)


while True:
    try:
        for evt in drain():
            try:
                forward(evt)
            except Exception as exc:  # noqa: BLE001 — keep the loop alive
                print(f"forward failed: {exc}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"drain failed: {exc}", flush=True)
    time.sleep(INTERVAL)
