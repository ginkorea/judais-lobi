"""The public surface: one entry point that dispatches on an operation name."""

from core import add


def compute(op, a, b):
    """Apply the named operation to two numbers.

    Raises ``ValueError`` for an operation this module does not know.
    """
    if op == "add":
        return add(a, b)
    raise ValueError(f"unknown operation: {op}")
