"""Round-2 review of PR 7: no output may contain a needle, and an unusable
NEEDLES file fails the gate with no paths shown."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gate"))
import run_gate  # noqa: E402
import safe  # noqa: E402


def test_sanitize_needle_inside_redacted_marker_gives_opaque_label():
    out = safe.sanitize_path("dir/zebrafish.txt", ["zebrafish", "dact"])
    assert out.startswith("file-") and "dact" not in out and "zebrafish" not in out


def test_sanitize_char_mapping_cannot_form_a_needle():
    out = safe.sanitize_path("a\x01b", ["a?b"])
    assert out.startswith("file-") and "a?b" not in out


def test_sanitize_clean_path_is_kept():
    assert safe.sanitize_path("src/ok.py", ["zebrafish"]) == "src/ok.py"


def test_unreadable_or_empty_needles_show_no_paths(tmp_path, monkeypatch):
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


def test_run_gate_exits_2_when_needles_unreadable(tmp_path, monkeypatch):
    monkeypatch.setattr(run_gate.shutil, "which", lambda _: None)
    cfg = tmp_path / "c.toml"
    cfg.write_text("")
    rc = run_gate.main(["--target", str(tmp_path), "--config", str(cfg),
                        "--needles", str(tmp_path / "missing"),
                        "--accepted", str(tmp_path / "missing"),
                        "--summary", str(tmp_path / "s.md")])
    assert rc == 2


def test_fallback_label_never_contains_a_needle():
    out = safe.sanitize_path("file.txt", ["file"])
    assert "file" not in out
    out = safe.sanitize_path("x/zebrafish", ["zebrafish", "file-", "0", "1", "2", "3", "4", "5", "6",
                                              "7", "8", "9", "a", "b", "c", "d", "e", "f"])
    assert out == ""


def test_guard_text_replaces_text_holding_a_needle():
    assert safe.guard_text("fine", ["zebra"]) == ("fine", False)
    assert safe.guard_text("has zebra", ["zebra"]) == ("output withheld", True)
    assert safe.guard_text("has zebra", ["zebra", "withheld"]) == ("", True)


def test_summary_with_generated_text_matching_a_needle_is_withheld(tmp_path, monkeypatch):
    # needle "total" equals words the gate itself prints, so the summary is replaced
    needles = tmp_path / "n.txt"
    needles.write_text("total\n")
    empty = tmp_path / "a.txt"
    empty.write_text("")
    cfg = tmp_path / "c.toml"
    cfg.write_text("")

    def fake_run(cmd, **kw):
        if "--report-path" in cmd:
            report = cmd[cmd.index("--report-path") + 1]
            with open(report, "w") as f:
                f.write('[{"File": "%s/x.txt"}]' % str(tmp_path).replace("\\", "/"))
            return subprocess.CompletedProcess(cmd, 1, "", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(run_gate.subprocess, "run", fake_run)
    out = tmp_path / "s.md"
    rc = run_gate.main(["--target", str(tmp_path), "--config", str(cfg), "--needles", str(needles),
                        "--accepted", str(empty), "--gitleaks", "gl", "--summary", str(out)])
    text = out.read_text(encoding="utf-8")
    assert rc == 1 and "total" not in text and text == "output withheld"


def test_empty_needles_with_gitleaks_enabled_exits_2_and_shows_no_path(tmp_path, monkeypatch):
    needles = tmp_path / "n.txt"
    needles.write_text("\n")
    cfg = tmp_path / "c.toml"
    cfg.write_text("")

    def fake_run(cmd, **kw):
        report = cmd[cmd.index("--report-path") + 1] if "--report-path" in cmd else None
        if report:
            with open(report, "w") as f:
                f.write('[{"File": "%s/secret-name.txt"}]' % str(tmp_path).replace("\\", "/"))
        return subprocess.CompletedProcess(cmd, 1 if report else 0, "", "")
    monkeypatch.setattr(run_gate.subprocess, "run", fake_run)
    out = tmp_path / "s.md"
    rc = run_gate.main(["--target", str(tmp_path), "--config", str(cfg), "--needles", str(needles),
                        "--accepted", str(needles), "--gitleaks", "gl", "--summary", str(out)])
    assert rc == 2 and "secret-name" not in out.read_text(encoding="utf-8")


def _scan(tmp_path, needles, files):
    t = tmp_path / "t"
    t.mkdir()
    for name, body in files.items():
        (t / name).write_text(body)
    n, a = tmp_path / "n.txt", tmp_path / "a.txt"
    n.write_text(needles)
    a.write_text("")
    return subprocess.run([sys.executable, os.path.join(ROOT, "gate", "needles_scan.py"),
                           "--target", str(t), "--needles", str(n), "--accepted", str(a)],
                          capture_output=True, text=True)


def test_scanner_count_cannot_form_a_needle(tmp_path):
    r = _scan(tmp_path, "note.txt 1\nzebra\n", {"note.txt": "zebra\n"})
    assert "note.txt 1" not in r.stdout + r.stderr
    assert r.returncode == 1


def test_scanner_boilerplate_word_matching_a_needle_is_withheld(tmp_path):
    r = _scan(tmp_path, "total\nzebra\n", {"ok.txt": "zebra\n"})
    assert "total" not in r.stdout and r.returncode == 1


def test_unusable_list_runs_no_other_check_and_publishes_a_fixed_notice(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no subprocess may run when the private list is unusable")
    monkeypatch.setattr(run_gate.subprocess, "run", boom)
    out = tmp_path / "s.md"
    rc = run_gate.main(["--target", str(tmp_path), "--config", str(tmp_path / "c.toml"),
                        "--needles", str(tmp_path / "missing"), "--accepted", str(tmp_path / "missing"),
                        "--gitleaks", "gl", "--run-build", "--summary", str(out)])
    assert rc == 2
    assert "unreadable or empty" in out.read_text(encoding="utf-8")
