# core/eval/__init__.py — the eval harness: missions in, verdicts out

"""Measure before default.

ROADMAP §3 says nothing becomes on-by-default until the harness scores it
against a held-out set, and until this package there was no harness.  The
August 2026 measurements lived in docstrings, the corpus was one recorded
fabrication file, and three live questions — is ``--swarm`` a better default,
is ``--protocol native`` a better default, should ``reading.py`` become a
grounding tier — had no way to be answered except by somebody's memory of a
demo.

The package is five modules and one rule:

* :mod:`core.eval.suite` — what a mission is, what a flag is, how a suite is
  refused for being ungradeable, and the dated ``RUBRIC_CHANGES`` ledger.
* :mod:`core.eval.stub_suite` — the eleven missions this repository ships,
  over its own MCP stub server, so the harness runs with no GPU and no
  platform.
* :mod:`core.eval.score` — the verdict, computed **only** from the recorded
  stream.
* :mod:`core.eval.run` — ``python -m core.eval run|measure|score|check``.
* :mod:`core.eval.measure` — the **matrix**: the suite run once per entry of
  ``MEASUREMENTS`` against one endpoint, and a table of the differences.  A
  default is decided by a comparison and never by a single score, and every
  row is recorded so the table can be produced again with no GPU.

The rule is the third bullet.  An agent's summary is evidence about its
reporting, never about its behaviour, so every machine check is answered from
:mod:`core.runtime.contract`'s records and the prose rubric is handed to a
person, marked as theirs.

``EVAL.md`` is the guide.  A platform keeps its own suite in its own
repository and loads it with :func:`~core.eval.suite.load_suite`; nothing in
here knows a tool name, an asset id or a deployment.
"""

# The `measure` FUNCTION is deliberately not re-exported here: binding it as
# `core.eval.measure` would shadow the submodule of that name on the package,
# and the next `from core.eval import measure` would get a function where it
# wanted a module. `core.eval.measure.measure` is the one way in.
from core.eval.measure import (MEASUREMENTS, Configured, Matrix, Measurement,
                               Unmeasurable)
from core.eval.score import (Half, NoStream, Report, Totals, Verdict,
                             records_from, score_run, score_suite)
from core.eval.suite import (FLAGS, HARNESS_OWNED_FLAGS, MIN_TEST_MISSIONS,
                             RUBRIC_CHANGES, SPLITS, TEST_SHARE, Mission,
                             MissionMisdeclared, RubricChange, Split, Suite,
                             check_the_suite_is_gradeable, load_suite,
                             missions_in)

__all__ = [
    "FLAGS", "HARNESS_OWNED_FLAGS", "MIN_TEST_MISSIONS", "RUBRIC_CHANGES",
    "SPLITS", "TEST_SHARE", "Mission", "MissionMisdeclared", "RubricChange",
    "Split", "Suite", "check_the_suite_is_gradeable", "load_suite",
    "missions_in",
    "Half", "NoStream", "Report", "Totals", "Verdict", "records_from",
    "score_run", "score_suite",
    "MEASUREMENTS", "Configured", "Matrix", "Measurement", "Unmeasurable",
]
