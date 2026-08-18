"""Build and read an index of record names."""

from records import normalize


def build(names):
    """Index every name by its canonical form.

    The value is the name as it was written, so a caller can report the
    original spelling back.
    """
    return {name.strip(): name for name in names}


def lookup(table, name):
    """Return the original spelling of *name*, or ``None``."""
    return table.get(normalize(name))
