# tests/test_skills_compose.py — several SKILL.md files as one mission

"""`--skill` repeats, and `compose_manifests` is the only thing that knows
what repeating it means.

Two lessons run through this file and every test is one of them.

The first: **one skill composes to itself, unchanged.** Composition is new
and the single-skill path is not, so a manifest handed in alone comes back
as the same object with the same bytes in its prompt. The replay corpus is
what proves it at the level of a whole mission; this file proves it at the
level of the function, which is where a regression would be introduced.

The second: **strictness unions and identity does not.** What a mission can
have several of — tools, prompt text, checks it must pass — is unioned, and
a check asked for by any skill binds the run. What a mission has exactly one
of — its name, its answer shape, its identifier grammar — belongs to the
primary or, where there is no honest way to choose, is a refusal naming both
skills. The failure this shape exists to prevent is quiet: two skills that
disagree about a platform's identifier grammar, silently resolved by taking
the first, produce a run whose grounding report says a check ran over
identifiers it could never have matched.
"""

import os
import textwrap

import pytest

from core.runtime.skills import (
    SkillManifest,
    SkillManifestError,
    compose_manifests,
    load_skill,
)

pytest.importorskip("yaml", reason="a skill manifest is YAML frontmatter")


def skill(tmp_path, name, body=None, **fields) -> SkillManifest:
    """One manifest written to disk under *name*, and loaded.

    Frontmatter keys are passed as keywords and YAML-dumped, so a test says
    what it is about (`grounding={...}`) and nothing about fences.
    """
    import yaml

    front = {"name": name, "when_to_use": f"When {name} applies."}
    front.setdefault("allowed_tools", ["alpha"])
    front.update(fields)
    path = tmp_path / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        + yaml.safe_dump(front, sort_keys=False, allow_unicode=True)
        + "---\n\n"
        + (body if body is not None else f"# {name}\n\nThe {name} body.")
        + "\n",
        encoding="utf-8",
    )
    return load_skill(path)


class TestOneSkillComposesToItself:
    """The compatibility promise, stated three ways.

    A framework that quietly re-rendered every single-skill prompt the day
    composition landed would have changed every mission in the field, and
    nothing would have said so.
    """

    def test_it_is_the_same_object_and_not_a_copy(self, tmp_path):
        one = skill(tmp_path, "solo")
        assert compose_manifests([one]) is one

    def test_the_prompt_is_byte_identical(self, tmp_path):
        one = skill(tmp_path, "solo", output_format="A table.")
        assert compose_manifests([one]).prompt == one.prompt

    def test_it_carries_no_trace_of_having_been_composed(self, tmp_path):
        """`composed` is what a report reads to name every skill a run is
        under. Empty for one skill, so the line it prints is the line it
        printed before."""
        assert compose_manifests([skill(tmp_path, "solo")]).composed == ()

    def test_composing_nothing_is_a_refusal_and_not_an_empty_manifest(self):
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([])
        assert "no skill manifests" in str(exc.value)


class TestTheClosedSetUnions:
    def test_it_is_a_union_in_first_seen_order(self, tmp_path):
        """A union and never an intersection. Two skills composed for the
        knowledge in both of them, handed the tools in neither, is a
        mission that answers from the model's memory — the same failure a
        silently narrowed closed set is, arrived at a different way."""
        composed = compose_manifests([
            skill(tmp_path, "first", allowed_tools=["alpha", "beta"]),
            skill(tmp_path, "second", allowed_tools=["beta", "gamma"]),
        ])
        assert composed.allowed_tools == ("alpha", "beta", "gamma")

    def test_the_set_stays_closed(self, tmp_path):
        """Composition widens the closed set to exactly the union and not
        to the bus: a tool neither skill named is still not in it."""
        composed = compose_manifests([
            skill(tmp_path, "first", allowed_tools=["alpha"]),
            skill(tmp_path, "second", allowed_tools=["beta"]),
        ])
        assert "run_shell_command" not in composed.allowed_tools

    def test_one_tool_in_two_conventions_is_one_entry(self, tmp_path):
        """`same_tool` is this framework's one answer to *are these the
        same tool*, and a composed set that named `echo` and `mcp.echo`
        separately would ask the server for a tool twice."""
        composed = compose_manifests([
            skill(tmp_path, "first", allowed_tools=["echo"]),
            skill(tmp_path, "second", allowed_tools=["mcp.echo"]),
        ])
        assert composed.allowed_tools == ("echo",)

    def test_required_anywhere_beats_optional(self, tmp_path):
        """The skill that needs the tool needs it. Being composed with a
        skill that merely likes it is news about the composition and not
        news about the plane."""
        composed = compose_manifests([
            skill(tmp_path, "first", allowed_tools=["shared?"]),
            skill(tmp_path, "second", allowed_tools=["shared"]),
        ])
        assert composed.optional_tools == frozenset()

    def test_required_first_is_still_required(self, tmp_path):
        """The same rule read from the other end, so it is a rule about
        requirement and not a rule about which skill was listed first."""
        composed = compose_manifests([
            skill(tmp_path, "first", allowed_tools=["shared"]),
            skill(tmp_path, "second", allowed_tools=["shared?"]),
        ])
        assert composed.optional_tools == frozenset()

    def test_optional_in_every_skill_that_names_it_stays_optional(
            self, tmp_path):
        assert compose_manifests([
            skill(tmp_path, "first", allowed_tools=["shared?"]),
            skill(tmp_path, "second", allowed_tools=["shared?"]),
        ]).optional_tools == {"shared"}


class TestThePrimaryOwnsWhatThereIsOneOf:
    def test_the_name_is_the_primarys(self, tmp_path):
        """Every refusal, every report and every memory bank files a run
        under one word."""
        assert compose_manifests([
            skill(tmp_path, "first"), skill(tmp_path, "second"),
        ]).name == "first"

    def test_the_version_and_source_are_the_primarys(self, tmp_path):
        first = skill(tmp_path, "first", version="2.1.0")
        composed = compose_manifests([first, skill(tmp_path, "second",
                                                   version="9.9.9")])
        assert (composed.version, composed.source) == ("2.1.0", first.source)

    def test_the_output_contract_is_the_primarys(self, tmp_path):
        """THE test for first-is-primary. A mission has one answer shape,
        and the one the primary's grounding block is written against is
        the one that has to survive."""
        composed = compose_manifests([
            skill(tmp_path, "first", output_format="A table of assets."),
            skill(tmp_path, "second", output_format="A numbered list."),
        ])
        assert composed.output_contract == "A table of assets."

    def test_a_supporting_skills_answer_shape_does_not_reach_the_model(
            self, tmp_path):
        """Not merely unused — absent. Two output contracts in one system
        message is a model choosing one, and the choice is not the
        harness's to leave open."""
        composed = compose_manifests([
            skill(tmp_path, "first", output_format="A table of assets."),
            skill(tmp_path, "second", output_format="A numbered list."),
        ])
        assert "A numbered list." not in composed.prompt

    def test_the_primarys_answer_shape_still_ends_the_prompt(self, tmp_path):
        """`output_format` is rendered last because it is the instruction
        a model is acting on when it stops, and composition must not bury
        that under a supporting skill's body — it moves to the end of the
        composition rather than staying where the primary's own prompt
        left it. The same recency argument that moved the conduct after
        the catalogue."""
        composed = compose_manifests([
            skill(tmp_path, "first", output_format="A table of assets."),
            skill(tmp_path, "second"),
        ])
        assert composed.prompt.rstrip().endswith("A table of assets.")
        assert (composed.prompt.index("The second body.")
                < composed.prompt.index("A table of assets."))

    def test_the_supporting_body_is_still_there(self, tmp_path):
        """Only the answer shape is taken off a supporting skill. Its
        operational knowledge is the reason it was composed in."""
        composed = compose_manifests([
            skill(tmp_path, "first"),
            skill(tmp_path, "second", output_format="A numbered list."),
        ])
        assert "The second body." in composed.prompt

    def test_the_prompts_arrive_in_listed_order(self, tmp_path):
        composed = compose_manifests([
            skill(tmp_path, "first"),
            skill(tmp_path, "second"),
            skill(tmp_path, "third"),
        ])
        assert (composed.prompt.index("The first body.")
                < composed.prompt.index("The second body.")
                < composed.prompt.index("The third body."))

    def test_composed_names_every_skill_primary_first(self, tmp_path):
        assert compose_manifests([
            skill(tmp_path, "first"), skill(tmp_path, "second"),
        ]).composed == ("first", "second")


class TestGroundingMerges:
    """The half where getting it wrong is quiet.

    A closed set that came out wrong refuses at the door. A grounding block
    that came out wrong produces a report saying a check ran.
    """

    def test_a_skill_with_no_grounding_contributes_nothing(self, tmp_path):
        composed = compose_manifests([
            skill(tmp_path, "first", grounding={"ignore": ["placeholder"]}),
            skill(tmp_path, "second"),
        ])
        assert composed.grounding == {"ignore": ["placeholder"]}

    def test_nobody_declaring_one_composes_to_no_validator(self, tmp_path):
        composed = compose_manifests([
            skill(tmp_path, "first"), skill(tmp_path, "second"),
        ])
        assert composed.grounding is None

    def test_the_literal_lists_union_in_first_seen_order(self, tmp_path):
        composed = compose_manifests([
            skill(tmp_path, "first", grounding={"ignore": ["dead", "shared"]}),
            skill(tmp_path, "second", grounding={"ignore": ["shared", "tbd"]}),
        ])
        assert composed.grounding["ignore"] == ["dead", "shared", "tbd"]

    def test_figures_from_unions_too(self, tmp_path):
        composed = compose_manifests([
            skill(tmp_path, "first", grounding={
                "number_pattern": r"\d+", "figures_from": ["verify"]}),
            skill(tmp_path, "second", grounding={
                "number_pattern": r"\d+", "figures_from": ["measure"]}),
        ])
        assert composed.grounding["figures_from"] == ["verify", "measure"]

    def test_a_check_asked_for_by_one_skill_binds_the_run(self, tmp_path):
        """OR and never AND. A skill asked for a claim table because its
        own answers are not worth much without one, and being composed
        with a laxer skill is not a reason to stop asking."""
        composed = compose_manifests([
            skill(tmp_path, "first", grounding={"claim_table": True}),
            skill(tmp_path, "second", grounding={"ignore": ["dead"]}),
        ])
        assert composed.grounding["claim_table"] is True

    def test_the_expensive_tiers_or_the_same_way(self, tmp_path):
        composed = compose_manifests([
            skill(tmp_path, "first", grounding={"critic": True}),
            skill(tmp_path, "second", grounding={
                "claim_table": True, "reading": True}),
        ])
        assert (composed.grounding["critic"], composed.grounding["reading"],
                composed.grounding["claim_table"]) == (True, True, True)

    def test_a_flag_nobody_asked_for_stays_off(self, tmp_path):
        composed = compose_manifests([
            skill(tmp_path, "first", grounding={"ignore": ["dead"]}),
            skill(tmp_path, "second", grounding={"ignore": ["tbd"]}),
        ])
        assert "critic" not in composed.grounding

    def test_a_scalar_only_one_skill_declares_is_taken(self, tmp_path):
        composed = compose_manifests([
            skill(tmp_path, "first", grounding={"ignore": ["dead"]}),
            skill(tmp_path, "second", grounding={
                "identifier_pattern": r"\bacme\.\w+\b"}),
        ])
        assert composed.grounding["identifier_pattern"] == r"\bacme\.\w+\b"

    def test_two_skills_agreeing_on_a_scalar_is_not_a_conflict(self, tmp_path):
        composed = compose_manifests([
            skill(tmp_path, "first", grounding={"max_repairs": 3}),
            skill(tmp_path, "second", grounding={"max_repairs": 3}),
        ])
        assert composed.grounding["max_repairs"] == 3

    def test_two_identifier_grammars_are_a_refusal_naming_both(self, tmp_path):
        """THE grounding test. There is no honest way to pick between two
        identifier grammars: taking the first switches the check off for
        the other skill's identifiers while the report goes on saying it
        ran, which is the one report a reader must be able to believe."""
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([
                skill(tmp_path, "first", grounding={
                    "identifier_pattern": r"\bacme\.\w+\b"}),
                skill(tmp_path, "second", grounding={
                    "identifier_pattern": r"\bother\.\w+\b"}),
            ])
        message = str(exc.value)
        assert "identifier_pattern" in message
        assert "'first'" in message and "'second'" in message
        assert repr(r"\bacme\.\w+\b") in message
        assert repr(r"\bother\.\w+\b") in message

    def test_disagreeing_repair_budgets_refuse_too(self, tmp_path):
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([
                skill(tmp_path, "first", grounding={"max_repairs": 1}),
                skill(tmp_path, "second", grounding={"max_repairs": 4}),
            ])
        assert "max_repairs" in str(exc.value)

    def test_must_cite_unions_by_check_name(self, tmp_path):
        composed = compose_manifests([
            skill(tmp_path, "first", grounding={"must_cite": ["identifiers"]}),
            skill(tmp_path, "second", grounding={"must_cite": {"claims": 3}}),
        ])
        assert composed.grounding["must_cite"] == {
            "identifiers": 1, "claims": 3}

    def test_must_cite_true_and_a_named_check_both_survive(self, tmp_path):
        """`true` reduces to the wildcard, which is a check name like any
        other, so the union is over what `_read_must_cite` says and not
        over the spelling a skill happened to use."""
        composed = compose_manifests([
            skill(tmp_path, "first", grounding={"must_cite": True}),
            skill(tmp_path, "second", grounding={"must_cite": {"claims": 2}}),
        ])
        assert composed.grounding["must_cite"] == {"*": 1, "claims": 2}

    def test_one_check_with_two_floors_is_a_refusal(self, tmp_path):
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([
                skill(tmp_path, "first", grounding={"must_cite": {"claims": 2}}),
                skill(tmp_path, "second", grounding={"must_cite": {"claims": 5}}),
            ])
        message = str(exc.value)
        assert "must_cite" in message and "claims" in message

    def test_planes_union_by_name(self, tmp_path):
        composed = compose_manifests([
            skill(tmp_path, "first", grounding={"planes": {
                "sdk": {"tools": ["mcp.run_python_code"],
                        "claims": ["I used the SDK"]}}}),
            skill(tmp_path, "second", grounding={"planes": {
                "catalog": {"tools": ["catalog_*"],
                            "claims": ["I searched the catalogue"]}}}),
        ])
        assert sorted(composed.grounding["planes"]) == ["catalog", "sdk"]

    def test_one_plane_name_over_two_tool_sets_refuses_naming_both(
            self, tmp_path):
        """A plane name is what a report says and what a claim phrase is
        recognised under. Two skills declaring one name over different
        tools have declared two planes and given them one word, and
        whichever lost would fail every claim about it."""
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([
                skill(tmp_path, "first", grounding={"planes": {
                    "sdk": {"tools": ["mcp.run_python_code"],
                            "claims": ["I used the SDK"]}}}),
                skill(tmp_path, "second", grounding={"planes": {
                    "sdk": {"tools": ["acme_sdk_call"],
                            "claims": ["I used the SDK"]}}}),
            ])
        message = str(exc.value)
        assert "planes: sdk" in message
        assert "'first'" in message and "'second'" in message

    def test_the_same_plane_declared_twice_identically_is_not_a_conflict(
            self, tmp_path):
        """Two skills of one family legitimately both describe the plane
        they share, and refusing that would make the family unusable."""
        plane = {"sdk": {"tools": ["mcp.run_python_code"],
                         "claims": ["I used the SDK"]}}
        composed = compose_manifests([
            skill(tmp_path, "first", grounding={"planes": plane}),
            skill(tmp_path, "second", grounding={"planes": plane}),
        ])
        assert list(composed.grounding["planes"]) == ["sdk"]

    def test_a_block_that_does_not_stand_up_alone_is_named_as_such(
            self, tmp_path):
        """Its own reason, not a stranger complaint about a merged mapping
        nobody wrote."""
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([
                skill(tmp_path, "first", grounding={"ignore": ["dead"]}),
                skill(tmp_path, "second", grounding={"identifier_patern": "x"}),
            ])
        message = str(exc.value)
        assert "'second'" in message and "unknown key" in message

    def test_the_merged_block_is_validated_at_compose_time(self, tmp_path):
        """The merge can produce a block no skill wrote. Two skills each
        scope `figures_from` to their own `number_pattern`; the patterns
        disagree so neither survives, and what is left is a figure scope
        over a check that is switched off — which
        `GroundingConfig.from_mapping` refuses, and it is asked here so
        the refusal arrives at the door rather than at the end of an
        11,000-second mission."""
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([
                skill(tmp_path, "first", grounding={
                    "number_pattern": r"\d+%", "figures_from": ["verify"]}),
                skill(tmp_path, "second", grounding={
                    "number_pattern": r"\d+s", "figures_from": ["measure"]}),
            ])
        message = str(exc.value)
        assert "number_pattern" in message
        assert "figures_from` without a `number_pattern" in message


class TestTheSdkName:
    def test_one_declared_name_is_carried(self, tmp_path):
        composed = compose_manifests([
            skill(tmp_path, "first"),
            skill(tmp_path, "second", sdk_import="acme"),
        ])
        assert composed.sdk_import == "acme"

    def test_the_same_name_twice_is_not_a_conflict(self, tmp_path):
        composed = compose_manifests([
            skill(tmp_path, "first", sdk_import="acme"),
            skill(tmp_path, "second", sdk_import="acme"),
        ])
        assert composed.sdk_import == "acme"

    def test_nobody_naming_one_composes_to_no_rung(self, tmp_path):
        """Undeclared withholds the `code+sdk` rung rather than offering
        it with a blank where the module goes, and composition must not
        invent one."""
        assert compose_manifests([
            skill(tmp_path, "first"), skill(tmp_path, "second"),
        ]).sdk_import == ""

    def test_two_different_names_are_a_refusal(self, tmp_path):
        """The sentence that offers a code step the platform's own module
        names one module. A sentence naming two is a sentence the model
        writes wrong, and a 20B accepts every invitation to invent."""
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([
                skill(tmp_path, "first", sdk_import="acme"),
                skill(tmp_path, "second", sdk_import="other"),
            ])
        message = str(exc.value)
        assert "acme" in message and "other" in message


class TestTheSandboxTakesTheStrictestAsk:
    def test_bwrap_anywhere_wins(self, tmp_path):
        composed = compose_manifests([
            skill(tmp_path, "first", allowed_tools=["run_shell_command"],
                  sandbox="bwrap"),
            skill(tmp_path, "second", sandbox="none"),
        ])
        assert composed.sandbox == "bwrap"

    def test_and_the_code_plane_gate_is_re_run_over_the_union(self, tmp_path):
        """Belt and braces, and the belt is what this asserts: the
        composed manifest still carries the code-plane tool, and still
        passes the gate, so the check ran over something rather than over
        an empty set."""
        composed = compose_manifests([
            skill(tmp_path, "first", allowed_tools=["run_shell_command"],
                  sandbox="bwrap"),
            skill(tmp_path, "second", sandbox="none"),
        ])
        assert [entry for entry, _tool, _scopes
                in composed.code_plane_entries()] == ["run_shell_command"]

    def test_none_survives_when_nobody_asked_for_isolation(self, tmp_path):
        composed = compose_manifests([
            skill(tmp_path, "first"),
            skill(tmp_path, "second", sandbox="none"),
        ])
        assert composed.sandbox == "none"

    def test_silence_stays_silence(self, tmp_path):
        """Absent is not `none`. Absent is nobody having said anything,
        and turning it into a statement would make a manifest claim
        something its author never wrote."""
        assert compose_manifests([
            skill(tmp_path, "first"), skill(tmp_path, "second"),
        ]).sandbox == ""


class TestTheSameSkillTwice:
    def test_one_file_listed_twice_is_a_refusal_not_a_dedup(self, tmp_path):
        """Silently de-duplicating would make this a typo nobody finds:
        the second copy contributes nothing, so the run would be exactly
        the single-skill run the operator believed they had left."""
        one = skill(tmp_path, "solo")
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([one, one])
        assert "listed twice" in str(exc.value)

    def test_the_refusal_names_the_file(self, tmp_path):
        one = skill(tmp_path, "solo")
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([one, one])
        assert str(one.source) in str(exc.value)

    def test_two_different_files_of_one_name_are_a_refusal(self, tmp_path):
        """A pack name and a path can reach two manifests calling
        themselves the same thing. Every refusal and every memory bank
        names a skill by that one word, so two of them is one being talked
        about and the other one silently not."""
        first = skill(tmp_path / "a", "twin")
        second = skill(tmp_path / "b", "twin")
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([first, second])
        assert "both called 'twin'" in str(exc.value)


class TestEveryProblemArrivesInOneMessage:
    def test_three_disagreements_are_three_lines(self, tmp_path):
        """The module's idiom, and the reason for it: composing skills is
        something an operator does at a command line and gets wrong at a
        command line, and a refusal arriving one problem at a time is
        fixed one problem at a time."""
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([
                skill(tmp_path, "first", sdk_import="acme", grounding={
                    "max_repairs": 1,
                    "planes": {"sdk": {"tools": ["a"], "claims": ["I"]}}}),
                skill(tmp_path, "second", sdk_import="other", grounding={
                    "max_repairs": 4,
                    "planes": {"sdk": {"tools": ["b"], "claims": ["I"]}}}),
            ])
        message = str(exc.value)
        assert "acme" in message
        assert "max_repairs" in message
        assert "planes: sdk" in message


# ── the flag that reaches it ─────────────────────────────────────────────────


class TestTheRepeatableFlag:
    """`--skill` at the command line, down to `_load_skill`.

    The trap this class exists for is argparse's: an `append` action APPENDS
    to its default, so a `default=` read from the environment would give an
    operator who typed one skill a run under two — one of them a skill they
    had forgotten was in their shell. `MISSION_SKILL` is therefore read in
    `_skill_values`, where a typed flag wins outright.
    """

    def parser(self):
        from tests.test_contract import _mission_parser

        return _mission_parser()

    def test_the_flag_repeats_into_a_list(self, tmp_path):
        args = self.parser().parse_args(
            ["go", "--skill", "a/SKILL.md", "--skill", "b/SKILL.md"])
        assert [str(p) for p in args.skill] == ["a/SKILL.md", "b/SKILL.md"]

    def test_one_value_is_still_a_list_of_one(self, tmp_path):
        args = self.parser().parse_args(["go", "--skill", "a/SKILL.md"])
        assert [str(p) for p in args.skill] == ["a/SKILL.md"]

    def test_no_flag_and_no_variable_is_no_skill(self, monkeypatch):
        from core import cli

        monkeypatch.delenv("MISSION_SKILL", raising=False)
        assert cli._load_skill(self.parser().parse_args(["go"])) is None

    def test_two_flags_reach_load_skill_and_compose(self, tmp_path,
                                                    monkeypatch):
        from core import cli

        monkeypatch.delenv("MISSION_SKILL", raising=False)
        first = skill(tmp_path, "first", allowed_tools=["alpha"])
        second = skill(tmp_path, "second", allowed_tools=["beta"])
        args = self.parser().parse_args(
            ["go", "--skill", str(first.source), "--skill", str(second.source)])
        manifest = cli._load_skill(args)
        assert manifest.name == "first"
        assert manifest.allowed_tools == ("alpha", "beta")
        assert manifest.composed == ("first", "second")

    def test_one_flag_loads_exactly_what_it_always_did(self, tmp_path,
                                                       monkeypatch):
        from core import cli

        monkeypatch.delenv("MISSION_SKILL", raising=False)
        one = skill(tmp_path, "solo")
        args = self.parser().parse_args(["go", "--skill", str(one.source)])
        loaded = cli._load_skill(args)
        assert (loaded.name, loaded.prompt, loaded.composed) == (
            "solo", one.prompt, ())

    def test_the_variable_splits_on_the_path_separator(self, tmp_path,
                                                       monkeypatch):
        from core import cli

        first = skill(tmp_path, "first", allowed_tools=["alpha"])
        second = skill(tmp_path, "second", allowed_tools=["beta"])
        monkeypatch.setenv(
            "MISSION_SKILL",
            os.pathsep.join([str(first.source), str(second.source)]))
        manifest = cli._load_skill(self.parser().parse_args(["go"]))
        assert manifest.composed == ("first", "second")

    def test_one_path_in_the_variable_is_one_skill(self, tmp_path,
                                                   monkeypatch):
        """What `MISSION_SKILL` has always meant, unchanged."""
        from core import cli

        one = skill(tmp_path, "solo")
        monkeypatch.setenv("MISSION_SKILL", str(one.source))
        loaded = cli._load_skill(self.parser().parse_args(["go"]))
        assert (loaded.name, loaded.composed) == ("solo", ())

    def test_a_typed_flag_wins_over_the_variable_rather_than_adding_to_it(
            self, tmp_path, monkeypatch):
        """The argparse trap, asserted. An operator who typed one skill
        gets one skill, whatever is exported in their shell."""
        from core import cli

        typed = skill(tmp_path, "typed")
        exported = skill(tmp_path, "exported")
        monkeypatch.setenv("MISSION_SKILL", str(exported.source))
        args = self.parser().parse_args(["go", "--skill", str(typed.source)])
        loaded = cli._load_skill(args)
        assert (loaded.name, loaded.composed) == ("typed", ())

    def test_a_refusal_to_compose_is_a_systemexit_naming_the_flag(
            self, tmp_path, monkeypatch):
        """The same treatment every bad flag gets: an operator who named
        two skills and got a run under one would get a plausible answer
        from a mission holding half the knowledge they meant to supply."""
        from core import cli

        monkeypatch.delenv("MISSION_SKILL", raising=False)
        first = skill(tmp_path, "first", sdk_import="acme")
        second = skill(tmp_path, "second", sdk_import="other")
        args = self.parser().parse_args(
            ["go", "--skill", str(first.source), "--skill", str(second.source)])
        with pytest.raises(SystemExit) as exc:
            cli._load_skill(args)
        assert "--skill:" in str(exc.value)

    def test_the_run_metadata_records_every_skill_it_ran_under(
            self, tmp_path, monkeypatch):
        """A run directory outlives the process, and *which skills* is the
        first thing a reader of one asks. The environment form is no
        longer an argparse default, so the index has to be built from the
        same resolution the loader used or a run started from
        `MISSION_SKILL` alone would file itself as having had none."""
        from core import cli

        one = skill(tmp_path, "solo")
        monkeypatch.setenv("MISSION_SKILL", str(one.source))
        flags = cli._run_meta_flags(self.parser().parse_args(["go"]))
        assert [str(p) for p in flags["skill"]] == [str(one.source)]

    def test_a_campaign_takes_the_primarys_pack_name(self, tmp_path,
                                                     monkeypatch):
        """`_campaign_packs` gives a step one persona and one pack's
        templates, and the pack a composed mission belongs to is the one
        whose name and answer shape it carries."""
        from core import cli

        monkeypatch.delenv("MISSION_SKILL", raising=False)
        args = self.parser().parse_args(
            ["go", "--skill", "analyst", "--skill", "research"])
        _templates, packs = cli._campaign_packs(args, "tai")
        assert list(packs) == ["analyst"]


class TestTheReportNamesEverySkill:
    def test_the_line_leads_with_the_primary(self, tmp_path):
        """The `📜 skill` line is what an operator reads to check they got
        the run they asked for, and a composed run that named one of three
        skills would leave the other two to be inferred from a prompt
        nobody prints."""
        composed = compose_manifests([
            skill(tmp_path, "first"), skill(tmp_path, "second"),
        ])
        line = (f"📜 skill {composed.name}"
                + (f" + {', '.join(composed.composed[1:])}"
                   if composed.composed else ""))
        assert line == "📜 skill first + second"


def test_the_module_docstring_says_composition_has_one_owner():
    """One owner per fact, asserted where a second implementation would be
    written: a platform embedding the library that unioned the tools its
    own way would produce transcripts that look exactly like these."""
    import core.runtime.skills as module

    assert "compose_manifests" in textwrap.dedent(module.__doc__)
