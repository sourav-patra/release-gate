"""Run the gate checks and write a Markdown summary.

Checks: gitleaks, identity, needles, and (only with --run-build) the build
and smoke steps named in the config. The build step runs the target's own
build backend, so the scheduled gate never passes --run-build; the publish
workflow does, on a tagged commit.
Exit non-zero if any check fails.
"""
import argparse
import os
import shlex
import shutil
import subprocess
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))


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

    if gl:
        rc, out = run([gl, "dir", a.target, "--redact", "--no-banner"])
        results.append(("gitleaks", rc == 0, out[-4000:]))
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
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
