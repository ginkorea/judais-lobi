# core/eval/__init__.py — the eval harness: missions in, verdicts out

"""Measure before default.

ROADMAP §3 says nothing becomes on-by-default until the harness scores it
against a held-out set, and until this package there was no harness.  The
August 2026 measurements lived in docstrings, the corpus was one recorded
fabrication file, and three live questions — is ``--swarm`` a better default,
is ``--protocol native`` a better default, should ``reading.py`` become a
grounding tier — had no way to be answered except by somebody's memory of a
demo.

The package is six modules and one rule:

* :mod:`core.eval.suite` — what a mission is, what a flag is, how a suite is
  refused for being ungradeable, and the dated ``RUBRIC_CHANGES`` ledger.
* :mod:`core.eval.stub_suite` — the eleven missions this repository ships,
  over its own MCP stub server, so the harness runs with no GPU and no
  platform.
* :mod:`core.eval.benchmark_suite` — twelve more, chosen so that the way
  they fail is a job the RUNTIME could have done: multi-hop evidence,
  missing evidence, contradictory evidence, dependency reasoning,
  long-horizon recovery, misleading evidence.  ROADMAP §2.9.3's benchmark
  pack, on this machinery and not a second framework.
* :mod:`core.eval.score` — the verdict, computed **only** from the recorded
  stream.
* :mod:`core.eval.run` — ``python -m core.eval
  run|measure|ablation|score|check|extraction|registry``.
* :mod:`core.eval.extraction` — ROADMAP §2.9.3's gatekeeper: real recorded
  receipts in, typed propositions with abstention out, and a rate per
  failure class with an interval on it.  The one measurement in this
  package that is not about a mission.
* :mod:`core.eval.measure` — the **matrix**: the suite run once per entry of
  ``MEASUREMENTS`` against one endpoint, and a table of the differences.  A
  default is decided by a comparison and never by a single score, and every
  row is recorded so the table can be produced again with no GPU.
* :mod:`core.eval.ablation` — the **arms**: the same missions across a
  declared set of CLI flag deltas, paired mission by mission, with a Wilson
  interval on each arm's rate.  An arm whose flags the spawn line does not
  accept is skipped with the reason, so a piece that has not been built yet
  still has its column.
* :mod:`core.eval.registry` — the **profile store**: what has actually been
  measured about each model, ingested only from the reports the three
  measuring subcommands write, every figure with its ``k``/``n``, nothing
  averaged across interpreters and nothing under the sample floor given an
  interval.  `MODELS.md` §5.  It does not route; it is the evidence a
  router would have to read first.

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
from core.eval.extraction import (CATEGORIES, FAMILIES, KINDS, STATUSES,
                                  Attempt, ExtractionReport, Probe,
                                  ProbeMisdeclared, Proposition, Rate,
                                  Unextractable, load_probes,
                                  parse_propositions, rates_of, run_probes,
                                  score_attempt, wilson)
# `wilson` above is the ONE owner. `ablation` used to carry a twin of it —
# same statistic, its own z, its own rounding, grown on a parallel branch —
# and that twin is gone: the module imports this one and keeps only
# `ablation.band`, which is the reporting rule (no runs, no interval) and
# not a second implementation of the arithmetic.
from core.eval.ablation import (ARMS, Ablation, Arm, ArmResult, Unavailable,
                                ablate, accepted_flags, band, paired)
from core.eval.measure import (MEASUREMENTS, Configured, Matrix, Measurement,
                               Unmeasurable)
# Same rule as `measure` above: the MODULE `core.eval.registry` is not
# shadowed by a binding of that name here, so `from core.eval import
# registry` keeps getting the module. `Registry` is the class.
from core.eval.registry import (DEFAULT_REGISTRY, FLOOR_N, SCHEMA, Delta,
                                Entry, Figure, Registry, Unregisterable,
                                deltas, endpoint_kind, read_report, render,
                                source_of, staleness)
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
    "CATEGORIES", "FAMILIES", "KINDS", "STATUSES", "Attempt",
    "ExtractionReport", "Probe", "ProbeMisdeclared", "Proposition", "Rate",
    "Unextractable", "load_probes", "parse_propositions", "rates_of",
    "run_probes", "score_attempt", "wilson",
    "ARMS", "Ablation", "Arm", "ArmResult", "Unavailable", "ablate",
    "accepted_flags", "band", "paired",
    "DEFAULT_REGISTRY", "FLOOR_N", "SCHEMA", "Delta", "Entry", "Figure",
    "Registry", "Unregisterable", "deltas", "endpoint_kind", "read_report",
    "render", "source_of", "staleness",
]
