# tests/conformance/__init__.py — so this repository can import its own template
#
# A platform copying the kit does NOT need this file: `conftest.py` and
# `test_conformance.py` are the two files `README.md` names, and pytest imports
# them out of any directory. It exists because judais-lobi's own
# `tests/test_conformance_kit.py` imports the template as a module — to hold
# its `CONFORMANCE` dict against `core.runtime.contract` and to exercise the
# pin comparison's branches — and `tests/` is already a package, so a
# sub-package is how that import is spelled.
