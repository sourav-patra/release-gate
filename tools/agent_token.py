"""Mint a short-lived installation token for the agent App, scoped to one repository.

Usage: agent_token.py --repo OWNER/NAME [--app-id N] [--key PATH]
Env fallbacks: AGENT_APP_ID, AGENT_APP_KEY_PATH.
Prints the token and nothing else on stdout. The key is read only by the
openssl command line (RS256 signing), so no package is needed, and its path
and contents are never printed. Exit: 0 ok, 2 usage or API error.
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def sign_rs256(message, key_path):
    p = subprocess.run(["openssl", "dgst", "-sha256", "-sign", key_path],
                       input=message, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError("signing failed")
    return p.stdout


def make_jwt(app_id, key_path, now=None):
    now = int(now if now is not None else time.time())
    head = b64(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64(json.dumps({"iat": now - 60, "exp": now + 540, "iss": str(app_id)},
                          separators=(",", ":")).encode())
    signing_input = (head + "." + body).encode()
    return head + "." + body + "." + b64(sign_rs256(signing_input, key_path))


def http(method, path, jwt, body=None):
    req = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + jwt,
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def mint(app_id, key_path, repo):
    owner, name = repo.split("/", 1)
    jwt = make_jwt(app_id, key_path)
    inst = http("GET", "/repos/%s/%s/installation" % (owner, name), jwt)["id"]
    tok = http("POST", "/app/installations/%d/access_tokens" % inst, jwt,
               {"repositories": [name]})
    return tok["token"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--app-id", default=os.environ.get("AGENT_APP_ID"))
    ap.add_argument("--key", default=os.environ.get("AGENT_APP_KEY_PATH"))
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 2
    if not a.app_id or not a.key or "/" not in a.repo:
        print("error: need --repo OWNER/NAME, an app id and a key path", file=sys.stderr)
        return 2
    try:
        token = mint(a.app_id, a.key, a.repo)
    except (OSError, RuntimeError, KeyError, ValueError, urllib.error.URLError) as e:
        print("error: " + type(e).__name__, file=sys.stderr)  # type only, never key data
        return 2
    print(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
