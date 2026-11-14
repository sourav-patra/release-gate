"""Print (default) or apply the rules in rules/rules.toml to one repository.

Usage:
  apply_rules.py --repo OWNER/NAME --gate-app-id N --owner-id N          # dry run
  apply_rules.py --repo OWNER/NAME --gate-app-id N --owner-id N --apply  # owner only

Dry run prints the `gh api` calls. Agents run only the dry run.
Uses the gh CLI signed in as the owner when applying.
"""
import argparse
import json
import os
import subprocess
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, "..", "rules", "rules.toml")


def build_calls(rules, repo, gate_app_id, owner_id):
    m, t, e = rules["main_ruleset"], rules["tag_ruleset"], rules["environment"]
    main_rules = []
    if m.get("require_pull_request"):
        main_rules.append({"type": "pull_request", "parameters": {
            "required_approving_review_count": m["approvals"],
            "dismiss_stale_reviews_on_push": False,
            "require_code_owner_review": False,
            "require_last_push_approval": False,
            "required_review_thread_resolution": False}})
    main_rules.append({"type": "required_status_checks", "parameters": {
        "strict_required_status_checks_policy": False,
        "required_status_checks": [
            {"context": m["required_check"], "integration_id": gate_app_id}]}})
    if m.get("block_force_push"):
        main_rules.append({"type": "non_fast_forward"})
    if m.get("block_deletion"):
        main_rules.append({"type": "deletion"})
    tag_rules = []
    if t.get("block_update"):
        tag_rules.append({"type": "update"})
    if t.get("block_deletion"):
        tag_rules.append({"type": "deletion"})
    bypass = [{"actor_id": m["bypass_role_id"], "actor_type": "RepositoryRole",
               "bypass_mode": "always"}]
    env = {"deployment_branch_policy": {"protected_branches": False,
                                        "custom_branch_policies": True},
           "prevent_self_review": e["prevent_self_review"],
           "reviewers": [{"type": "User", "id": owner_id}] if e["owner_is_reviewer"] else []}
    return [
        ("POST", "/repos/%s/rulesets" % repo, {
            "name": m["name"], "target": "branch", "enforcement": "active",
            "conditions": {"ref_name": {"include": [m["branch"]], "exclude": []}},
            "rules": main_rules, "bypass_actors": bypass}),
        ("POST", "/repos/%s/rulesets" % repo, {
            "name": t["name"], "target": "tag", "enforcement": "active",
            "conditions": {"ref_name": {"include": [t["pattern"]], "exclude": []}},
            "rules": tag_rules, "bypass_actors": bypass}),
        ("PUT", "/repos/%s/environments/%s" % (repo, e["name"]), env),
        ("POST", "/repos/%s/environments/%s/deployment-branch-policies" % (repo, e["name"]),
         {"name": e["tag_pattern"], "type": "tag"}),
    ]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--gate-app-id", type=int, required=True)
    ap.add_argument("--owner-id", type=int, required=True)
    ap.add_argument("--rules", default=RULES)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    with open(a.rules, "rb") as f:
        rules = tomllib.load(f)
    for method, path, body in build_calls(rules, a.repo, a.gate_app_id, a.owner_id):
        text = json.dumps(body)
        if not a.apply:
            print("gh api -X %s %s --input - <<< '%s'" % (method, path, text))
            continue
        p = subprocess.run(["gh", "api", "-X", method, path, "--input", "-"],
                           input=text, text=True, capture_output=True)
        print("%s %s -> %s" % (method, path, "ok" if p.returncode == 0 else "FAILED: " + p.stderr.strip()))
        if p.returncode != 0:
            return 1
    if not a.apply:
        print("dry run: nothing changed. The owner adds --apply to make these calls.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
