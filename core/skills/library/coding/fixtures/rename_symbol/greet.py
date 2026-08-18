"""Greetings."""

from util import fmt_msg


def greeting(name):
    """A greeting line for *name*."""
    return fmt_msg("greeting", f"hello, {name}")
