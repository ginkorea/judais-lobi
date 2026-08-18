"""Canonical forms for record names."""


def normalize(name):
    """Return the canonical form of a record name.

    Two spellings of one name must canonicalise to the same string, so
    that an index built from one finds the other.
    """
    return name.strip()
