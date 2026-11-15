"""Make repository-controlled text safe to show in a public check summary."""
import hashlib
import re

_UNSAFE = re.compile(r"[^A-Za-z0-9._/@+ \-\[\]]")


def _has_needle(text, needles):
    return any(n and n in text for n in needles)


def sanitize_path(path, needles):
    """Replace any needle inside a path, then drop every character that could
    break Markdown or carry control codes. If the original or the result still
    contains a needle (the replacement text or the character mapping can form
    one), return an opaque label instead. Never returns text containing a needle."""
    clean = path
    for n in sorted(needles, key=len, reverse=True):
        if n:
            clean = clean.replace(n, "[redacted]")
    clean = _UNSAFE.sub("?", clean)
    if _has_needle(path, needles) or _has_needle(clean, needles):
        return "file-" + hashlib.sha256(path.encode("utf-8", "replace")).hexdigest()[:12]
    return clean
