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
