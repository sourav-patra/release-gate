"""Check that every author and committer address in a repository is allowed.

Usage: identity_check.py --repo DIR --config FILE
Exit: 0 pass, 1 fail, 2 usage or git error.
Offending addresses are never printed (the output goes to a public check);
they appear as a short hash.
"""
import argparse
import hashlib
import subprocess
import sys
import tomllib


def load_config(path):
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    allowed = set(cfg.get("allowed_emails", []))
    exceptions = {}
    for ex in cfg.get("exceptions", []):
        exceptions.setdefault(ex["email"], set()).update(ex.get("commits", []))
    return allowed, exceptions


def addresses_by_commit(repo):
    out = subprocess.run(
        ["git", "-C", repo, "log", "--all", "--format=%H%x09%ae%x09%ce"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise RuntimeError("git log failed")
    rows = []
    for line in out.stdout.splitlines():
        parts = line.split("	")
        if len(parts) != 3 or not all(parts):
            raise RuntimeError("malformed commit record")  # fail closed
        rows.append((parts[0], parts[1], parts[2]))
    if not rows:
        raise RuntimeError("no commits found")  # an empty history is not a pass
    return rows


def short(addr):
    return "<redacted:" + hashlib.sha256(addr.encode()).hexdigest()[:8] + ">"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--config", required=True)
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return 2
    try:
        allowed, exceptions = load_config(args.config)
        rows = addresses_by_commit(args.repo)
    except (OSError, RuntimeError, tomllib.TOMLDecodeError, KeyError) as e:
        print("error: " + type(e).__name__)
        return 2
    seen = set()
    bad = []
    for sha, ae, ce in rows:
        for addr in (ae, ce):
            seen.add(addr)
            if addr in exceptions:
                # An excepted address is restricted to its listed commits,
                # even when it also appears in allowed_emails.
                if sha not in exceptions[addr]:
                    bad.append((sha, addr))
            elif addr not in allowed:
                bad.append((sha, addr))
    print("addresses:")
    for addr in sorted(seen):
        print("  " + (addr if addr in allowed or addr in exceptions else short(addr)))
    for addr, commits in sorted(exceptions.items()):
        print("exception: " + addr + " allowed only on " + ", ".join(sorted(commits)))
    if bad:
        print("FAIL: %d disallowed address use(s)" % len(bad))
        for sha, addr in sorted(set(bad)):
            print("  commit %s address %s" % (sha[:12], short(addr)))
        return 1
    print("PASS: %d commits checked" % len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
