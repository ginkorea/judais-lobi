# judais_lobi.py — the library API, and the one import a platform writes

"""Embed the mission runtime: ``from judais_lobi import Run``.

Six objects and a loop, which is the whole API::

    from judais_lobi import Bounds, Model, Observer, Personality, Run, \\
        Store, ToolPlane, Tools

    bus = Tools().bus                                   # SAFE, sandboxed, audited
    run = Run(Personality(system_message="You are Tai."),
              ToolPlane(bus=bus, offered=["read_file"]),
              Bounds(), Store(), Observer(), Model(ask=my_chat_fn))
    print(run.run("what does this repository build?").answer)

``my_chat_fn`` is ``messages -> str`` and nothing else: the loop is confined
to one injected callable and cannot ask a backend anything the caller did
not offer.  Everything else is a default that means *nothing*: no bus of its
own, no ceiling, no clock, no durable log, no watcher.  A platform adds the
ones it wants and pays for nothing else.

**The same contract the CLI speaks.**  A run built here emits the records
:mod:`core.runtime.contract` declares — same events, same required fields,
same ``SCHEMA_VERSION`` — because it is the same :class:`Run`.  There is no
library dialect and no CLI dialect; ``contract.conforms(record)`` is the one
question, and it is exported here so a consumer can ask it without knowing
which of the two produced the stream.

**The CLI is a client of this.**  ``judais --mission`` is
:func:`core.cli._mission`: argparse, then six builders — ``_personality_of``,
``_plane_of``, ``_bounds_of``, ``_store_of``, ``_observer_of``,
``_model_of`` — then this same :class:`Run`.  Whatever the CLI can do, six
objects can do, because six objects are all the CLI has.  What the CLI adds
on top is an operator's conveniences and none of the loop: the flags, the
console lines, the MCP transport, the run directory.

**Why a module and not a package.**  ``judais_lobi`` is one file at the root
of the distribution, shipped through ``py_modules`` rather than
``find_packages()``.  The wheel's top-level *packages* stay exactly ``core``,
``judais``, ``lobi`` — the set ``tests/test_packaging.py`` pins — and
``from judais_lobi import Run`` works anyway.  A fourth top-level package is
warranted the day this façade needs submodules, which is a decision to take
on that evidence and not before.

**There is deliberately no ``mission(objective, …)`` convenience builder.**
It would have to carry defaults — which model, which provider, which
transport, which store, which profile — and those defaults already have an
owner: the argparse parser in :func:`core.cli._main` and the six builders
that read it.  A second one would agree with the first for exactly as long
as somebody remembered to change both, and the day they disagreed a platform
would run under a policy nobody chose.  A platform that wants the CLI's
defaults spawns the CLI (``PLATFORMS.md`` § the spawn shape) and reads the
NDJSON; a platform that wants its own writes the six lines above.

See ``PLATFORMS.md`` for the whole integration guide — the personality
format, the ``SKILL.md`` fields, the stream, and the release-and-pin loop.
Install with ``pip install 'judais-lobi[mission]'``: the bare package runs
the loop, and the extra adds the three wheels a governed mission needs (an
MCP client, a YAML reader for ``--skill``, and a JSON-schema validator).
"""

from core.budgets import Cancellation, Deadline
from core.durable import RunStore
from core.runtime import contract
from core.runtime.context_window import MissionWindow
from core.runtime.contract import SCHEMA_VERSION
from core.runtime.run import (
    Bounds, Model, Observer, Personality, Run, Store, ToolPlane,
)
from core.runtime.skills import (SkillManifest as Skill, load_skill,
                                 resolve_skill)
from core.runtime.supervisor import Supervisor
from core.skills.library import packs
from core.tools import Tools

#: Every name this façade promises.  Explicit, and asserted against by
#: ``tests/test_facade.py``: a name here that does not import is a broken
#: promise, and a name exported by accident is a surface nobody chose to
#: support.
__all__ = [
    # The six.  `Run(personality, plane, bounds, store, observer, model)`.
    "Run",
    "Personality",
    "ToolPlane",
    "Bounds",
    "Store",
    "Observer",
    "Model",
    # What the six are usually built out of.
    "Tools",            # the default bus: SAFE, sandboxed, audited
    "Skill",            # a SKILL.md manifest — the closed set and the prompt
    "load_skill",       # …and how to read one off disk
    # The shipped mission packs. `Skill.load("analyst")` takes a path OR a
    # pack name; `packs()` says which names there are. A platform that
    # writes its own manifest keeps using `load_skill` and never calls
    # either.
    "resolve_skill",    # a path, or the name of a shipped pack
    "packs",            # ('analyst', 'coding', 'research')
    "Deadline",         # a wall clock for `Bounds`
    "Cancellation",     # a switch for `Bounds`
    "Supervisor",       # what watches a run for repetition, for `Bounds`
    "MissionWindow",    # the context bound, for `Model`
    "RunStore",         # the durable transcript, for `Store`
    # The wire, so a consumer can check a stream without owning a copy of
    # the rules.
    "contract",
    "SCHEMA_VERSION",
]
