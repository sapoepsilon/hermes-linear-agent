#!/usr/bin/env python3
"""Self-check for the handler's token auto-refresh (expired token -> refresh -> retry)."""
import importlib.util
import json
import os
import tempfile
from pathlib import Path

tokens = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
json.dump({"access_token": "stale", "refresh_token": "r1"}, tokens)
tokens.close()

os.environ.update(LINEAR_WEBHOOK_SECRET="s", LINEAR_TOKENS_FILE=tokens.name,
                  LINEAR_CLIENT_ID="cid", LINEAR_CLIENT_SECRET="csec")
spec = importlib.util.spec_from_file_location("h", Path(__file__).with_name("linear_agent_handler.py"))
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)

auth_err = {"errors": [{"message": "x", "extensions": {"type": "authentication error"}}]}
ok = {"data": {"agentActivityCreate": {"success": True}}}
calls = []


class FakeResp:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def fake_urlopen(request, timeout=None):
    calls.append(request.full_url)
    if request.full_url == h.TOKEN_URL:
        return FakeResp({"access_token": "fresh", "refresh_token": "r2"})
    token = request.headers["Authorization"].split()[-1]
    return FakeResp(ok if token == "fresh" else auth_err)


h.urllib.request.urlopen = fake_urlopen

assert h.graphql("mutation{...}", {}) == ok, "auth error must refresh then succeed"
assert json.load(open(tokens.name)) == {"access_token": "fresh", "refresh_token": "r2"}, \
    "rotated token pair must be persisted"
assert h.TOKEN_URL in calls and len(calls) == 3, "expected graphql, refresh, retry"
assert h.graphql("q", {}) == ok and len(calls) == 4, "fresh token must be reused without re-refresh"
os.unlink(tokens.name)
print("OK: 401 -> refresh -> retry works; rotated refresh token persisted; fresh token reused")
