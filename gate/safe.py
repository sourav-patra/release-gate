"""Make repository-controlled text safe to show in a public check summary."""
import re

_UNSAFE = re.compile(r"[^A-Za-z0-9._/@+ \-\[\]]")


def sanitize_path(path, needles):
    """Replace any needle inside a path, then drop every character that could
    break Markdown or carry control codes. A path never discloses a needle."""
    for n in sorted(needles, key=len, reverse=True):
        if n:
            path = path.replace(n, "[redacted]")
    return _UNSAFE.sub("?", path)
