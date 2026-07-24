#!/bin/sh
# Installed as /usr/local/bin/whispera-gh — acts as whispera-agent[bot]:
# every call gets a fresh installation token. The plain `gh` on the box keeps
# its own (human) auth; agent replies use this wrapper explicitly.
GH_TOKEN=$(python3 /usr/local/bin/whispera-agent-token.py) exec /usr/local/bin/gh "$@"
