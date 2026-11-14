"""scan_repos against a fake GitHub API: no network, no real clone."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gate"))
import scan_repos  # noqa: E402

CFG = 'allowed_emails = ["x@noreply.test"]\n'
SHA_PR_NEW, SHA_PR_DONE, SHA_TAG = "a" * 40, "b" * 40, "c" * 40


class World:
    """A fake installation: repo 'o/plain' has no config, 'o/opted' has one."""

    def __init__(self):
        self.git_calls = []
        self.posts = []
        self.printed = []

    def paged(self, path, token, key=None):
        if path == "/installation/repositories":
            return [{"full_name": "o/plain"}, {"full_name": "o/opted"}]
        if "/pulls" in path:
            repo = path.split("/")[2] + "/" + path.split("/")[3]
            if repo == "o/plain":
                return [{"number": 9, "head": {"sha": "d" * 40}}]
            return [{"number": 1, "head": {"sha": SHA_PR_NEW}},
                    {"number": 2, "head": {"sha": SHA_PR_DONE}}]
        if "matching-refs" in path:
            return [{"ref": "refs/tags/v1.0.0", "object": {"type": "commit", "sha": SHA_TAG}}]
        raise AssertionError("unexpected path " + path)

    def api(self, method, path, token, body=None):
        if method == "GET" and "check-runs" in path:
            done = SHA_PR_DONE in path
            return {"total_count": 1 if done else 0}
        if method == "POST" and path.endswith("/check-runs"):
            self.posts.append((path, body["head_sha"], body["conclusion"]))
            return {}
        raise AssertionError("unexpected call %s %s" % (method, path))


@pytest.fixture
def world(monkeypatch):
    w = World()
    monkeypatch.setenv("GH_TOKEN", "fake-token")
    monkeypatch.setenv("NEEDLES_FILE", "n")
    monkeypatch.setenv("ACCEPTED_FILE", "a")
    monkeypatch.setattr(scan_repos, "paged", w.paged)
    monkeypatch.setattr(scan_repos, "api", w.api)
    monkeypatch.setattr(scan_repos, "config_text",
                        lambda repo, token: CFG if repo == "o/opted" else None)

    def fake_git(args, cwd, token):
        w.git_calls.append((args[0], args[-1] if args[0] == "remote" else ""))
        return ""
    monkeypatch.setattr(scan_repos, "git", fake_git)

    class Done:
        returncode = 0

    def fake_run(cmd, *a, **k):  # stands in for run_gate.py
        with open(cmd[cmd.index("--summary") + 1], "w", encoding="utf-8") as f:
            f.write("ok")
        return Done()
    monkeypatch.setattr(scan_repos.subprocess, "run", fake_run)

    def fake_print(*args, **kwargs):
        w.printed.append((" ".join(str(a) for a in args), kwargs))
    monkeypatch.setattr(scan_repos, "print", fake_print, raising=False)
    return w


def test_repository_without_config_is_never_cloned(world):
    assert scan_repos.main([]) == 0
    remotes = [u for name, u in world.git_calls if name == "remote"]
    assert remotes and all("o/plain" not in u for u in remotes)
    assert all("o/plain" not in p for p, _, _ in world.posts)


def test_unchecked_heads_scanned_once_and_checked_heads_skipped(world):
    scan_repos.main([])
    posted = sorted(sha for _, sha, _ in world.posts)
    assert posted == sorted([SHA_PR_NEW, SHA_TAG])
    assert SHA_PR_DONE not in posted
    assert sum(1 for name, _ in world.git_calls if name == "init") == 2
    assert all(c == "success" for _, _, c in world.posts)


def test_output_is_flushed_and_reports_counts(world):
    scan_repos.main([])
    assert any("2 installed, 1 opted in" in t for t, _ in world.printed)
    assert world.printed and all(k.get("flush") is True for _, k in world.printed)


def test_manual_dispatch_without_config_is_skipped(world, monkeypatch):
    monkeypatch.setattr(scan_repos, "config_text", lambda repo, token: None)
    assert scan_repos.main(["--repo", "o/plain", "--sha", "e" * 40]) == 0
    assert world.git_calls == [] and world.posts == []
