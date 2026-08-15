# tests/test_packaging.py — what `pip install judais-lobi` actually gets

"""The declared dependencies, against the code that imports them.

A dependency nobody declared is not a missing line in a file; it is a
turn that dies on a host where the developer's laptop happened to have
the wheel.  `tomllib` is the one that bites: it is 3.11+, `setup.py`
says `python_requires=">=3.10"`, and `PersonalityConfig.from_file`
reads a TOML persona.  The reference deployment runs 3.10 and points an
env var at a `tai.toml`, so on a clean install the agent never reaches
`mission_started` — the silent-stream failure the exit contract tells a
consumer to report, caused by packaging rather than by the harness.

`requirements.txt` says at the top of itself that it mirrors
`install_requires`.  That claim is checked here rather than believed,
because the two files drift in the direction that installs less.
"""

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SETUP_PY = REPO / "setup.py"
REQUIREMENTS = REPO / "requirements.txt"


def _setup_kwargs() -> dict:
    """The keywords of the ``setup()`` call, as literals.

    Parsed rather than imported: importing ``setup.py`` runs ``setup()``,
    which reads ``sys.argv`` and would make a test suite a build.
    """
    tree = ast.parse(SETUP_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "setup":
            return {kw.arg: kw.value for kw in node.keywords}
    raise AssertionError("setup.py has no setup() call")


def _requires() -> list:
    return [ast.literal_eval(item)
            for item in _setup_kwargs()["install_requires"].elts]


def _requirements_lines() -> list:
    return [line.strip()
            for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")]


class TestTheTomlReaderIsDeclared:
    """The one import in ``core/`` that is not in the standard library on
    every interpreter this package says it supports."""

    def test_the_supported_floor_is_below_tomllib(self):
        """The whole reason a marker is needed. If this ever rises to 3.11
        the pin below becomes dead weight and can go."""
        floor = ast.literal_eval(_setup_kwargs()["python_requires"])
        assert floor == ">=3.10"

    def test_tomli_is_required_on_the_interpreters_that_lack_tomllib(self):
        pins = [item for item in _requires() if item.startswith("tomli")]
        assert pins, (
            "core/contracts/schemas.py imports tomllib and falls back to "
            "tomli; on 3.10 neither is installed and a TOML personality "
            "raises before the first event")
        assert len(pins) == 1
        assert re.fullmatch(
            r'tomli>=[\d.]+; *python_version *< *"3\.11"', pins[0]), pins[0]

    def test_it_is_a_requirement_and_not_an_extra(self):
        """``schemas.py`` is core and unconditional. An extra would mean the
        personality seam works only for whoever also asked for a mission."""
        extras = ast.literal_eval(_setup_kwargs()["extras_require"])
        for name, items in extras.items():
            assert not [i for i in items if i.startswith("tomli")], name

    def test_the_fallback_it_pays_for_is_still_in_the_source(self):
        source = (REPO / "core" / "contracts" / "schemas.py").read_text()
        assert "import tomli as tomllib" in source


class TestARefusalNamesAnExtraThatFixesIt:
    """The two places that refuse for want of pyyaml named `[critic]` —
    an extra that happens to carry pyyaml behind three model SDKs and a
    keyring. An operator following that sentence installs anthropic,
    google-generativeai and keyring to read a YAML file. `[mission]` is
    the one that exists for this path.
    """

    MESSAGES = (
        "core/runtime/skills.py",           # frontmatter on --skill
        "core/contracts/schemas.py",        # a YAML personality file
    )

    def test_the_pyyaml_refusals_point_at_the_mission_extra(self):
        for rel in self.MESSAGES:
            source = (REPO / rel).read_text(encoding="utf-8")
            assert "judais-lobi[mission]" in source, rel
            assert "judais-lobi[critic]" not in source, rel

    def test_that_extra_is_one_that_carries_pyyaml(self):
        """The half that makes the sentence true rather than merely
        different."""
        extras = ast.literal_eval(_setup_kwargs()["extras_require"])
        assert [item for item in extras["mission"] if item.startswith("pyyaml")]


class TestRequirementsMirrorsSetupPy:
    def test_line_for_line_and_in_order(self):
        """Equality, not containment: a line in one file and not the other
        is a difference between what the package declares and what a
        `pip install -r` reproduces, in whichever direction it points."""
        assert _requirements_lines() == _requires()

    def test_no_optional_stack_leaked_back_in(self):
        """It used to pin the whole voice/TTS stack — torch included — as
        hard requirements while omitting mcp entirely."""
        names = {re.split(r"[<>=;\[ ]", line)[0] for line in _requirements_lines()}
        assert not names & {"torch", "TTS", "torchaudio", "mcp", "pyyaml"}
