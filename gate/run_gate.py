"""Run the gate checks and write a Markdown summary.

Checks: gitleaks, identity, needles, and (only with --run-build) the build
and smoke steps named in the config. The build step runs the target's own
build backend, so the scheduled gate never passes --run-build; the publish
workflow does, on a tagged commit.
Raw gitleaks output is never shown: only file paths and counts.
Exit non-zero if any check fails.
"""
import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from safe import sanitize_path  # noqa: E402


def gitleaks_summary(gl, target, needles):
    """Run gitleaks; return (ok, text) built from its JSON report."""
    with tempfile.TemporaryDirectory() as tmp:
        report = os.path.join(tmp, "r.json")
        p = subprocess.run([gl, "dir", target, "--redact", "--no-banner",
                            "--report-format", "json", "--report-path", report],
                           capture_output=True, text=True)
        if p.returncode == 0:
            return True, "no leaks found"
        if p.returncode != 1:
            return False, "gitleaks error (exit %d)" % p.returncode
        try:
            with open(report, encoding="utf-8") as f:
                findings = json.load(f)
        except (OSError, ValueError):
            return False, "gitleaks reported leaks; report unreadable"
    counts = {}
    for item in findings:
        name = item.get("File", "")
        rel = os.path.relpath(name, target).replace(os.sep, "/") if name else "?"
        counts[rel] = counts.get(rel, 0) + 1
    if needles is None:  # private list unreadable: no path is safe to show
        lines = []
    else:
        lines = ["%s %d" % (sanitize_path(r, needles), c) for r, c in sorted(counts.items())]
    lines.append("total %d in %d file(s)" % (len(findings), len(counts)))
    return False, "\n".join(lines)


def read_needles(path):
    try:
        with open(path, "rb") as f:
            raw = f.read().decode("utf-8", "replace").split("\n")
    except OSError:
        return None
    needles = [n.rstrip("\r") for n in raw if n.rstrip("\r")]
    return needles or None  # unreadable or empty is an error, never "no needles"


def run(cmd, cwd=None):
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return p.returncode, (p.stdout + p.stderr).strip()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--needles", required=True)
    ap.add_argument("--accepted", required=True)
    ap.add_argument("--gitleaks", default=None)
    ap.add_argument("--summary", default=None, help="write Markdown here")
    ap.add_argument("--run-build", action="store_true")
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 2
    gl = a.gitleaks or shutil.which("gitleaks")
    results = []  # (name, ok, text)

    needles = read_needles(a.needles)
    if gl:
        ok, text = gitleaks_summary(gl, a.target, needles)
        results.append(("gitleaks", ok, text))
    else:
        results.append(("gitleaks", False, "gitleaks binary not found"))

    rc, out = run([sys.executable, os.path.join(HERE, "identity_check.py"),
                   "--repo", a.target, "--config", a.config])
    results.append(("identity", rc == 0, out))

    rc, out = run([sys.executable, os.path.join(HERE, "needles_scan.py"),
                   "--target", a.target, "--needles", a.needles,
                   "--accepted", a.accepted])
    results.append(("needles", rc == 0, out))

    if a.run_build:
        try:
            with open(a.config, "rb") as f:
                cfg = tomllib.load(f)
            steps = ([cfg["build"]] if cfg.get("build") else []) + list(cfg.get("smoke", []))
            ok, log = True, []
            for s in steps:
                rc, out = run(shlex.split(s), cwd=a.target)
                log.append("$ %s -> %d" % (s, rc))
                if rc != 0:
                    ok = False
                    log.append(out[-2000:])
                    break
            results.append(("build", ok, "\n".join(log) or "no build step configured"))
        except (OSError, tomllib.TOMLDecodeError) as e:
            results.append(("build", False, "config error: " + type(e).__name__))

    lines = ["# release-gate", ""]
    for name, ok, text in results:
        lines += ["## %s: %s" % (name, "pass" if ok else "FAIL"), "", "```", text, "```", ""]
    md = "\n".join(lines)
    if a.summary:
        with open(a.summary, "w", encoding="utf-8") as f:
            f.write(md)
    else:
        print(md)
    if needles is None:
        return 2  # same code the needles scan uses for an unusable list
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
