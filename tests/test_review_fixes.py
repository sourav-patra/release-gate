"""Regression tests for the independent review of 2026-11-15."""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gate"))
import run_gate  # noqa: E402
import safe  # noqa: E402
import scan_repos  # noqa: E402


def py(script, *args):
    return subprocess.run([sys.executable, os.path.join(ROOT, script), *args],
                          capture_output=True, text=True)


def test_sanitize_path_hides_needles_and_markup():
    out = safe.sanitize_path("dir/zebrafish-notes`\n```x|y.md", ["zebrafish"])
    assert "zebrafish" not in out
    assert "\n" not in out and "`" not in out and "|" not in out
    assert out.startswith("file-")  # a path holding a needle becomes an opaque label


def test_needle_in_filename_is_not_printed(tmp_path):
    t = tmp_path / "t"
    t.mkdir()
    (t / "zebrafish-plan.txt").write_text("zebrafish inside\n")
    n, a = tmp_path / "n.txt", tmp_path / "a.txt"
    n.write_text("zebrafish\n")
    a.write_text("")
    r = py("gate/needles_scan.py", "--target", str(t), "--needles", str(n), "--accepted", str(a))
    assert r.returncode == 1
    assert "zebrafish" not in r.stdout + r.stderr
    assert "file-" in r.stdout and "-plan.txt" not in r.stdout


def test_gitleaks_summary_shows_only_paths_and_counts(tmp_path, monkeypatch):
    target = str(tmp_path / "t")
    os.makedirs(target)

    class Done:
        returncode = 1
        stdout = "Finding: SECRETTEXT Line: 7"
        stderr = "SECRETTEXT"

    def fake_run(cmd, **kw):
        report = cmd[cmd.index("--report-path") + 1]
        with open(report, "w") as f:
            json.dump([{"File": os.path.join(target, "a", "zebrafish.txt"),
                        "Match": "SECRETTEXT", "StartLine": 7},
                       {"File": os.path.join(target, "a", "zebrafish.txt"), "Match": "SECRETTEXT"}], f)
        return Done()
    monkeypatch.setattr(run_gate.subprocess, "run", fake_run)
    ok, text = run_gate.gitleaks_summary("gl", target, ["zebrafish"])
    assert ok is False
    assert "SECRETTEXT" not in text and "zebrafish" not in text and "StartLine" not in text and ":7" not in text
    assert text.startswith("file-") and "total 2 in 1 file(s)" in text
    assert "file-" in text and "total 2 in 1 file(s)" in text


def test_identity_empty_history_is_an_error_not_a_pass(tmp_path):
    r = tmp_path / "empty"
    r.mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    cfg = tmp_path / "c.toml"
    cfg.write_text('allowed_emails = ["x@noreply.test"]\n')
    out = py("gate/identity_check.py", "--repo", str(r), "--config", str(cfg))
    assert out.returncode == 2


def test_has_check_requires_completed_check_from_gate_app(monkeypatch):
    seen = []

    def fake_api(method, path, token, body=None):
        seen.append(path)
        return {"total_count": 0}
    monkeypatch.setattr(scan_repos, "api", fake_api)
    monkeypatch.setenv("GATE_APP_ID", "123")
    assert scan_repos.has_check("o/r", "f" * 40, "t") is False
    assert "status=completed" in seen[0] and "app_id=123" in seen[0]
