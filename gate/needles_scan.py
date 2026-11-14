"""Fixed-string private-name scan that never reveals what it matched.

Usage: needles_scan.py --target DIR --needles FILE --accepted FILE

Equivalent to: grep -rIFf NEEDLES . | grep -vxFf ACCEPTED
An ACCEPTED entry is a complete scan line "./<path>:<matched line>".
Prints "<relative path> <count>" per file with unaccepted matches, then a
total. Never prints a needle, a matched line or a line number.
Exit: 0 no match, 1 match, 2 error (empty or unreadable NEEDLES included).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from safe import sanitize_path  # noqa: E402


def read_lines(path):
    with open(path, "rb") as f:
        data = f.read().decode("utf-8", errors="replace")
    return [ln.rstrip("\r") for ln in data.split("\n")]


def scan(target, needles, accepted):
    results = {}
    for root, dirs, files in os.walk(target):
        dirs[:] = sorted(d for d in dirs if d != ".git")
        for name in sorted(files):
            full = os.path.join(root, name)
            if os.path.islink(full):
                continue
            rel = os.path.relpath(full, target).replace(os.sep, "/")
            with open(full, "rb") as f:
                raw = f.read()
            if b"\0" in raw[:8192]:
                continue
            count = 0
            for line in raw.decode("utf-8", errors="replace").split("\n"):
                line = line.rstrip("\r")
                if any(n in line for n in needles):
                    if ("./" + rel + ":" + line) not in accepted:
                        count += 1
            if count:
                results[rel] = count
    return results


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--needles", required=True)
    ap.add_argument("--accepted", required=True)
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return 2
    try:
        needles = [n for n in read_lines(args.needles) if n]
        accepted = {a for a in read_lines(args.accepted) if a}
        if not needles:
            print("error: needles file is empty")
            return 2
        if not os.path.isdir(args.target):
            print("error: target is not a directory")
            return 2
        results = scan(args.target, needles, accepted)
    except OSError as e:
        print("error: " + type(e).__name__)
        return 2
    for rel in sorted(results):
        print("%s %d" % (sanitize_path(rel, needles), results[rel]))
    total = sum(results.values())
    print("total %d in %d file(s)" % (total, len(results)))
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
