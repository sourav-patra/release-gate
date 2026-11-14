"""Scheduled driver: find unchecked PR heads and v* tags, gate them, post checks.

Env: GH_TOKEN (gate App installation token), NEEDLES_FILE, ACCEPTED_FILE.
Optional args: --repo OWNER/NAME and --sha to gate one commit (workflow_dispatch).
Reads files only: nothing from a target repository is executed.
The config is read from the target's default branch, never from the commit
under test, so a pull request cannot loosen its own rules.
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

API = "https://api.github.com"
CHECK = "release-gate"
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = ".github/release-gate.toml"


def api(method, path, token, body=None):
    req = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def paged(path, token, key=None):
    page, out = 1, []
    sep = "&" if "?" in path else "?"
    while True:
        data = api("GET", "%s%sper_page=100&page=%d" % (path, sep, page), token)
        items = data[key] if key else data
        out += items
        if len(items) < 100:
            return out
        page += 1


def config_text(repo, token):
    """The repository's gate config from its default branch, or None (not opted in)."""
    req = urllib.request.Request(
        "%s/repos/%s/contents/%s" % (API, repo, CONFIG_PATH),
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github.raw+json",
                 "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def has_check(repo, sha, token):
    data = api("GET", "/repos/%s/commits/%s/check-runs?check_name=%s" % (repo, sha, CHECK), token)
    return data["total_count"] > 0


def pending(repo, token):
    """Yield (sha, label) of open PR heads and v* tags with no gate check yet."""
    cands = {}
    for pr in paged("/repos/%s/pulls?state=open" % repo, token):
        cands[pr["head"]["sha"]] = "pr %d" % pr["number"]
    for ref in paged("/repos/%s/git/matching-refs/tags/v" % repo, token):
        obj = ref["object"]
        sha = obj["sha"]
        if obj["type"] == "tag":
            sha = api("GET", "/repos/%s/git/tags/%s" % (repo, sha), token)["object"]["sha"]
        cands[sha] = ref["ref"].replace("refs/tags/", "tag ")
    return [(s, l) for s, l in cands.items() if not has_check(repo, s, token)]


def git(args, cwd, token):
    auth = base64.b64encode(("x-access-token:" + token).encode()).decode()
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_CONFIG_COUNT="2",
               GIT_CONFIG_KEY_0="http.extraheader",
               GIT_CONFIG_VALUE_0="AUTHORIZATION: basic " + auth,
               GIT_CONFIG_KEY_1="core.hooksPath", GIT_CONFIG_VALUE_1=os.devnull)
    p = subprocess.run(["git"] + args, cwd=cwd, env=env, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("git " + args[0] + " failed")
    return p.stdout


def gate_one(repo, sha, cfg_text, token, needles, accepted, workdir):
    url = "https://github.com/%s.git" % repo
    git(["init", "-q", workdir], None, token)
    git(["remote", "add", "origin", url], workdir, token)
    git(["fetch", "-q", "origin", "+refs/heads/*:refs/remotes/origin/*",
         "+refs/tags/*:refs/tags/*", "+refs/pull/*/head:refs/remotes/pull/*"], workdir, token)
    git(["checkout", "-q", "--detach", sha], workdir, token)
    cfg = os.path.join(os.path.dirname(workdir), "release-gate.toml")
    with open(cfg, "w") as f:
        f.write(cfg_text)
    summary = os.path.join(os.path.dirname(workdir), "summary.md")
    rc = subprocess.run([sys.executable, os.path.join(HERE, "run_gate.py"),
                         "--target", workdir, "--config", cfg, "--needles", needles,
                         "--accepted", accepted, "--summary", summary]).returncode
    with open(summary, encoding="utf-8") as f:
        text = f.read()[:60000]
    return rc, text


def post(repo, sha, ok, text, token):
    api("POST", "/repos/%s/check-runs" % repo, token, {
        "name": CHECK, "head_sha": sha, "status": "completed",
        "conclusion": "success" if ok else "failure",
        "output": {"title": "release-gate " + ("passed" if ok else "failed"), "summary": text}})


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="")
    ap.add_argument("--sha", default="")
    a = ap.parse_args(argv)
    token = os.environ["GH_TOKEN"]
    needles, accepted = os.environ["NEEDLES_FILE"], os.environ["ACCEPTED_FILE"]
    if a.repo and a.sha:
        work = [(a.repo, config_text(a.repo, token), [(a.sha, "manual")])]
    else:
        repos = [r["full_name"] for r in paged("/installation/repositories", token, "repositories")]
        work = []
        for r in repos:
            cfg = config_text(r, token)
            if cfg is None:
                continue  # not opted in: nothing is cloned or scanned
            work.append((r, cfg, pending(r, token)))
        print("%d installed, %d opted in" % (len(repos), len(work)), flush=True)
    failed = 0
    for repo, cfg, items in work:
        if cfg is None:
            print("%s: no config, skipped" % repo, flush=True)
            continue
        for sha, label in items:
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    res = gate_one(repo, sha, cfg, token, needles, accepted, os.path.join(tmp, "t"))
                except Exception as e:  # never print content, only the type
                    print("%s %s: error %s" % (repo, sha[:12], type(e).__name__))
                    failed += 1
                    continue
            rc, text = res
            post(repo, sha, rc == 0, text, token)
            print("%s %s (%s): %s" % (repo, sha[:12], label, "pass" if rc == 0 else "FAIL"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
