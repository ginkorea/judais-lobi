"""Message formatting shared by every surface in this package."""


def fmt_msg(subject, body):
    """Return one formatted line: a bracketed subject, then the body."""
    return f"[{subject}] {body}"
