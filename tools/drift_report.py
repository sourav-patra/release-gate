"""Read-only drift report: live rulesets and environment vs rules/rules.toml.

Usage: drift_report.py --repo OWNER/NAME --gate-app-id N --owner-id N
Only GET requests are made (through the gh CLI). Exit: 0 no drift, 1 drift,
2 error. Agents may run this; it changes nothing.
"""
import argparse
import json
import os
import subprocess
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import apply_rules  # noqa: E402


def fetch(path):
    p = subprocess.run(["gh", "api", "-X", "GET", path], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("gh api failed for " + path.split("?")[0])
    return json.loads(p.stdout)


def rule_map(rules):
    return {r["type"]: r.get("parameters", {}) for r in rules}


def checks_of(params):
    return {(c["context"], c.get("integration_id"))
            for c in params.get("required_status_checks", [])}


def diff_ruleset(exp, live):
    out = []
    n = exp["name"]
    for k in ("target", "enforcement"):
        if live.get(k) != exp[k]:
            out.append("%s: %s is %r, expected %r" % (n, k, live.get(k), exp[k]))
    want_inc = exp["conditions"]["ref_name"]["include"]
    inc = live.get("conditions", {}).get("ref_name", {}).get("include", [])
    if sorted(inc) != sorted(want_inc):
        out.append("%s: ref include %r, expected %r" % (n, inc, want_inc))
    want_exc = exp["conditions"]["ref_name"].get("exclude", [])
    exc = live.get("conditions", {}).get("ref_name", {}).get("exclude", [])
    if sorted(exc) != sorted(want_exc):
        out.append("%s: ref exclude %r, expected %r" % (n, exc, want_exc))
    e, l = rule_map(exp["rules"]), rule_map(live.get("rules", []))
    for t in sorted(set(e) - set(l)):
        out.append("%s: missing rule %s" % (n, t))
    for t in sorted(set(l) - set(e)):
        out.append("%s: unexpected rule %s" % (n, t))
    if "required_status_checks" in e and "required_status_checks" in l:
        want, have = checks_of(e["required_status_checks"]), checks_of(l["required_status_checks"])
        if want != have:
            out.append("%s: required checks %s, expected %s"
                       % (n, sorted(have, key=str), sorted(want, key=str)))
    if "pull_request" in e and "pull_request" in l:
        a = e["pull_request"].get("required_approving_review_count")
        b = l["pull_request"].get("required_approving_review_count")
        if a != b:
            out.append("%s: required approvals %r, expected %r" % (n, b, a))

    def bypass(d):
        return sorted((b["actor_id"], b["actor_type"], b["bypass_mode"])
                      for b in d.get("bypass_actors", []))
    if bypass(exp) != bypass(live):
        out.append("%s: bypass actors %s, expected %s" % (n, bypass(live), bypass(exp)))
    return out


def diff_environment(exp, live):
    out = []
    want_custom = exp["deployment_branch_policy"]["custom_branch_policies"]
    if live.get("deployment_branch_policy", {}).get("custom_branch_policies") != want_custom:
        out.append("environment: custom branch policies differ")
    rr = [r for r in live.get("protection_rules", []) if r.get("type") == "required_reviewers"]
    want_ids = sorted((r["type"], r["id"]) for r in exp["reviewers"])
    have_ids = sorted((x.get("type"), x["reviewer"]["id"])
                      for r in rr for x in r.get("reviewers", []))
    if want_ids != have_ids:
        out.append("environment: reviewers %s, expected %s" % (have_ids, want_ids))
    live_self = bool(rr and rr[0].get("prevent_self_review"))
    if live_self != bool(exp["prevent_self_review"]):
        out.append("environment: prevent_self_review is %r, expected %r"
                   % (live_self, bool(exp["prevent_self_review"])))
    return out


def report(repo, gate_app_id, owner_id, rules_path, get=None):
    get = get or fetch  # resolved at call time so tests can replace fetch
    with open(rules_path, "rb") as f:
        rules = tomllib.load(f)
    (_, _, main_p), (_, _, tag_p), (_, _, env_p), (_, _, pol_p) = apply_rules.build_calls(
        rules, repo, gate_app_id, owner_id)
    live_list = {r["name"]: r["id"] for r in get("/repos/%s/rulesets" % repo)}
    out = []
    for exp in (main_p, tag_p):
        if exp["name"] not in live_list:
            out.append("%s: ruleset missing" % exp["name"])
            continue
        out += diff_ruleset(exp, get("/repos/%s/rulesets/%d" % (repo, live_list[exp["name"]])))
    env_name = rules["environment"]["name"]
    try:
        live_env = get("/repos/%s/environments/%s" % (repo, env_name))
    except RuntimeError:
        out.append("environment %s: missing" % env_name)
        return out
    out += diff_environment(env_p, live_env)
    pols = get("/repos/%s/environments/%s/deployment-branch-policies" % (repo, env_name))
    have = {(p["name"], p.get("type")) for p in pols.get("branch_policies", [])}
    want = {(pol_p["name"], pol_p["type"])}
    if have != want:
        out.append("environment: deployment policies %s, expected %s"
                   % (sorted(have, key=str), sorted(want, key=str)))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--gate-app-id", type=int, required=True)
    ap.add_argument("--owner-id", type=int, required=True)
    ap.add_argument("--rules", default=apply_rules.RULES)
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 2
    try:
        diffs = report(a.repo, a.gate_app_id, a.owner_id, a.rules)
    except (OSError, RuntimeError, KeyError, ValueError) as e:
        print("error: " + type(e).__name__)
        return 2
    for d in diffs:
        print("DRIFT " + d)
    print("drift: %d difference(s)" % len(diffs) if diffs else "no drift")
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main())
