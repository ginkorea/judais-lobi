# tests/test_platforms_doc.py — the integration guide, asserted against the code

"""`PLATFORMS.md` claims to be sufficient to integrate without reading source.

That is a promise, and `ROADMAP.md` §2.8 makes it one third of the 1.0 gate. A
promise about a document is only worth anything if something fails when it
stops being true, and the failure mode is specific: prose does not fail a test
run, so a page that describes a harness three releases old looks exactly like a
page that is right. The reference deployment read a paragraph describing the
gate-matching rule for several releases *after* the rule had changed — the
paragraph was written when it was true, and nothing said anything when it
stopped being.

So this file holds the page against `core.runtime.contract`, in **both**
directions, plus the four other facts a reader of that page will act on:

* everything the contract publishes is named — every event, every field of
  every event, every flag, every environment variable, every outcome word,
  every clause of the exit contract;
* **nothing on the page names a mission flag or an environment variable the
  contract does not publish**, unless it is in :data:`NOT_A_MISSION_FLAG` or
  :data:`NOT_A_PUBLISHED_VARIABLE` with a sentence saying which surface it
  belongs to instead. That is the half that catches an invented flag, and it is
  why those two tables carry reasons rather than being bare allowlists;
* every extra `setup.py` declares is in the extras table, so a reader can find
  out what to install;
* every subcommand of `python -m core.eval` is named, read off the parser;
* the conformance kit the page tells a platform to copy exists, is two files,
  and passes against this repository — which is asserted in
  `tests/test_conformance_kit.py` and by the kit's own collection under
  `testpaths`, and named here so §10's claim has an owner;
* the CI workflows the page points at parse, and name the python floor.

Substring checks throughout, deliberately, and nothing about wording. A docs
test that asserted phrasing would be rewritten to match the docs the first time
somebody improved a sentence, which is a test that has stopped testing.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from core.runtime import contract as c

REPO = Path(__file__).resolve().parent.parent
PLATFORMS = REPO / "PLATFORMS.md"
SETUP = REPO / "setup.py"
WORKFLOWS = REPO / ".github" / "workflows"
CI = WORKFLOWS / "ci.yml"
RELEASE = WORKFLOWS / "pypi-release.yml"
KIT = REPO / "tests" / "conformance"


@pytest.fixture(scope="module")
def platforms() -> str:
    return PLATFORMS.read_text(encoding="utf-8")


# ── what the contract publishes, and what the page must therefore say ────────

class TestEveryPublishedNameIsOnThePage:
    """The forward direction. A name that exists in the code and not in the
    page a reader is sent to is a reader who has to open `core/`."""

    @pytest.mark.parametrize("event", c.EVENTS)
    def test_every_event(self, platforms, event):
        assert f"`{event}`" in platforms, (
            f"{event} is an event a consumer will receive and PLATFORMS.md "
            f"never names it")

    @pytest.mark.parametrize("event,field", [
        (event, field)
        for event in c.EVENTS
        for field in tuple(c.FIELDS[event]) + tuple(c.OPTIONAL.get(event, ()))
    ])
    def test_every_field_of_every_event(self, platforms, event, field):
        """Required and optional alike. An optional field is the only kind
        this repo may add without bumping the schema, which makes it the kind
        most likely to reach the module and not the page — and a field nobody
        documented is a field nobody reads with a default."""
        assert f"`{field}`" in platforms, f"{event}.{field} is undocumented"

    @pytest.mark.parametrize("flag", c.CLI_FLAGS)
    def test_every_published_flag(self, platforms, flag):
        assert f"`{flag}`" in platforms, (
            f"{flag} is in CLI_FLAGS — a surface this repo promised not to "
            f"move — and PLATFORMS.md never names it")

    @pytest.mark.parametrize("name", c.ENV_VARS)
    def test_every_published_variable(self, platforms, name):
        assert f"`{name}`" in platforms, f"{name} is in ENV_VARS and undocumented"

    @pytest.mark.parametrize("outcome", c.OUTCOMES)
    def test_every_outcome_word(self, platforms, outcome):
        assert f"`{outcome}`" in platforms, (
            f"{outcome!r} is a word `mission_finished` can say and a driver "
            f"that has no branch for it renders whatever its default arm does")

    @pytest.mark.parametrize("clause", sorted(c.EXIT_CONTRACT))
    def test_every_clause_of_the_exit_contract(self, platforms, clause):
        """Named as a clause, not merely used as an English word. `events`,
        `control` and `finished` all occur in ordinary prose, so the check is
        for the backticked name in the list the page draws."""
        assert f"**`{clause}`**" in platforms, (
            f"the exit contract's {clause!r} clause is a promise a platform "
            f"builds behaviour on and PLATFORMS.md does not state it")


# ── and nothing that the contract does not publish ───────────────────────────

#: Flags PLATFORMS.md names on purpose that are NOT in `contract.CLI_FLAGS`,
#: each with the surface it belongs to instead. A bare allowlist would let an
#: invented flag be waved through by whoever added it; a reason has to be
#: written, and a reason that is not true is visible in review.
#:
#: Kept to the ones the page really uses, and held there by
#: :meth:`TestThePageInventsNothing.test_the_excuses_are_all_in_use` — an
#: allowlist with room in it is an allowlist somebody widens instead of
#: thinking.
NOT_A_MISSION_FLAG = {
    "--personality": "a person's surface. Mission mode reaches a personality "
                     "through ELF_PERSONALITY, which IS published, and the "
                     "page says so",
    "--help": "every CLI has one, and this page names it only to say that "
              "what is in it besides CLI_FLAGS may move",
}

#: Same, for environment variables, and scoped to the families this repository
#: owns — `MISSION_*`, `MCP_*`, `JUDAIS_LOBI_*`, `ELF_*`, `TAI_*`, `LOCAL_*`.
#: A provider's own key (`OPENAI_API_KEY`) is somebody else's name and is not
#: swept for at all.
NOT_A_PUBLISHED_VARIABLE = {
    "ELF_PROVIDER": "the environment form of --provider, which is published "
                    "as a flag; the variable is a person's convenience",
}

_FAMILIES = re.compile(
    r"`((?:MISSION|MCP|JUDAIS_LOBI|ELF|TAI|LOCAL)_[A-Z0-9_]+)`")
_FLAGS = re.compile(r"`(--[a-z][a-z0-9-]*)`")


class TestThePageInventsNothing:
    """The reverse direction, and the one that catches a flag nobody
    implemented. A guide naming a flag the parser does not take sends an
    integrator to write a spawn line that refuses at the door."""

    def test_every_flag_it_names_is_published_or_excused(self, platforms):
        named = set(_FLAGS.findall(platforms))
        unexplained = named - set(c.CLI_FLAGS) - set(NOT_A_MISSION_FLAG)
        assert unexplained == set(), (
            f"PLATFORMS.md names {sorted(unexplained)}, which are not in "
            f"contract.CLI_FLAGS. Either the contract should publish them, or "
            f"they belong in NOT_A_MISSION_FLAG with the surface they are on.")

    def test_every_variable_it_names_is_published_or_excused(self, platforms):
        named = set(_FAMILIES.findall(platforms))
        unexplained = named - set(c.ENV_VARS) - set(NOT_A_PUBLISHED_VARIABLE)
        assert unexplained == set(), (
            f"PLATFORMS.md names {sorted(unexplained)}, which are not in "
            f"contract.ENV_VARS.")

    def test_the_excuses_are_all_in_use(self, platforms):
        """Every entry in the two tables above is a name the page really
        writes. An excuse for a name nobody uses is room for the next one, and
        an allowlist with room in it stops being read."""
        used = set(_FLAGS.findall(platforms)) | set(_FAMILIES.findall(platforms))
        stale = (set(NOT_A_MISSION_FLAG) | set(NOT_A_PUBLISHED_VARIABLE)) - used
        assert stale == set(), (
            f"{sorted(stale)} are excused and no longer named on the page")

    def test_the_event_table_holds_exactly_the_declared_vocabulary(
            self, platforms):
        """§3's table is the one place the page enumerates rather than
        describes, so it is compared as a set. A row for an event that no
        longer exists is a reader building a branch for a record that will
        never arrive."""
        rows = re.findall(r"^\| `([a-z_]+)` \| ", _event_table(platforms),
                          re.MULTILINE)
        assert set(rows) == set(c.EVENTS), sorted(set(rows) ^ set(c.EVENTS))

    @pytest.mark.parametrize("clause", sorted(c.EXIT_CONTRACT))
    def test_the_exit_clause_list_is_closed(self, platforms, clause):
        """Seven, and the page says seven. A page listing six of them while
        calling them seven is the arithmetic a reader trusts."""
        assert "Seven clauses" in platforms
        assert len(c.EXIT_CONTRACT) == 7


#: The header row of §3's one enumerating table. Located by its own header
#: rather than by the section it sits in, because a section holds several
#: tables and "the first one" is a fact about layout rather than about content.
_EVENT_TABLE_HEADER = "| event | required fields | optional fields |"


def _event_table(text: str) -> str:
    """The rows of §3's event table, up to the blank line that ends it."""
    body = text.split(_EVENT_TABLE_HEADER, 1)
    assert len(body) == 2, "PLATFORMS.md has no event table"
    return body[1].split("\n\n", 1)[0]


def _section(text: str, heading: str) -> str:
    """The body under one heading, up to the next heading of the same depth."""
    depth = len(heading) - len(heading.lstrip("#"))
    body = text.split(f"\n{heading}\n", 1)
    assert len(body) == 2, f"PLATFORMS.md has no '{heading}'"
    return body[1].split(f"\n{'#' * depth} ", 1)[0]


# ── the other four facts a reader will act on ────────────────────────────────

def _extras() -> dict:
    tree = ast.parse(SETUP.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "setup":
            for keyword in node.keywords:
                if keyword.arg == "extras_require":
                    return ast.literal_eval(keyword.value)
    raise AssertionError("setup.py declares no extras_require")


def _eval_subcommands() -> tuple:
    """The subcommand words, off the parser rather than out of a list."""
    from core.eval.run import _parser

    actions = [action for action in _parser()._actions
               if hasattr(action, "choices") and isinstance(action.choices, dict)]
    assert actions, "core.eval's parser has no subparsers"
    return tuple(actions[0].choices)


class TestTheReaderCanActOnIt:

    @pytest.mark.parametrize("extra", sorted(_extras()))
    def test_every_extra_is_in_the_extras_table(self, platforms, extra):
        """§1's table is what a reader installs from. An extra that exists and
        is not in it is a capability nobody discovers — `[anthropic]` was
        exactly that: named in the provider section and missing from the list
        of extras three sections later."""
        table = _section(platforms, "### The extras")
        assert f"`{extra}`" in table, (
            f"setup.py declares the {extra!r} extra and §1's table omits it")

    @pytest.mark.parametrize("subcommand", _eval_subcommands())
    def test_every_eval_subcommand_is_named(self, platforms, subcommand):
        assert f"**`{subcommand}`**" in platforms, (
            f"`python -m core.eval {subcommand}` exists and §9 does not "
            f"explain it")

    def test_the_conformance_kit_it_tells_you_to_copy_is_two_files(
            self, platforms):
        """§10's instruction is `cp` of two named files. A kit that had grown
        a third would leave every copy of it subtly broken, and the page would
        go on saying two."""
        for name in ("conftest.py", "test_conformance.py"):
            assert (KIT / name).is_file(), f"tests/conformance/{name} is gone"
            assert name in platforms, f"§10 does not name {name}"

    def test_it_points_at_the_kits_own_readme(self, platforms):
        assert "tests/conformance/README.md" in platforms
        assert (KIT / "README.md").is_file()


# ── the workflows the page points at, and the floor they hold ────────────────

class TestTheWorkflowsAreRealAndHoldTheFloor:
    """`ROADMAP.md` §2.8's third leg. A workflow file that does not parse is a
    CI run that never happens, and GitHub reports that as a badge nobody looks
    at rather than as a failure."""

    @pytest.mark.parametrize("path", [CI, RELEASE])
    def test_it_parses(self, path):
        yaml = pytest.importorskip(
            "yaml", reason="the workflows are YAML; pyyaml is the [mission] "
                           "extra and reading them needs it")
        assert path.is_file(), path
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(loaded, dict) and loaded.get("jobs"), path

    def test_the_matrix_names_the_floor_setup_py_declares(self):
        """`python_requires=">=3.10"` and a CI matrix that starts at 3.12 is a
        floor nobody tests — which is the whole reason the floor is a rule
        here rather than a preference."""
        yaml = pytest.importorskip("yaml")
        floor = re.search(r'python_requires=">=([0-9.]+)"',
                          SETUP.read_text(encoding="utf-8"))
        assert floor, "setup.py declares no python_requires"
        loaded = yaml.safe_load(CI.read_text(encoding="utf-8"))
        versions = loaded["jobs"]["suite"]["strategy"]["matrix"]["python"]
        assert floor.group(1) in versions, (
            f"setup.py's floor is {floor.group(1)} and the CI matrix is "
            f"{versions}")

    def test_the_release_workflow_documents_the_secret_it_needs(self):
        """It is the only workflow that holds one. A secret nobody wrote down
        is a release that fails once, in an hour nobody has."""
        text = RELEASE.read_text(encoding="utf-8")
        assert "PYPI_API_TOKEN" in text
        assert "secrets.PYPI_API_TOKEN" in text

    def test_ci_runs_the_harness_and_the_conformance_kit(self):
        """§10 tells a platform to put the kit on its CI trigger, and §9 says
        to run `check` there. This repository does both, or the advice is
        somebody else's homework."""
        text = CI.read_text(encoding="utf-8")
        assert "core.eval check" in text
        assert "tests/conformance" in text
        assert "compileall" in text
