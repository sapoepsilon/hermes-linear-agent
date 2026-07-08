#!/usr/bin/env python3
"""One-time Linear OAuth install (actor=app) → prints the agent access token.

Run on the Mac, authorize in the browser, and it captures the code and exchanges
it for the app access token you paste into the agent host's linear-agent.env.

  CLIENT_ID=... CLIENT_SECRET=... python3 oauth_install.py
"""
import json
import os
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

CLIENT_ID = os.environ["CLIENT_ID"]
CLIENT_SECRET = os.environ["CLIENT_SECRET"]
REDIRECT = "http://localhost:8744/callback"
SCOPES = "read,write,app:assignable,app:mentionable"

authorize = "https://linear.app/oauth/authorize?" + urllib.parse.urlencode({
    "client_id": CLIENT_ID,
    "redirect_uri": REDIRECT,
    "response_type": "code",
    "scope": SCOPES,
    "actor": "app",
    # without this, an already-installed app shows "Manage" with no Authorize button
    "prompt": "consent",
})

_token = {}


class Catch(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        query = urllib.parse.urlparse(self.path).query
        code = urllib.parse.parse_qs(query).get("code", [None])[0]
        message = b"Done. Return to the terminal."
        if code:
            data = urllib.parse.urlencode({
                "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
                "redirect_uri": REDIRECT, "code": code,
                "grant_type": "authorization_code",
            }).encode()
            req = urllib.request.Request("https://api.linear.app/oauth/token", data=data)
            with urllib.request.urlopen(req, timeout=30) as resp:
                _token.update(json.loads(resp.read()))
        else:
            message = b"No code in callback."
        self.send_response(200)
        self.end_headers()
        self.wfile.write(message)


def main():
    print("\nOpen this URL (must be a workspace admin), authorize the app:\n")
    print(authorize + "\n")
    try:
        webbrowser.open(authorize)
    except Exception:
        pass
    server = HTTPServer(("localhost", 8744), Catch)
    while "access_token" not in _token:
        server.handle_request()
    token = _token["access_token"]
    # confirm + get the app's workspace user id
    req = urllib.request.Request(
        "https://api.linear.app/graphql",
        data=json.dumps({"query": "query{viewer{id name}}"}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        viewer = json.loads(resp.read()).get("data", {}).get("viewer", {})
    with open("tokens.json", "w") as handle:
        json.dump({"access_token": token,
                   "refresh_token": _token.get("refresh_token")}, handle)
    os.chmod("tokens.json", 0o600)
    print("\n=== SUCCESS ===")
    print("agent user:", viewer)
    print("refresh_token captured:", bool(_token.get("refresh_token")))
    print("\nWrote ./tokens.json — copy it to the agent host (LINEAR_TOKENS_FILE,")
    print("default /opt/linear-agent/tokens.json) and set LINEAR_CLIENT_ID +")
    print("LINEAR_CLIENT_SECRET in linear-agent.env so the handler can auto-refresh.\n")


if __name__ == "__main__":
    main()
