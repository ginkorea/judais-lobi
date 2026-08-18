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


def _version() -> str:
    """The single assignment every other statement of the version derives
    from — ``version=VERSION`` and, since this test, ``description`` too."""
    tree = ast.parse(SETUP_PY.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                getattr(target, "id", "") == "VERSION" for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("setup.py has no VERSION assignment")


def _summary() -> str:
    """The ``Summary:`` line a built wheel carries.

    Rendered from the ``description`` expression with ``VERSION`` bound the
    way setup.py binds it, rather than built for real: this file refuses to
    import setup.py at all, and a build here would need network and a
    backend to answer a question the source already answers. Any other name
    in that expression raises ``NameError``, which is the right complaint.
    """
    node = _setup_kwargs()["description"]
    return eval(compile(ast.Expression(node), str(SETUP_PY), "eval"),
                {"__builtins__": {}, "VERSION": _version()})


def _requires() -> list:
    return [ast.literal_eval(item)
            for item in _setup_kwargs()["install_requires"].elts]


def _packages_exclude() -> list:
    """The names passed to ``find_packages(exclude=…)``, or ``[]``."""
    call = _setup_kwargs()["packages"]
    if not (isinstance(call, ast.Call)
            and getattr(call.func, "id", "") == "find_packages"):
        raise AssertionError("packages= is not a find_packages() call")
    for kw in call.keywords:
        if kw.arg == "exclude":
            return list(ast.literal_eval(kw.value))
    return []


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
        hard requirements while omitting mcp entirely. `faiss-cpu` was the
        same mistake in miniature: `_make_index` imports faiss inside a try
        and returns `NumpyIndex` when it is not there, so no code path ever
        required the compiled wheel every install was paying for."""
        names = {re.split(r"[<>=;\[ ]", line)[0] for line in _requirements_lines()}
        assert not names & {"torch", "TTS", "torchaudio", "mcp", "pyyaml",
                            "faiss-cpu"}

    def test_the_optional_ones_are_reachable_as_extras(self):
        """Dropped from `install_requires` and named nowhere is not optional,
        it is gone. Each of these is somebody's deliberate install."""
        extras = ast.literal_eval(_setup_kwargs()["extras_require"])
        offered = {re.split(r"[<>=;\[ ]", item)[0]
                   for items in extras.values() for item in items}
        assert {"faiss-cpu", "mcp", "pyyaml", "torch"} <= offered


class TestTheSummaryDoesNotKeepItsOwnVersion:
    """``description`` becomes ``Summary:`` in the built metadata and it
    opens with the version number — a number ``VERSION`` on line 3 already
    owns. Written out twice it stays true only while whoever bumps one
    remembers the other, and the Makefile's rebuild banner had already lost
    that game by three releases when it was found still saying v0.7.2.
    """

    def test_the_summary_carries_the_version(self):
        assert f"v{_version()}" in _summary(), _summary()

    def test_it_is_derived_and_not_retyped(self):
        """An f-string over ``VERSION``, not a literal that happens to
        agree today — a literal passes the check above until the next bump
        and then ships a wheel that misdescribes itself."""
        node = _setup_kwargs()["description"]
        assert isinstance(node, ast.JoinedStr), (
            "description is a constant string; the version in it is a "
            "second copy of VERSION")
        interpolated = {value.value.id
                        for value in node.values
                        if isinstance(value, ast.FormattedValue)
                        and isinstance(value.value, ast.Name)}
        assert "VERSION" in interpolated, interpolated


class TestTheWheelDoesNotShipTheTests:
    """`tests/` has an `__init__.py`, so it is a package as far as
    `find_packages()` is concerned — and 0.8.0's wheel was found carrying a
    top-level `tests` module at release time, one `pip install` away from
    shadowing every other project's `tests`. The exclusion is the fix; this
    pins it in the same AST the other checks read."""

    def test_find_packages_excludes_tests(self):
        names = _packages_exclude()
        assert names, "find_packages() with no exclude ships tests/"
        assert "tests" in names and "tests.*" in names

    def test_the_top_level_names_are_the_three_this_package_owns(self):
        """The exclusion fixes the one directory that was caught. This is
        the rule it was an instance of: everything with an ``__init__.py``
        at the root goes into site-packages under its own name, so any new
        one — a scratch package, a parked experiment, a second `tests` by
        another name — ships to every installer until somebody notices.

        setuptools is not importable in the test environment, so the
        discovery ``find_packages()`` would do is redone here: root
        directories carrying an ``__init__.py``, less what ``exclude``
        names. Dotted directories are skipped the way setuptools skips
        them — a `.venv` is not a candidate package.
        """
        excluded = {name.split(".")[0] for name in _packages_exclude()}
        found = {child.name for child in REPO.iterdir()
                 if child.is_dir()
                 and not child.name.startswith(".")
                 and (child / "__init__.py").exists()}
        assert found - excluded == {"core", "judais", "lobi"}, sorted(found)


class TestTheLibraryFacadeShipsAsAModule:
    """`from judais_lobi import Run` off a plain `pip install`, without a
    fourth top-level package.

    The class above pins the wheel's top-level *package* set at exactly
    three. The façade has to be importable under its own dotted name
    anyway, so it ships as a single MODULE — `judais_lobi.py` at the root,
    declared in `py_modules`, invisible to `find_packages()`. Both halves
    are asserted, because either one alone is a wheel that installs and
    does not work: no `py_modules` and the file is not in the
    distribution; no file and `py_modules` names nothing.
    """

    def _py_modules(self) -> list:
        node = _setup_kwargs().get("py_modules")
        assert node is not None, (
            "setup.py declares no py_modules; judais_lobi.py is at the root "
            "and find_packages() cannot see a bare module, so the wheel "
            "would ship without the façade")
        return list(ast.literal_eval(node))

    def test_the_facade_is_declared_as_a_module(self):
        assert self._py_modules() == ["judais_lobi"]

    def test_the_declared_module_is_a_file_that_exists(self):
        """A name in `py_modules` with no file beside it builds a wheel
        that is missing exactly the import the release was cut for."""
        for name in self._py_modules():
            assert (REPO / f"{name}.py").is_file(), name

    def test_it_is_not_also_a_package(self):
        """The whole point of the module form. A `judais_lobi/` directory
        with an `__init__.py` would be a fourth top-level name in
        site-packages and would break the assertion above it."""
        assert not (REPO / "judais_lobi").exists()

    def test_every_promised_name_imports(self):
        """`__all__` is a promise, and a name in it that does not resolve
        is the promise broken at the first `from judais_lobi import …`."""
        import judais_lobi

        assert judais_lobi.__all__, "the façade promises nothing"
        missing = [name for name in judais_lobi.__all__
                   if not hasattr(judais_lobi, name)]
        assert not missing, missing

    def test_the_facade_is_the_only_root_module_that_ships(self):
        """The mirror of the top-level *package* rule, for modules. A
        scratch script at the root is one `py_modules` line away from
        shadowing somebody's `utils`; this says which single one is
        deliberate. `main.py` and `setup.py` are at the root and are NOT
        declared, which is the arrangement being pinned."""
        assert set(self._py_modules()) == {"judais_lobi"}


class TestTheAnthropicExtraIsTheOneTheRefusalNames:
    """`AnthropicBackend` soft-imports the SDK and refuses by naming an
    extra. An extra that does not exist, or that installs a different
    floor than the critic asks for, makes that sentence a lie."""

    def test_the_refusal_points_at_an_extra_that_carries_the_sdk(self):
        source = (REPO / "core" / "runtime" / "backends"
                  / "anthropic_backend.py").read_text(encoding="utf-8")
        assert "judais-lobi[anthropic]" in source
        extras = ast.literal_eval(_setup_kwargs()["extras_require"])
        assert [item for item in extras["anthropic"]
                if item.startswith("anthropic")]

    def test_the_critic_and_the_backend_ask_for_the_same_floor(self):
        """`extras_require` is read here with `ast.literal_eval`, so the
        pin cannot be a shared name and has to be repeated. This is what
        keeps the two copies from drifting."""
        extras = ast.literal_eval(_setup_kwargs()["extras_require"])
        assert [item for item in extras["critic"]
                if item.startswith("anthropic")] == extras["anthropic"]


class TestTheWheelShipsTheMissionPacks:
    """`core/skills/library/<name>/` is DATA — no `__init__.py` anywhere
    under it, so `find_packages()` never sees it and the wheel's top-level
    set stays {core, judais, lobi}. Which means the packs ship only if
    `package_data` names them, and a pack that is not in the wheel is a
    `--skill analyst` that works on the developer's checkout and refuses
    on every install.

    Read out of the same AST as everything else in this file: building a
    wheel here would need setuptools, which the test environment does not
    have, and the question the source can answer is the one that gets
    broken — somebody adds a pack, or a file inside one, and does not add
    the pattern.
    """

    #: The three first-party packs `README.md` promises. `analyst` is lane
    #: O's; `coding` and `research` arrive with lanes N and M, and every
    #: assertion below except this one is written over the packs that are
    #: actually on disk, so they are covered the day they land.
    FIRST_PARTY = ("analyst", "coding", "research")

    LIBRARY = REPO / "core" / "skills" / "library"

    def _patterns(self) -> list:
        data = ast.literal_eval(_setup_kwargs()["package_data"])
        assert "core.skills" in data, sorted(data)
        return list(data["core.skills"])

    def _installed(self) -> list:
        return sorted(child.name for child in self.LIBRARY.iterdir()
                      if child.is_dir() and (child / "SKILL.md").is_file())

    def test_the_analyst_pack_is_installed_and_named(self):
        """One named assertion, so an empty library cannot make every
        other test in this class vacuously true."""
        assert "analyst" in self._installed()
        assert set(self._installed()) <= set(self.FIRST_PARTY), (
            "a pack not in FIRST_PARTY; add it there and to README.md's "
            "First-party skills section")

    def test_every_file_of_every_installed_pack_is_matched_by_a_pattern(self):
        """The rule rather than the instance: whatever a pack ships —
        another fixture, a second template, a third pack — is in the wheel
        or this is red."""
        import fnmatch

        patterns = self._patterns()
        for name in self._installed():
            for path in sorted((self.LIBRARY / name).rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(self.LIBRARY.parent).as_posix()
                assert any(fnmatch.fnmatch(relative, pattern)
                           for pattern in patterns), (
                    f"{relative} matches no package_data pattern "
                    f"{patterns}")

    def test_no_pack_is_a_python_package(self):
        """An `__init__.py` under `library/` would put a pack into
        `find_packages()`, and would also shadow `core/skills/library.py`
        — the module that loads them — out of existence."""
        assert not list(self.LIBRARY.rglob("__init__.py"))

    def test_the_sdist_carries_them_too(self):
        """`package_data` fills the wheel; `MANIFEST.in` fills the sdist,
        and a release is built from a clean `git archive` of the tag. A
        file in neither is a file `pip install` never sees."""
        manifest = (REPO / "MANIFEST.in").read_text(encoding="utf-8")
        assert "recursive-include core/skills/library" in manifest

    def test_no_pack_file_is_ignored_by_git(self):
        """A release is built from a clean `git archive` of the tag, so a
        pack file git does not track is a file no install ever sees —
        `package_data` and `MANIFEST.in` both name it and neither can put
        it back. Caught for real: `.gitignore` carried `*.log` for test
        artefacts, and the analyst pack's `service.log` fixture — the one
        its `errors_by_hour` mission runs against — was silently untracked
        at first commit. The negation beside that rule is the fix; this is
        what stops the next one.
        """
        import subprocess

        try:
            tracked = subprocess.run(
                ["git", "ls-files", "core/skills/library"],
                cwd=REPO, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
            import pytest
            pytest.skip(f"git is not usable here: {exc}")
        if tracked.returncode != 0:                           # pragma: no cover
            import pytest
            pytest.skip("not a git checkout")

        known = {line.strip() for line in tracked.stdout.splitlines()
                 if line.strip()}
        for name in self._installed():
            for path in sorted((self.LIBRARY / name).rglob("*")):
                if path.is_file():
                    relative = path.relative_to(REPO).as_posix()
                    assert relative in known, (
                        f"{relative} is not tracked by git — check "
                        f".gitignore")
