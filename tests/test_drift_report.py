"""Drift report against fixtures shaped like the GitHub API (hand-built from
apply_rules payloads, not live captures)."""
import copy
import os
import sys
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import apply_rules  # noqa: E402
import drift_report  # noqa: E402

REPO, GATE, OWNER = "o/r", 11, 22
PATH = "/repos/o/r"


def good_world():
    with open(apply_rules.RULES, "rb") as f:
        rules = tomllib.load(f)
    (_, _, main_p), (_, _, tag_p), _, (_, _, pol_p) = apply_rules.build_calls(
        rules, REPO, GATE, OWNER)
    env_l = {"deployment_branch_policy": {"custom_branch_policies": True,
                                          "protected_branches": False},
             "protection_rules": [
                 {"type": "required_reviewers", "prevent_self_review": True,
                  "reviewers": [{"type": "User", "reviewer": {"id": OWNER}}]},
                 {"type": "branch_policy"}]}
    return {PATH + "/rulesets": [{"id": 1, "name": main_p["name"]},
                                 {"id": 2, "name": tag_p["name"]}],
            PATH + "/rulesets/1": copy.deepcopy(main_p),
            PATH + "/rulesets/2": copy.deepcopy(tag_p),
            PATH + "/environments/pypi": env_l,
            PATH + "/environments/pypi/deployment-branch-policies":
                {"branch_policies": [{"name": pol_p["name"], "type": pol_p["type"]}]}}


def run(world):
    def get(path):
        if path not in world:
            raise RuntimeError("404")
        return copy.deepcopy(world[path])
    return drift_report.report(REPO, GATE, OWNER, apply_rules.RULES, get=get)


def test_no_drift_when_live_matches():
    assert run(good_world()) == []


def test_missing_ruleset_reported():
    w = good_world()
    w[PATH + "/rulesets"] = w[PATH + "/rulesets"][:1]
    assert any("ruleset missing" in d for d in run(w))


def test_wrong_required_check_app_reported():
    w = good_world()
    for r in w[PATH + "/rulesets/1"]["rules"]:
        if r["type"] == "required_status_checks":
            r["parameters"]["required_status_checks"][0]["integration_id"] = 999
    assert any("required checks" in d for d in run(w))


def test_removed_force_push_block_reported():
    w = good_world()
    w[PATH + "/rulesets/1"]["rules"] = [
        r for r in w[PATH + "/rulesets/1"]["rules"] if r["type"] != "non_fast_forward"]
    assert any("missing rule non_fast_forward" in d for d in run(w))


def test_environment_drift_reported():
    w = good_world()
    rule = w[PATH + "/environments/pypi"]["protection_rules"][0]
    rule["prevent_self_review"] = False
    rule["reviewers"] = []
    d = run(w)
    assert any("prevent_self_review" in x for x in d) and any("reviewers" in x for x in d)


def test_missing_environment_reported():
    w = good_world()
    del w[PATH + "/environments/pypi"]
    assert any("missing" in d for d in run(w))


def test_main_error_exit_code(monkeypatch):
    def boom(path):
        raise RuntimeError("x")
    monkeypatch.setattr(drift_report, "fetch", boom)
    assert drift_report.main(["--repo", "o/r", "--gate-app-id", "1", "--owner-id", "2"]) == 2


def test_main_never_writes(monkeypatch):
    seen = []

    def spy(args, **kw):
        seen.append(args)
        raise OSError("blocked")
    monkeypatch.setattr(drift_report.subprocess, "run", spy)
    drift_report.main(["--repo", "o/r", "--gate-app-id", "1", "--owner-id", "2"])
    assert seen and all("GET" in a for a in seen)


def test_excluding_the_protected_branch_is_drift():
    w = good_world()
    w[PATH + "/rulesets/1"]["conditions"]["ref_name"]["exclude"] = ["refs/heads/main"]
    assert any("ref exclude" in d for d in run(w))


def test_extra_deployment_policy_is_drift():
    w = good_world()
    w[PATH + "/environments/pypi/deployment-branch-policies"]["branch_policies"].append(
        {"name": "*", "type": "branch"})
    assert any("deployment policies" in d for d in run(w))


def test_reviewer_type_substitution_is_drift():
    w = good_world()
    w[PATH + "/environments/pypi"]["protection_rules"][0]["reviewers"][0]["type"] = "Team"
    assert any("reviewers" in d for d in run(w))


def test_main_uses_replaced_fetch_and_never_reaches_gh(monkeypatch):
    called = []

    def fake_fetch(path):
        called.append(path)
        raise RuntimeError("x")
    monkeypatch.setattr(drift_report, "fetch", fake_fetch)
    assert drift_report.main(["--repo", "o/r", "--gate-app-id", "1", "--owner-id", "2"]) == 2
    assert called == ["/repos/o/r/rulesets"]
