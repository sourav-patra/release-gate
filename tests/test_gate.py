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


def test_exceptions_entry_with_extra_keys_is_a_config_error(repo, tmp_path):
    commit(repo, OK)
    p = tmp_path / "bad.toml"
    p.write_text('allowed_emails = ["%s"]\n[[exceptions]]\nemail = "%s"\ncommits = []\n'
                 'build = "python -m build"\n' % (OK, BOT))
    r = py("gate/identity_check.py", "--repo", str(repo), "--config", str(p))
    assert r.returncode == 2


def test_cerebrollm_example_keeps_build_and_smoke_top_level():
    with open(os.path.join(ROOT, "examples", "cerebrollm.toml"), "rb") as f:
        cfg = tomllib.load(f)
    assert cfg["build"] == "python -m build" and cfg["smoke"] == ["cerebrollm --help"]
    assert set(cfg["exceptions"][0]) == {"email", "commits"}
