# core/eval/__main__.py — `python -m core.eval`

"""The entry point, so the harness is reachable without an installed script.

A console script would be a second name to keep in step with `setup.py`, and
this is a developer's and a CI job's tool rather than an operator's.
"""

import sys

from core.eval.run import main

if __name__ == "__main__":       # pragma: no cover - exercised as a subprocess
    sys.exit(main())
