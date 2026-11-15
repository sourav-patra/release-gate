import os
import subprocess
import sys
import tomllib

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE = os.path.join(ROOT, "gate")
OK = "owner@noreply.test"
BOT = "bot@noreply.test"
STRANGER = "stranger@noreply.test"


def py(script, *args):
    return subprocess.run([sys.executable, os.path.join(ROOT, script), *args],
                          capture_output=True, text=True)


def commit(repo, email, msg="c"):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL=email,
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL=email)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", msg],
                   check=True, env=env)
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    return r


def cfg(tmp_path, commits=()):
    p = tmp_path / "cfg.toml"
    text = 'allowed_emails = ["%s"]\n' % OK
    if commits is not None:
        quoted = ", ".join('"%s"' % c for c in commits)
        text += '[[exceptions]]\nemail = "%s"\ncommits = [%s]\n' % (BOT, quoted)
    p.write_text(text)
    return str(p)


def test_identity_pass(repo, tmp_path):
    commit(repo, OK)
    r = py("gate/identity_check.py", "--repo", str(repo), "--config", cfg(tmp_path))
    assert r.returncode == 0, r.stdout


def test_identity_unknown_address_fails_and_is_not_printed(repo, tmp_path):
    commit(repo, OK)
    commit(repo, STRANGER)
    r = py("gate/identity_check.py", "--repo", str(repo), "--config", cfg(tmp_path))
    assert r.returncode == 1
    assert STRANGER not in r.stdout + r.stderr


def test_identity_exception_only_on_listed_commit(repo, tmp_path):
    first = commit(repo, BOT)
    c = cfg(tmp_path, [first])
    assert py("gate/identity_check.py", "--repo", str(repo), "--config", c).returncode == 0
    commit(repo, BOT, "second")
    assert py("gate/identity_check.py", "--repo", str(repo), "--config", c).returncode == 1


def test_identity_bad_repo_is_usage_error(tmp_path):
    r = py("gate/identity_check.py", "--repo", str(tmp_path / "nope"), "--config", cfg(tmp_path))
    assert r.returncode == 2


@pytest.fixture
def tree(tmp_path):
    t = tmp_path / "t"
    (t / ".git").mkdir(parents=True)
    (t / ".git" / "ignored.txt").write_text("zebrafish\n")
    (t / "a.txt").write_text("hello\nsee zebrafish here\nzebrafish again\n")
    (t / "bin.dat").write_bytes(b"\0zebrafish")
    (t / "clean.txt").write_text("nothing\n")
    return t


def lists(tmp_path, needles="zebrafish\n", accepted=""):
    n, a = tmp_path / "needles.txt", tmp_path / "accepted.txt"
    n.write_text(needles)
    a.write_text(accepted)
    return ["--needles", str(n), "--accepted", str(a)]


def test_needles_no_match(tmp_path, tree):
    r = py("gate/needles_scan.py", "--target", str(tree), *lists(tmp_path, "quokka\n"))
    assert r.returncode == 0


def test_needles_match_prints_path_and_count_only(tmp_path, tree):
    r = py("gate/needles_scan.py", "--target", str(tree), *lists(tmp_path))
    assert r.returncode == 1
    assert "a.txt 2" in r.stdout
    assert "bin.dat" not in r.stdout and "ignored" not in r.stdout


def test_needles_output_never_contains_needle_or_line(tmp_path, tree):
    r = py("gate/needles_scan.py", "--target", str(tree), *lists(tmp_path))
    out = r.stdout + r.stderr
    assert "zebrafish" not in out
    assert "see " not in out and "again" not in out


def test_needles_accepted_line_is_suppressed(tmp_path, tree):
    acc = "./a.txt:see zebrafish here\n"
    r = py("gate/needles_scan.py", "--target", str(tree), *lists(tmp_path, accepted=acc))
    assert "a.txt 1" in r.stdout and r.returncode == 1
    acc += "./a.txt:zebrafish again\n"
    r = py("gate/needles_scan.py", "--target", str(tree), *lists(tmp_path, accepted=acc))
    assert r.returncode == 0


@pytest.mark.parametrize("needles", ["", "\n\n"])
def test_needles_empty_is_error(tmp_path, tree, needles):
    r = py("gate/needles_scan.py", "--target", str(tree), *lists(tmp_path, needles))
    assert r.returncode == 2


def test_needles_missing_file_is_error(tmp_path, tree):
    r = py("gate/needles_scan.py", "--target", str(tree), "--needles",
           str(tmp_path / "none"), "--accepted", str(tmp_path / "none"))
    assert r.returncode == 2


def test_run_gate_summary_is_clean(tmp_path, repo):
    import shutil
    if not shutil.which("gitleaks"):
        pytest.skip("gitleaks not installed")
    (repo / "f.txt").write_text("harmless zebrafish\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    commit(repo, OK)
    out = tmp_path / "summary.md"
    r = py("gate/run_gate.py", "--target", str(repo), "--config", cfg(tmp_path),
           *lists(tmp_path), "--summary", str(out))
    text = out.read_text(encoding="utf-8")
    assert r.returncode == 1
    assert "needles: FAIL" in text and "identity: pass" in text
    assert "zebrafish" not in text


def test_apply_rules_dry_run_prints_calls():
    r = py("tools/apply_rules.py", "--repo", "o/r", "--gate-app-id", "1", "--owner-id", "2")
    assert r.returncode == 0
    assert r.stdout.count("gh api") == 4
    assert "dry run" in r.stdout


def test_config_examples_parse():
    for name in ("release-gate.toml", "cerebrollm.toml"):
        with open(os.path.join(ROOT, "examples", name), "rb") as f:
            assert "allowed_emails" in tomllib.load(f)


def _gate_modules():
    sys.path.insert(0, os.path.join(ROOT, "gate"))
    import run_gate
    import safe
    return run_gate, safe


def test_sanitize_needle_inside_redacted_marker_gives_opaque_label():
    _, safe = _gate_modules()
    out = safe.sanitize_path("dir/zebrafish.txt", ["zebrafish", "dact"])
    assert out.startswith("file-") and "dact" not in out and "zebrafish" not in out


def test_sanitize_char_mapping_cannot_form_a_needle():
    _, safe = _gate_modules()
    out = safe.sanitize_path("a\x01b", ["a?b"])
    assert out.startswith("file-") and "a?b" not in out


def test_sanitize_clean_path_is_kept():
    _, safe = _gate_modules()
    assert safe.sanitize_path("src/ok.py", ["zebrafish"]) == "src/ok.py"


def test_unreadable_or_empty_needles_show_no_paths(tmp_path, monkeypatch):
    run_gate, _ = _gate_modules()
    assert run_gate.read_needles(str(tmp_path / "missing")) is None
    empty = tmp_path / "empty"
    empty.write_text("\n")
    assert run_gate.read_needles(str(empty)) is None

    def fake_run(cmd, **kw):
        report = cmd[cmd.index("--report-path") + 1]
        with open(report, "w") as f:
            f.write('[{"File": "%s/secret-name.txt"}]' % str(tmp_path).replace("\\", "/"))
        return subprocess.CompletedProcess(cmd, 1, "", "")
    monkeypatch.setattr(run_gate.subprocess, "run", fake_run)
    ok, text = run_gate.gitleaks_summary("gl", str(tmp_path), None)
    assert not ok and "secret-name" not in text and "total 1 in 1 file(s)" in text


def test_run_gate_exits_2_when_needles_unreadable(tmp_path, repo, monkeypatch, capsys):
    run_gate, _ = _gate_modules()
    monkeypatch.setattr(run_gate.shutil, "which", lambda _: None)
    rc = run_gate.main(["--target", str(repo), "--config", cfg(tmp_path),
                        "--needles", str(tmp_path / "missing"),
                        "--accepted", str(tmp_path / "missing")])
    assert rc == 2
