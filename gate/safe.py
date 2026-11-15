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
        digest = hashlib.sha256(path.encode("utf-8", "replace")).hexdigest()
        # The label itself may collide with a short needle: try other slices,
        # then show nothing at all.
        for start in (0, 12, 24, 36, 48):
            label = "file-" + digest[start:start + 12]
            if not _has_needle(label, needles):
                return label
        return ""
    return clean


def guard_text(text, needles, fallbacks=("output withheld", "")):
    """Final check on any text about to be published. Returns (text, withheld).
    If the text contains a needle, a fallback that contains none replaces it."""
    if not _has_needle(text, needles):
        return text, False
    for fb in fallbacks:
        if not _has_needle(fb, needles):
            return fb, True
    return "", True
