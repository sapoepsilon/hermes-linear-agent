#!/usr/bin/env python3
"""Self-check for the Linear handler's signature verification (the security gate)."""
import hashlib
import hmac
import importlib.util
import os
from pathlib import Path

os.environ["LINEAR_WEBHOOK_SECRET"] = "test-secret"
os.environ["LINEAR_ACCESS_TOKEN"] = "test-token"

spec = importlib.util.spec_from_file_location("h", Path(__file__).with_name("linear_agent_handler.py"))
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)

body = b'{"type":"AgentSessionEvent","action":"created","agentSession":{"id":"x"}}'
good = hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()

assert h.verify(body, good), "correct signature must pass"
assert not h.verify(body, "deadbeef"), "wrong signature must fail"
assert not h.verify(body, ""), "missing signature must fail"
assert not h.verify(body + b"x", good), "tampered body must fail"
print("OK: signature verification rejects forged/missing/tampered, accepts valid")
