#!/usr/bin/env python3
"""Prints a valid GitHub App installation token for whispera-agent.

Mints via app JWT (RS256 signed with openssl — no extra deps) and caches the
1-hour installation token, reusing it until <5 minutes remain. Used by the
`gh` wrapper so every gh/git call acts as whispera-agent[bot].
"""
import base64
import json
import os
import subprocess
import time
import urllib.request

APP_ID = os.environ.get("WHISPERA_AGENT_APP_ID", "REPLACE_WITH_APP_ID")
PEM = os.environ.get(
    "WHISPERA_AGENT_PEM", os.path.expanduser("~/.hermes/whispera-agent.pem")
)
CACHE = os.path.expanduser("~/.cache/whispera-agent-token.json")
UA = {"User-Agent": "whispera-agent-token/1.0", "Accept": "application/vnd.github+json"}


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def app_jwt() -> str:
    now = int(time.time())
    header = b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    payload = b64url(
        json.dumps({"iat": now - 60, "exp": now + 540, "iss": APP_ID}).encode()
    )
    signing_input = f"{header}.{payload}".encode()
    sig = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", PEM],
        input=signing_input,
        capture_output=True,
        check=True,
    ).stdout
    return f"{header}.{payload}.{b64url(sig)}"


def api(path: str, token: str, method: str = "GET"):
    req = urllib.request.Request(
        "https://api.github.com" + path,
        method=method,
        headers={**UA, "Authorization": "Bearer " + token},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def mint() -> dict:
    jwt = app_jwt()
    installations = api("/app/installations", jwt)
    if not installations:
        raise SystemExit("app has no installations — install it on the repos first")
    inst_id = installations[0]["id"]
    tok = api(f"/app/installations/{inst_id}/access_tokens", jwt, method="POST")
    return {"token": tok["token"], "expires_at": tok["expires_at"]}


def main() -> None:
    try:
        with open(CACHE) as fh:
            cached = json.load(fh)
        expires = time.strptime(cached["expires_at"], "%Y-%m-%dT%H:%M:%SZ")
        if time.mktime(expires) - time.mktime(time.gmtime()) > 300:
            print(cached["token"])
            return
    except Exception:  # noqa: BLE001 — any cache problem just re-mints
        pass

    fresh = mint()
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    fd = os.open(CACHE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(fresh, fh)
    print(fresh["token"])


if __name__ == "__main__":
    main()
