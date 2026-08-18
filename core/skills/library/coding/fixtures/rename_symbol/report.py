"""Row-count reports."""

from util import fmt_msg


def report(rows):
    """A one-line report of how many rows were seen."""
    return fmt_msg("report", f"{len(rows)} row(s)")
