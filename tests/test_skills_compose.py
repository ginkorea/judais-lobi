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
    SkillToolsUnavailable,
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
        silently narrowed closed set is, arrived at a different way.

        The names are deliberately NOT in alphabetical order: the order a
        skill author chose is the order the catalogue is read in, and a
        fixture that happened to be sorted would pass against a merge
        that sorted."""
        composed = compose_manifests([
            skill(tmp_path, "first", allowed_tools=["beta", "alpha"]),
            skill(tmp_path, "second", allowed_tools=["alpha", "gamma"]),
        ])
        assert composed.allowed_tools == ("beta", "alpha", "gamma")

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

    def test_a_supporting_exemption_cannot_dig_under_the_wildcard(
            self, tmp_path):
        """THE weakening the review found. `minimum_for` lets an explicit
        name beat the `must_cite: true` wildcard — right inside one skill,
        where the author who wrote both sentences meant the exemption, and
        wrong across two, where nobody wrote both. A primary asking for
        citations generally, composed with a supporting skill that exempts
        figures for its own reasons, would come out citing FEWER things
        than the primary asked for and the report would not say so."""
        from core.runtime.grounding import GroundingConfig

        composed = compose_manifests([
            skill(tmp_path, "first", grounding={"must_cite": True}),
            skill(tmp_path, "second", grounding={"must_cite": {"figures": 0}}),
        ])
        config = GroundingConfig.from_mapping(composed.grounding)
        assert config.minimum_for("figures") == 1

    def test_a_higher_named_minimum_is_left_alone(self, tmp_path):
        """Raised to the floor, never lowered to it: the wildcard is a
        floor and not a setting."""
        from core.runtime.grounding import GroundingConfig

        composed = compose_manifests([
            skill(tmp_path, "first", grounding={"must_cite": True}),
            skill(tmp_path, "second", grounding={"must_cite": {"claims": 3}}),
        ])
        config = GroundingConfig.from_mapping(composed.grounding)
        assert config.minimum_for("claims") == 3

    def test_one_skills_own_exemption_beside_its_own_wildcard_survives(
            self, tmp_path):
        """The other side of the rule, and the reason it is written over
        the DECLARER SET rather than per key. `{"*": 1, figures: 0}` in
        one block is one author saying "cite generally, except this kind,
        which my answers legitimately omit". Raising that would overrule a
        sentence somebody did write, which is the opposite failure."""
        from core.runtime.grounding import GroundingConfig

        composed = compose_manifests([
            skill(tmp_path, "first",
                  grounding={"must_cite": {"*": 1, "figures": 0}}),
            skill(tmp_path, "second", grounding={"ignore": ["dead"]}),
        ])
        config = GroundingConfig.from_mapping(composed.grounding)
        assert config.minimum_for("figures") == 0

    def test_two_skills_both_exempting_it_is_agreement(self, tmp_path):
        """Every skill that set the floor also wrote the exemption, so
        the exemption stands. This is the case the rule has to keep
        working, or "compose skills written to work together" stops being
        possible for a family that agrees about its own figures."""
        from core.runtime.grounding import GroundingConfig

        composed = compose_manifests([
            skill(tmp_path, "first",
                  grounding={"must_cite": {"*": 1, "figures": 0}}),
            skill(tmp_path, "second", grounding={"must_cite": {"figures": 0}}),
        ])
        config = GroundingConfig.from_mapping(composed.grounding)
        assert config.minimum_for("figures") == 0

    @pytest.mark.parametrize("swapped", [False, True], ids=["as-listed",
                                                            "reversed"])
    def test_a_bare_wildcard_does_not_lose_its_floor_to_someone_elses_exemption(
            self, tmp_path, swapped):
        """THE second order-dependence the re-review found. Scoping the
        exemption to the FIRST NAMER looked equivalent to scoping it to
        the declarer set and was not: `{"*": 1, figures: 0}` composed with
        a bare `must_cite: true` gave figures a floor of 0 or of 1
        depending on which was typed first, and in the 0 direction the
        skill that asked for citations generally lost its floor to an
        exemption it had never written.

        Parametrised over both orders on purpose. One order is not
        evidence about an order-dependence bug — it is how the bug got
        through the first time."""
        from core.runtime.grounding import GroundingConfig

        exempting = skill(tmp_path, "exempting",
                          grounding={"must_cite": {"*": 1, "figures": 0}})
        just_true = skill(tmp_path, "just_true", grounding={"must_cite": True})
        pair = [just_true, exempting] if swapped else [exempting, just_true]
        config = GroundingConfig.from_mapping(
            compose_manifests(pair).grounding)
        assert config.minimum_for("figures") == 1

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

    def test_a_shared_plane_restated_in_another_order_composes(self, tmp_path):
        """A skill family restates the plane its members share, and two
        authors — or one author on two days — write the tools in another
        order and another naming convention. Comparing the TEXT refused
        that, over a difference that is not one, with no fix short of
        editing somebody else's manifest to match your typing. Membership
        is what is compared: tools by `tool_key`, claims casefolded."""
        composed = compose_manifests([
            skill(tmp_path, "first", grounding={"planes": {"sdk": {
                "tools": ["mcp.run_python_code", "acme.sdk_call"],
                "claims": ["I used the SDK", "I recomputed"]}}}),
            skill(tmp_path, "second", grounding={"planes": {"sdk": {
                "tools": ["acme_sdk_call", "mcp_run_python_code"],
                "claims": ["i recomputed", "i used the sdk"]}}}),
        ])
        assert list(composed.grounding["planes"]) == ["sdk"]

    def test_genuinely_different_membership_still_refuses(self, tmp_path):
        """The refusal has to survive the loosening, or the loosening is
        just a removal. One extra tool is different membership."""
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([
                skill(tmp_path, "first", grounding={"planes": {"sdk": {
                    "tools": ["mcp.run_python_code"],
                    "claims": ["I used the SDK"]}}}),
                skill(tmp_path, "second", grounding={"planes": {"sdk": {
                    "tools": ["mcp.run_python_code", "acme_sdk_call"],
                    "claims": ["I used the SDK"]}}}),
            ])
        assert "planes: sdk" in str(exc.value)

    def test_a_family_and_a_single_tool_of_that_name_are_not_one_plane(
            self, tmp_path):
        """`tool_key("catalog_*")` and `tool_key("catalog")` are the same
        string, and to `plane_matches` they are nothing like the same
        thing: `catalog_*` is every catalogue tool a server advertises,
        `catalog` is one tool called catalog. Folding them let the two
        compose without a word, and then LISTING ORDER decided whether
        `catalog_search_assets` was on the plane — the code-plane gate's
        order-dependence, one field over."""
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([
                skill(tmp_path, "first", grounding={"planes": {"catalog": {
                    "tools": ["catalog_*"], "claims": ["I searched"]}}}),
                skill(tmp_path, "second", grounding={"planes": {"catalog": {
                    "tools": ["catalog"], "claims": ["I searched"]}}}),
            ])
        assert "planes: catalog" in str(exc.value)

    def test_and_that_holds_the_other_way_round(self, tmp_path):
        """Both orders, or the assertion is about which one was read
        first rather than about the two specs being different."""
        with pytest.raises(SkillManifestError):
            compose_manifests([
                skill(tmp_path, "first", grounding={"planes": {"catalog": {
                    "tools": ["catalog"], "claims": ["I searched"]}}}),
                skill(tmp_path, "second", grounding={"planes": {"catalog": {
                    "tools": ["catalog_*"], "claims": ["I searched"]}}}),
            ])

    def test_two_spellings_of_one_family_are_still_one_family(self, tmp_path):
        """The loosening has to survive the fix: a family written in two
        conventions is one family, and only the `*` is being kept out of
        the reduction."""
        composed = compose_manifests([
            skill(tmp_path, "first", grounding={"planes": {"catalog": {
                "tools": ["catalog_*"], "claims": ["I searched"]}}}),
            skill(tmp_path, "second", grounding={"planes": {"catalog": {
                "tools": ["catalog.*"], "claims": ["I searched"]}}}),
        ])
        assert list(composed.grounding["planes"]) == ["catalog"]

    def test_a_grounding_block_of_only_false_bools_is_still_a_block(
            self, tmp_path):
        """`grounding: {claim_table: false}` is a declaration. Dropping the
        false key left the merged mapping empty, `merged or None` turned
        that into *no grounding grammar at all*, and a composition where
        nobody asked for anything to change lost its validator — and the
        console line said so. Declared is declared."""
        from core.runtime.grounding import GroundingConfig

        composed = compose_manifests([
            skill(tmp_path, "first", grounding={"claim_table": False}),
            skill(tmp_path, "second"),
        ])
        assert composed.grounding["claim_table"] is False
        assert GroundingConfig.from_mapping(composed.grounding) is not None

    def test_an_empty_grounding_block_is_a_declaration_too(self, tmp_path):
        """`grounding: {}` builds a validator with no opinion for a single
        skill — `from_mapping({})` is a config, `from_mapping(None)` is
        `None`, and those are different answers. Composition must not swap
        one for the other on its way through an empty merged mapping."""
        from core.runtime.grounding import GroundingConfig

        composed = compose_manifests([
            skill(tmp_path, "first", grounding={}),
            skill(tmp_path, "second"),
        ])
        assert composed.grounding is not None
        assert GroundingConfig.from_mapping(composed.grounding) is not None

    def test_an_empty_must_cite_survives_as_an_empty_must_cite(
            self, tmp_path):
        """THE case the reference deployment found, composing 13 skills.

        Every input declared `must_cite: {}` — an empty floor, written on
        purpose. One skill returned the manifest unchanged and
        `"must_cite" in grounding` was True; two skills composed and the
        union of nothing dropped the key, so it was False. A consumer that
        switches on key presence turns its check off the moment a second
        skill is added to the line, and the only sign of it is a shape
        change nothing reports."""
        composed = compose_manifests([
            skill(tmp_path, "first", grounding={"must_cite": {}}),
            skill(tmp_path, "second", grounding={"must_cite": {}}),
        ])
        assert "must_cite" in composed.grounding
        assert composed.grounding["must_cite"] == {}

    def test_an_empty_must_cite_still_reads_back_to_no_floor(self, tmp_path):
        """The value may change — `{}` where a skill wrote `{}` or
        `false` — and what it MEANS may not. `_read_must_cite` reads the
        emitted `{}` back to the same no-floor it read the original to."""
        from core.runtime.grounding import GroundingConfig

        composed = compose_manifests([
            skill(tmp_path, "first", grounding={"must_cite": {}}),
            skill(tmp_path, "second", grounding={"must_cite": False}),
        ])
        config = GroundingConfig.from_mapping(composed.grounding)
        assert config.must_cite == ()
        assert config.minimum_for("identifiers") == 0

    @pytest.mark.parametrize("key", ["ignore", "figures_from"])
    def test_a_declared_empty_list_survives_as_an_empty_list(
            self, tmp_path, key):
        """Same defect, same shape, one field over: the union of two empty
        lists is empty, and `if union:` dropped the key that both skills
        had written down."""
        composed = compose_manifests([
            skill(tmp_path, "first", grounding={key: []}),
            skill(tmp_path, "second", grounding={key: []}),
        ])
        assert composed.grounding[key] == []

    def test_a_declared_empty_planes_block_survives(self, tmp_path):
        composed = compose_manifests([
            skill(tmp_path, "first", grounding={"planes": {}}),
            skill(tmp_path, "second", grounding={"planes": {}}),
        ])
        assert composed.grounding["planes"] == {}

    def test_an_explicit_null_scalar_is_a_declaration_and_not_a_silence(
            self, tmp_path):
        """`identifier_pattern: null` carries no opinion, and that is not
        the same as never having written the key. It is not COMPARED —
        a null cannot disagree with a grammar, and refusing over one would
        refuse a composition over nothing — and it is not DROPPED either,
        because somebody typed it."""
        composed = compose_manifests([
            skill(tmp_path, "first", grounding={"identifier_pattern": None}),
            skill(tmp_path, "second", grounding={"identifier_pattern": None}),
        ])
        assert "identifier_pattern" in composed.grounding
        assert composed.grounding["identifier_pattern"] is None

    def test_a_null_scalar_yields_to_a_skill_that_stated_one(self, tmp_path):
        """Presence is preserved; the VALUE still comes from whoever had
        an opinion. A null beside a grammar is not a disagreement."""
        composed = compose_manifests([
            skill(tmp_path, "first", grounding={"identifier_pattern": None}),
            skill(tmp_path, "second",
                  grounding={"identifier_pattern": r"\bacme\.\w+\b"}),
        ])
        assert composed.grounding["identifier_pattern"] == r"\bacme\.\w+\b"

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


#: One clause, and the same clause written in a second YAML style. Two
#: authors of a skill family restate the rule they share, and a merge that
#: compared what was TYPED would refuse a composition over a difference
#: that is not one.
CONTROLS = {"name": "controls",
            "head": ["?a", "controls", "?c"],
            "body": [["?a", "admin_access", "?c"],
                     ["?a", "payment_link", "?c"]]}
CONTROLS_RESTATED = {"name": "controls",
                     "head": ("?a", "controls", "?c"),
                     "body": (("?a", "admin_access", "?c"),
                              ("?a", "payment_link", "?c"))}
#: The same NAME over different content — the conflict.
CONTROLS_OTHER = {"name": "controls",
                  "head": ["?a", "controls", "?c"],
                  "body": [["?a", "billing_access", "?c"]]}


class TestTheRulePackMerges:
    """`cognition:` composes like everything else a mission has several of.

    `rules` and `goals` are named things and they UNION: two skills that
    each bring clauses bring both, because a pack is not a setting to be
    chosen between. `cardinality` is the scalar discipline one field at a
    time — a field carries one value or many for the whole store, the
    kernel will hold only one answer about it, and choosing between two
    would switch collision detection off for whichever skill lost while
    the store went on reporting no disagreement.

    The refusal is the half that matters, as everywhere else in this file:
    a name silently resolved by taking the first makes which clause a
    mission derives under a fact about the order the skills were typed in.
    """

    def test_rules_union_by_name(self, tmp_path):
        composed = compose_manifests([
            skill(tmp_path, "first", cognition={"rules": [CONTROLS]}),
            skill(tmp_path, "second", cognition={"rules": [
                {"name": "paid", "head": ["?a", "paid", True],
                 "body": [["?a", "amount", 0]]}]}),
        ])
        assert [rule["name"] for rule in composed.cognition["rules"]] \
            == ["controls", "paid"]

    def test_goals_union_by_name(self, tmp_path):
        composed = compose_manifests([
            skill(tmp_path, "first", cognition={"goals": [
                {"name": "owner_known", "pattern": ["?a", "controls", "?c"]}]}),
            skill(tmp_path, "second", cognition={"goals": [
                {"name": "settled", "pattern": ["?a", "paid", True]}]}),
        ])
        assert [goal["name"] for goal in composed.cognition["goals"]] \
            == ["owner_known", "settled"]

    def test_an_identical_redeclaration_is_deduplicated(self, tmp_path):
        """A family restating the clause it shares. Two skills that both
        know a rule both still know it, and the mission derives under one
        copy of it rather than two rule ids concluding the same thing."""
        composed = compose_manifests([
            skill(tmp_path, "first", cognition={"rules": [CONTROLS]}),
            skill(tmp_path, "second", cognition={"rules": [dict(CONTROLS)]}),
        ])
        assert len(composed.cognition["rules"]) == 1

    def test_a_clause_restated_in_another_shape_is_the_same_clause(self):
        """The library caller's half, and the one that needs `_canonical`:
        a platform composing in-process builds its blocks in Python, where
        a pattern may be a tuple, and a merge comparing container types
        would refuse a composition over a difference that is not one."""
        one = SkillManifest(name="first", allowed_tools=("alpha",),
                            prompt="a", cognition={"rules": [CONTROLS]})
        two = SkillManifest(name="second", allowed_tools=("alpha",),
                            prompt="b",
                            cognition={"rules": [CONTROLS_RESTATED]})
        assert len(compose_manifests([one, two]).cognition["rules"]) == 1

    def test_one_name_over_two_clauses_is_a_refusal_naming_both(self,
                                                                tmp_path):
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([
                skill(tmp_path, "first", cognition={"rules": [CONTROLS]}),
                skill(tmp_path, "second",
                      cognition={"rules": [CONTROLS_OTHER]}),
            ])
        message = str(exc.value)
        assert "'controls'" in message
        assert "'first'" in message and "'second'" in message

    def test_one_goal_name_over_two_targets_is_a_refusal(self, tmp_path):
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([
                skill(tmp_path, "first", cognition={"goals": [
                    {"name": "done", "pattern": ["?a", "paid", True]}]}),
                skill(tmp_path, "second", cognition={"goals": [
                    {"name": "done", "pattern": ["?a", "shipped", True]}]}),
            ])
        assert "'done'" in str(exc.value)

    def test_cardinality_agrees_and_is_carried(self, tmp_path):
        composed = compose_manifests([
            skill(tmp_path, "first", cognition={"cardinality": {"units": "one"}}),
            skill(tmp_path, "second",
                  cognition={"cardinality": {"units": "one", "score": "many"}}),
        ])
        assert composed.cognition["cardinality"] == {"units": "one",
                                                     "score": "many"}

    def test_cardinality_that_disagrees_is_a_refusal_naming_both(self,
                                                                 tmp_path):
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([
                skill(tmp_path, "first",
                      cognition={"cardinality": {"units": "one"}}),
                skill(tmp_path, "second",
                      cognition={"cardinality": {"units": "many"}}),
            ])
        message = str(exc.value)
        assert "units" in message
        assert "'first'" in message and "'second'" in message

    def test_silence_yields_rather_than_disagreeing(self, tmp_path):
        """A skill that never mentioned a field has no opinion about it,
        and a merge that read absence as `many` would refuse a family
        where one member declares what the others never thought about."""
        composed = compose_manifests([
            skill(tmp_path, "first", cognition={"cardinality": {"units": "one"}}),
            skill(tmp_path, "second", cognition={"rules": [CONTROLS]}),
        ])
        assert composed.cognition["cardinality"] == {"units": "one"}

    def test_a_skill_with_no_block_contributes_nothing(self, tmp_path):
        composed = compose_manifests([
            skill(tmp_path, "first", cognition={"rules": [CONTROLS]}),
            skill(tmp_path, "second"),
        ])
        assert [rule["name"] for rule in composed.cognition["rules"]] \
            == ["controls"]

    def test_nobody_declaring_one_composes_to_none(self, tmp_path):
        """`None` is *nobody asked for cognition*, and it is not the same
        answer as an empty pack — the shadow loads one and not the other."""
        assert compose_manifests([
            skill(tmp_path, "first"), skill(tmp_path, "second"),
        ]).cognition is None

    @pytest.mark.parametrize("key,empty", [
        ("cardinality", {}), ("rules", []), ("goals", []),
    ])
    def test_a_key_declared_empty_survives_as_declared_empty(
            self, tmp_path, key, empty):
        """The 1.1.1 invariant, on the second block that has one:
        composition may change a value, never a declared key's presence.
        A consumer switching on `"rules" in block` must not get a different
        answer because a second skill joined the line."""
        composed = compose_manifests([
            skill(tmp_path, "first", cognition={key: empty}),
            skill(tmp_path, "second", cognition={key: empty}),
        ])
        assert key in composed.cognition

    @pytest.mark.parametrize("key,empty", [
        ("cardinality", {}), ("rules", []), ("goals", []),
    ])
    def test_a_key_nobody_declared_is_not_invented(self, tmp_path, key, empty):
        composed = compose_manifests([
            skill(tmp_path, "first", cognition={"rules": [CONTROLS]}),
            skill(tmp_path, "second", cognition={"rules": [CONTROLS]}),
        ])
        if key != "rules":
            assert key not in composed.cognition

    def test_a_block_that_does_not_stand_up_alone_names_its_own_skill(self):
        """Hand-built, because a manifest off disk never gets this far —
        `load_skill` refuses it at the file. A platform composing in
        process has no such door, and the refusal has to say WHICH skill
        to open: a fault reported under the primary's name sends an
        operator to the wrong file, which is the argument `describe()`
        was written for."""
        good = SkillManifest(name="first", allowed_tools=("alpha",),
                             prompt="a", cognition={"rules": [CONTROLS]})
        bad = SkillManifest(name="second", allowed_tools=("alpha",),
                            prompt="b", cognition={"rules": [
                                {"name": "loose",
                                 "head": ["?a", "owns", "?x"],
                                 "body": [["?a", "paid", True]]}]})
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([good, bad])
        message = str(exc.value)
        assert "'second'" in message
        assert "?x" in message

    def test_the_merged_block_carries_only_what_stood_up(self):
        """And the composition goes on being computed, so the refusal
        names every problem rather than the first — the module's idiom,
        and the reason a merge collects rather than raises."""
        good = SkillManifest(name="first", allowed_tools=("alpha",),
                             prompt="a", cognition={"rules": [CONTROLS]})
        bad = SkillManifest(name="second", allowed_tools=("alpha",),
                            prompt="b", cognition={"cardinality": "nope"})
        worse = SkillManifest(name="third", allowed_tools=("alpha",),
                              prompt="c", cognition={"goals": [{"name": "g"}]})
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([good, bad, worse])
        message = str(exc.value)
        assert "'second'" in message and "'third'" in message

    def test_the_problems_in_one_pack_are_one_per_line(self):
        """A separator the messages never use. Several of them carry a
        semicolon of their own — the kernel's `'two' is not a cardinality;
        'one' or 'many'` among them — so a list joined on `"; "` is three
        faults arriving as six half-sentences."""
        bad = SkillManifest(name="second", allowed_tools=("alpha",),
                            prompt="b", cognition={
                                "nonsense": 1, "cardinality": {"u": "two"}})
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([
                SkillManifest(name="first", allowed_tools=("alpha",),
                              prompt="a", cognition={"rules": [CONTROLS]}),
                bad,
            ])
        lines = [line.strip() for line in str(exc.value).splitlines()
                 if line.strip().startswith("- ")]
        assert any(line.startswith("- unknown key(s): nonsense")
                   for line in lines), lines
        assert any(line.startswith("- `cardinality: u` is 'two'")
                   for line in lines), lines

    def test_the_composed_pack_loads_into_a_kernel(self, tmp_path):
        """The end of the merge is a pack, and a pack's whole purpose is
        to be written into a store. Asserted here rather than left to the
        shadow tests, because a merge that produced a mapping the reader
        takes and the kernel does not would pass every test above."""
        from core.cognition import CognitiveState
        from core.runtime.cognition import RulePack

        composed = compose_manifests([
            skill(tmp_path, "first", cognition={
                "cardinality": {"amount": "one"}, "rules": [CONTROLS]}),
            skill(tmp_path, "second", cognition={"goals": [
                {"name": "owner_known",
                 "pattern": ["?a", "controls", "?c"]}]}),
        ])
        state = CognitiveState()
        assert RulePack.from_mapping(composed.cognition).load_into(state) \
            == (1, 1, 1)


#: One tool, declared by a skill that knows about jobs.
DISCOVERY = {"name": "narrative_discovery",
             "identifiers": {"job_id": {"kind": "job"}},
             "establishes": ["job_id"],
             "produces": [{"kind": "asset", "field": "label_set_asset_id",
                           "via": "job_status", "on": "job_id"}]}

#: The same tool, as a sibling skill knows it: more that it establishes,
#: and nothing that contradicts.
DISCOVERY_MORE = {"name": "narrative_discovery",
                  "identifiers": {"corpus_asset_id": {"kind": "asset"}},
                  "establishes": ["corpus_asset_id"]}


class TestThePlaneDeclarationsMerge:
    """`tools:` composes like everything else a mission has several of.

    A family of skills shares one plane, so they declare overlapping parts
    of it: entries union by tool, `establishes` and `produces` union, and
    every place two skills could mean different things by one word — an
    identifier's kind, a product's chain, a fallback shape — agrees or is
    a refusal naming both. Taking the first would make which subject a
    value identifies a fact about the order two skills were typed in, and
    a wrong identifier is the one declaration that manufactures evidence.
    """

    def test_entries_union_by_tool(self, tmp_path):
        composed = compose_manifests([
            skill(tmp_path, "first", tools={"entries": [DISCOVERY]}),
            skill(tmp_path, "second", tools={"entries": [
                {"name": "runs_get",
                 "identifiers": {"run_id": {"kind": "run"}}}]}),
        ])
        assert [entry["name"] for entry in composed.tools["entries"]] \
            == ["narrative_discovery", "runs_get"]

    def test_one_tool_declared_by_two_skills_merges_per_verb(self, tmp_path):
        composed = compose_manifests([
            skill(tmp_path, "first", tools={"entries": [DISCOVERY]}),
            skill(tmp_path, "second", tools={"entries": [DISCOVERY_MORE]}),
        ])
        entry = composed.tools["entries"][0]
        assert entry["identifiers"] == {"corpus_asset_id": {"kind": "asset"},
                                        "job_id": {"kind": "job"}}
        assert entry["establishes"] == ["corpus_asset_id", "job_id"]
        assert len(entry["produces"]) == 1

    def test_two_kinds_for_one_key_is_a_refusal_naming_both(self, tmp_path):
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([
                skill(tmp_path, "first", tools={"entries": [DISCOVERY]}),
                skill(tmp_path, "second", tools={"entries": [
                    {"name": "narrative_discovery",
                     "identifiers": {"job_id": {"kind": "run"}}}]}),
            ])
        message = str(exc.value)
        assert "'job_id'" in message
        assert "'first'" in message and "'second'" in message

    def test_two_kinds_for_one_plane_default_is_a_refusal(self, tmp_path):
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([
                skill(tmp_path, "first", tools={"defaults": {"identifiers": {
                    "result_ref": {"kind": "result"}}}}),
                skill(tmp_path, "second", tools={"defaults": {"identifiers": {
                    "result_ref": {"kind": "asset"}}}}),
            ])
        assert "'result_ref'" in str(exc.value)

    def test_one_product_arriving_two_ways_is_a_refusal(self, tmp_path):
        """A hint pointing at two calls is a hint nobody can follow."""
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([
                skill(tmp_path, "first", tools={"entries": [DISCOVERY]}),
                skill(tmp_path, "second", tools={"entries": [
                    {"name": "narrative_discovery",
                     "identifiers": {"job_id": {"kind": "job"}},
                     "produces": [{"kind": "asset",
                                   "field": "label_set_asset_id",
                                   "via": "runs_get", "on": "job_id"}]}]}),
            ])
        assert "label_set_asset_id" in str(exc.value)

    def test_an_identical_redeclaration_is_deduplicated(self, tmp_path):
        """A family restating the part of the plane it shares."""
        composed = compose_manifests([
            skill(tmp_path, "first", tools={"entries": [DISCOVERY]}),
            skill(tmp_path, "second", tools={"entries": [dict(DISCOVERY)]}),
        ])
        assert len(composed.tools["entries"]) == 1
        assert composed.tools["entries"][0]["establishes"] == ["job_id"]

    def test_two_spellings_of_one_tool_are_one_entry(self, tmp_path):
        """`tool_key`, as everywhere else: an author writes the spelling
        their server advertises and every surface derives the rest."""
        composed = compose_manifests([
            skill(tmp_path, "first", tools={"entries": [DISCOVERY]}),
            skill(tmp_path, "second", tools={"entries": [
                {"name": "mcp.narrative_discovery",
                 "establishes": ["state"]}]}),
        ])
        assert len(composed.tools["entries"]) == 1
        assert composed.tools["entries"][0]["establishes"] == ["job_id",
                                                               "state"]

    def test_the_kept_spelling_is_chosen_by_sorting_not_by_arrival(self,
                                                                   tmp_path):
        """`allowed_tools` keeps the first spelling it sees, and that is
        fine for a set nobody writes down. This block IS written down — into
        `reasoning.jsonl`, read back by a resumed run — so the name comes
        from sorting the declared spellings rather than from which skill
        was typed first."""
        bare = skill(tmp_path / "a", "first", tools={"entries": [DISCOVERY]})
        namespaced = skill(tmp_path / "b", "second", tools={"entries": [
            {"name": "mcp.narrative_discovery", "establishes": ["state"]}]})
        forwards = compose_manifests([bare, namespaced])
        backwards = compose_manifests([namespaced, bare])
        assert forwards.tools["entries"][0]["name"] \
            == backwards.tools["entries"][0]["name"] \
            == "mcp.narrative_discovery"
        assert forwards.tools == backwards.tools

    def test_two_fallback_shapes_for_one_tool_are_a_refusal(self, tmp_path):
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([
                skill(tmp_path, "first", tools={"entries": [
                    {"name": "t", "output_schema": {"type": "object",
                                                    "properties": {"a": {}}}}]}),
                skill(tmp_path, "second", tools={"entries": [
                    {"name": "t", "output_schema": {"type": "object",
                                                    "properties": {"b": {}}}}]}),
            ])
        assert "'first'" in str(exc.value) and "'second'" in str(exc.value)

    def test_a_block_that_does_not_stand_up_alone_is_named(self, tmp_path):
        """A library caller's half: `load_skill` refuses this at the door,
        so only a hand-built manifest reaches the merge with one."""
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([
                SkillManifest(name="first", allowed_tools=("alpha",),
                              prompt="a", tools={"entries": [
                                  {"name": "t",
                                   "identifiers": {"a b": {"kind": "x"}}}]}),
                SkillManifest(name="second", allowed_tools=("alpha",),
                              prompt="b"),
            ])
        assert "'first'" in str(exc.value)

    def test_nobody_declaring_one_composes_to_none(self, tmp_path):
        assert compose_manifests([
            skill(tmp_path, "first"), skill(tmp_path, "second"),
        ]).tools is None

    def test_a_declared_empty_block_survives_composition(self, tmp_path):
        """The key-presence invariant, on this block: `{}` is a skill that
        declared a plane and said nothing about it, `None` is a skill that
        declared none, and a merge that swapped one for the other would
        answer a consumer's `is not None` differently for two skills than
        for one."""
        composed = compose_manifests([
            skill(tmp_path, "first", tools={}),
            skill(tmp_path, "second", tools={}),
        ])
        assert composed.tools == {}

    @pytest.mark.parametrize("key, value", [
        ("defaults", {"identifiers": {}}),
        ("entries", []),
    ])
    def test_a_key_declared_empty_keeps_its_presence(self, tmp_path, key,
                                                     value):
        composed = compose_manifests([
            skill(tmp_path, "first", tools={key: value}),
            skill(tmp_path, "second", tools={}),
        ])
        assert key in composed.tools

    @pytest.mark.parametrize("key", ["defaults", "entries"])
    def test_a_key_nobody_declared_is_not_invented(self, tmp_path, key):
        other = "entries" if key == "defaults" else "defaults"
        composed = compose_manifests([
            skill(tmp_path, "first", tools={other: (
                [] if other == "entries" else {})}),
            skill(tmp_path, "second", tools={}),
        ])
        assert key not in composed.tools

    def test_a_verb_nobody_wrote_is_not_invented_on_an_entry(self, tmp_path):
        composed = compose_manifests([
            skill(tmp_path, "first", tools={"entries": [
                {"name": "t", "establishes": ["verdict"]}]}),
            skill(tmp_path, "second", tools={}),
        ])
        assert set(composed.tools["entries"][0]) == {"name", "establishes"}

    def test_the_merged_block_does_not_depend_on_argument_order(self,
                                                                tmp_path):
        """The property the record depends on. A composed block is written
        into `reasoning.jsonl` and read back by a resumed run, so a block
        that came out differently when two skills were listed the other way
        round would make that record a fact about typing."""
        first = skill(tmp_path / "a", "first", tools={
            "defaults": {"identifiers": {"result_ref": {"kind": "result"}}},
            "entries": [DISCOVERY, {"name": "runs_get",
                                    "establishes": ["verdict"]}]})
        # `asset_fetch` sorts BEFORE the tools the first skill declares, so
        # a merge that kept first-seen order would produce two different
        # lists here and this assertion would be the thing that says so.
        second = skill(tmp_path / "b", "second", tools={
            "defaults": {"identifiers": {"run_ref": {"kind": "run"}}},
            "entries": [{"name": "asset_fetch",
                         "identifiers": {"asset_id": {"kind": "asset"}}},
                        DISCOVERY_MORE]})
        assert compose_manifests([first, second]).tools \
            == compose_manifests([second, first]).tools

    def test_a_family_of_spellings_partitions_the_same_way_round(self,
                                                                 tmp_path):
        """`same_tool` is not an equivalence: `runs_get` matches both
        `mcp.runs_get` and `mcp2.runs_get`, and those two do not match each
        other. A grouping built in arrival order therefore puts this family
        in one group or in two depending on which skill was typed first —
        which is the order of a command line, inside a record a resumed run
        reads back."""
        first = skill(tmp_path / "a", "first", tools={"entries": [
            {"name": "runs_get", "establishes": ["verdict"]}]})
        second = skill(tmp_path / "b", "second", tools={"entries": [
            {"name": "mcp.runs_get", "establishes": ["state"]}]})
        third = skill(tmp_path / "c", "third", tools={"entries": [
            {"name": "mcp2.runs_get", "establishes": ["owner"]}]})
        assert compose_manifests([first, second, third]).tools \
            == compose_manifests([third, second, first]).tools \
            == compose_manifests([second, third, first]).tools

    def test_a_merged_fallback_shape_is_data_and_not_a_frozen_view(self,
                                                                    tmp_path):
        """What comes out of a read block is read-only all the way down;
        what comes out of a MERGE is a raw block a reader, a dump or a JSON
        line may meet next. A read-only proxy in one of those is a string
        nobody can read back."""
        import json

        shape = {"type": "object", "properties": {"a": {"type": "string"}},
                 "required": ["a"]}
        composed = compose_manifests([
            skill(tmp_path / "a", "first", tools={"entries": [
                {"name": "t", "output_schema": shape}]}),
            skill(tmp_path / "b", "second", tools={"entries": [
                {"name": "t", "establishes": ["verdict"]}]}),
        ])
        emitted = composed.tools["entries"][0]["output_schema"]
        assert emitted == shape
        assert json.loads(json.dumps(emitted)) == shape


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

    def test_a_bwrap_composition_keeps_the_code_plane_it_was_given(
            self, tmp_path):
        """Supplementary to the gate tests below, and only that: it says
        the composition still CARRIES the code-plane tool, so those tests
        are refusing over something rather than over an empty set. It is
        not itself evidence that the gate ran."""
        composed = compose_manifests([
            skill(tmp_path, "first", allowed_tools=["run_shell_command"],
                  sandbox="bwrap"),
            skill(tmp_path, "second", sandbox="none"),
        ])
        assert [entry for entry, _tool, _scopes
                in composed.code_plane_entries()] == ["run_shell_command"]


class TestTheCodePlaneGateDoesNotDependOnArgumentOrder:
    """THE class the adversarial review paid for.

    The union deduplicates on `same_tool`, and `mcp.run_shell_command` and
    `run_shell_command` are the same tool to that function — so composing
    a skill that bridges a shell with a skill that runs one HERE collapses
    both to whichever entry was listed first. The bridged spelling is not
    gated (it executes on the server, and bwrap here would isolate nothing
    about it); the local one is. Gate only the composed set and the bridged
    entry swallows the local one, and a governed mission that runs
    arbitrary code on the host with no isolation composes cleanly — in one
    argument order, and refuses in the other.

    A gate whose answer depends on which skill was typed first is not a
    gate. So the declaration half runs over EACH INPUT manifest, under the
    sandbox the composition arrived at.
    """

    def bridged(self, tmp_path):
        """A shell on a discovered SERVER: legal without `sandbox: bwrap`,
        because this host spawns nothing for it."""
        return skill(tmp_path, "bridged",
                     allowed_tools=["mcp.run_shell_command"])

    def local(self, tmp_path):
        """A shell on THIS host with no isolation declared: the thing the
        gate exists to refuse."""
        return skill(tmp_path, "local", allowed_tools=["run_shell_command"])

    def test_the_bridged_skill_first_still_refuses(self, tmp_path):
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([self.bridged(tmp_path), self.local(tmp_path)])
        assert "runs code the model composed ON THIS HOST" in str(exc.value)

    def test_the_local_skill_first_refuses_too(self, tmp_path):
        """The same two manifests the other way round. Both orders, or the
        assertion is about dedup order rather than about the gate."""
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([self.local(tmp_path), self.bridged(tmp_path)])
        assert "runs code the model composed ON THIS HOST" in str(exc.value)

    def test_the_refusal_names_the_local_entry_and_not_the_bridged_one(
            self, tmp_path):
        """The bridged tool is not the problem and must not be named as
        one: an operator told to sandbox `mcp.run_shell_command` would go
        and write a declaration that is not true about where it runs."""
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([self.bridged(tmp_path), self.local(tmp_path)])
        message = str(exc.value)
        assert "'run_shell_command' runs code" in message
        assert "'mcp.run_shell_command' runs code" not in message

    def test_it_is_said_once_and_not_once_per_manifest(self, tmp_path):
        """One entry gated twice is one thing to fix. A refusal that says
        it twice reads like two problems and gets half-fixed."""
        with pytest.raises(SkillManifestError) as exc:
            compose_manifests([self.local(tmp_path), self.bridged(tmp_path)])
        assert str(exc.value).count("runs code the model composed") == 1

    def test_a_skill_that_supplies_bwrap_lets_the_composition_through(
            self, tmp_path):
        """The other half, or the rule above is just "refuse". The sandbox
        merge takes the strictest ask, and a skill that brought bwrap
        brought it for the whole composition — including for an entry
        another skill contributed."""
        composed = compose_manifests([
            self.bridged(tmp_path),
            skill(tmp_path, "local", allowed_tools=["run_shell_command"],
                  sandbox="bwrap"),
        ])
        assert composed.sandbox == "bwrap"

    def test_and_that_holds_in_the_other_order_as_well(self, tmp_path):
        composed = compose_manifests([
            skill(tmp_path, "local", allowed_tools=["run_shell_command"],
                  sandbox="bwrap"),
            self.bridged(tmp_path),
        ])
        assert composed.sandbox == "bwrap"

    def test_a_skill_declaring_none_does_not_drag_a_bwrap_one_down(
            self, tmp_path):
        """The per-manifest check asks each skill its question under the
        COMPOSED sandbox, not under the one it wrote. A skill that said
        `none` is not unsafe once another skill has brought isolation —
        gating it against its own declaration would refuse a composition
        that is, in fact, isolated."""
        composed = compose_manifests([
            skill(tmp_path, "first", allowed_tools=["run_python_code"],
                  sandbox="bwrap"),
            skill(tmp_path, "second", allowed_tools=["run_shell_command"],
                  sandbox="none"),
        ])
        assert composed.sandbox == "bwrap"
        assert sorted(entry for entry, _t, _s
                      in composed.code_plane_entries()) == [
            "run_python_code", "run_shell_command"]

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

    def test_a_hand_built_args_may_still_carry_a_scalar_skill(
            self, tmp_path, monkeypatch):
        """`args` is not always argparse's — a library caller, a test and
        `core.eval` all build one by hand, and every one of them wrote
        `skill="analyst"` while the flag took a single value. `list()`
        over a string is seven skills called 'a', 'n', 'a'…, which is a
        mangling of an argument somebody passed correctly."""
        from types import SimpleNamespace

        from core import cli

        monkeypatch.delenv("MISSION_SKILL", raising=False)
        assert cli._skill_values(SimpleNamespace(skill="analyst")) == ["analyst"]

    def test_a_scalar_path_is_not_a_typeerror(self, tmp_path, monkeypatch):
        """The other spelling, and the worse failure: `list(Path(...))`
        raises rather than mangling, so a caller that had been working
        would stop with a message about iteration."""
        from pathlib import Path as P
        from types import SimpleNamespace

        from core import cli

        monkeypatch.delenv("MISSION_SKILL", raising=False)
        one = skill(tmp_path, "solo")
        args = SimpleNamespace(skill=P(one.source))
        assert cli._load_skill(args).name == "solo"

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


class TestARefusalNamesEverySkillItIsAbout:
    """The closed set a refusal is about is the UNION.

    A tool missing for the third skill, reported under the first skill's
    name, sends an operator to open the wrong file and find nothing wrong
    with it.
    """

    def test_the_resolve_refusal_names_the_composition(self, tmp_path):
        composed = compose_manifests([
            skill(tmp_path, "first", allowed_tools=["alpha"]),
            skill(tmp_path, "second", allowed_tools=["beta"]),
        ])
        with pytest.raises(SkillToolsUnavailable) as exc:
            composed.resolve(["alpha"])
        message = str(exc.value)
        assert "'first' (composed with 'second')" in message
        assert "'beta' is in the closed set and was not discovered" in message

    def test_the_serverless_refusal_names_the_composition_too(self, tmp_path):
        """The residual the docstring admits, pinned in the direction it
        fails.

        Dedup keeps the FIRST spelling, so `mcp.thing` listed first and
        `thing` second composes to `mcp.thing` — an entry that CLAIMS a
        server owns it. On a host with no transport
        `_local_plane_or_refuse` reads that claim and refuses; the other
        listing order composes to `thing` and runs. The order-dependence
        is real and fail-closed, which is why it is a residual and not the
        blocker the code-plane gate was — and the refusal has to name
        every skill it is about, because the entry that provoked it came
        from the one that is not the primary."""
        from core.cli import _local_plane_or_refuse
        from core.tools import Tools

        composed = compose_manifests([
            skill(tmp_path, "bridged", allowed_tools=["mcp.run_shell_command"]),
            skill(tmp_path, "local", allowed_tools=["run_shell_command"],
                  sandbox="bwrap"),
        ])
        assert composed.allowed_tools == ("mcp.run_shell_command",)
        with pytest.raises(SystemExit) as exc:
            _local_plane_or_refuse(composed, Tools(root=str(tmp_path)).bus)
        assert "'bridged' (composed with 'local')" in str(exc.value)

    def test_one_skill_is_named_exactly_as_it_always_was(self, tmp_path):
        """The compatibility half: no composition, no parenthesis, and the
        sentence every existing test and every operator's eye knows."""
        with pytest.raises(SkillToolsUnavailable) as exc:
            skill(tmp_path, "solo", allowed_tools=["alpha"]).resolve(["beta"])
        assert "skill 'solo' cannot run against this server" in str(exc.value)


#: One value per ``grounding:`` key that is a DECLARATION carrying nothing:
#: what a skill writes when it means "this key, and no opinion yet". Each
#: has to be a value `from_mapping` accepts on its own, because the merge
#: validates every input block before folding it.
#:
#: ``max_repairs`` has no empty — a count is a count — so its neutral value
#: is the default somebody would have got anyway, written down.
NOTHING_DECLARED = {
    "identifier_pattern": None,
    "number_pattern": None,
    "ignore": [],
    "figures_from": [],
    "max_repairs": 1,
    "must_cite": {},
    "claim_table": False,
    "reading": False,
    "critic": False,
    "planes": {},
}


class TestCompositionNeverChangesAKeysPresence:
    """The rule, over every key a grounding block may set.

    Written as a sweep and not as a list of cases on purpose. The defect
    the reference deployment hit was not "must_cite is wrong" — it was that
    the merge had four separate `if <non-empty>:` guards and nobody had
    asked what each of them did to a key that was declared and empty. A key
    added to `grounding.py` tomorrow with no merge rule fails here on the
    day it is added, rather than on the day a platform composes with it.
    """

    def test_the_neutral_values_cover_every_key_there_is(self):
        """The sweep below is only as good as this mapping, and this
        mapping is the thing that would silently stop covering a new
        key."""
        from core.runtime.grounding import GROUNDING_KEYS

        assert set(NOTHING_DECLARED) == set(GROUNDING_KEYS)

    @pytest.mark.parametrize("key", sorted(NOTHING_DECLARED))
    def test_a_key_declared_empty_by_every_input_survives(self, tmp_path, key):
        composed = compose_manifests([
            skill(tmp_path, "first", grounding={key: NOTHING_DECLARED[key]}),
            skill(tmp_path, "second", grounding={key: NOTHING_DECLARED[key]}),
        ])
        assert key in composed.grounding, (
            f"{key!r} was declared by both skills and is not in the merged "
            f"mapping: composition may change a value, never a key's presence")

    @pytest.mark.parametrize("key", sorted(NOTHING_DECLARED))
    def test_a_key_declared_by_only_one_input_survives_too(self, tmp_path, key):
        """The asymmetric half. A family where one member declares a key
        and the others do not is the ordinary case, not the exotic one."""
        composed = compose_manifests([
            skill(tmp_path, "first", grounding={key: NOTHING_DECLARED[key]}),
            skill(tmp_path, "second", grounding={"ignore": ["placeholder"]}),
        ])
        assert key in composed.grounding

    @pytest.mark.parametrize("key", sorted(NOTHING_DECLARED))
    def test_a_key_nobody_declared_is_not_invented(self, tmp_path, key):
        """The other direction, and the reason this is a rule about
        PRESERVING presence rather than about filling the mapping in: a
        merge that emitted every key at its default would tell a consumer
        that ten checks were configured when none were."""
        composed = compose_manifests([
            skill(tmp_path, "first", grounding={"ignore": ["dead"]}),
            skill(tmp_path, "second", grounding={"ignore": ["tbd"]}),
        ])
        if key != "ignore":
            assert key not in composed.grounding

    @pytest.mark.parametrize("key", sorted(NOTHING_DECLARED))
    def test_the_merged_shape_is_the_single_skill_shape(self, tmp_path, key):
        """Stated as the equality it is. One skill composes to itself, so
        its mapping IS the reference shape — and the two-skill mapping has
        to carry the same keys or a consumer's `in` test answers differently
        for the same declarations."""
        block = {key: NOTHING_DECLARED[key]}
        alone = compose_manifests([skill(tmp_path, "solo", grounding=block)])
        together = compose_manifests([
            skill(tmp_path / "a", "first", grounding=block),
            skill(tmp_path / "b", "second", grounding=block),
        ])
        assert set(together.grounding) == set(alone.grounding)


def test_the_module_docstring_says_composition_has_one_owner():
    """One owner per fact, asserted where a second implementation would be
    written: a platform embedding the library that unioned the tools its
    own way would produce transcripts that look exactly like these."""
    import core.runtime.skills as module

    assert "compose_manifests" in textwrap.dedent(module.__doc__)
