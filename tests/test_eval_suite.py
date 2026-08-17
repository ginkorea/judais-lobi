# tests/test_eval_suite.py — the declaration half, and every way it is refused

"""A suite that cannot be graded must not load.

The point of `check_the_suite_is_gradeable` is that it fails, so this file is
mostly a catalogue of bad suites: a flag nobody captures, a prompt that names
a tool, a held-out half outside the band, two missions with one key, an
outcome word the contract does not know, a flag this repo never published.
Each is built by taking the real suite and breaking exactly one thing, which
is also how somebody will break it for real.

The in-repo suite is checked at import of `core.eval.stub_suite`; asserting it
here as well is not redundant, because a check that only ran at import would
pass a suite whose problems were introduced by a later edit to `FLAGS`.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from core.eval import suite as suite_module
from core.eval.stub_suite import SUITE
from core.eval.suite import (FLAGS, HARNESS_OWNED_FLAGS, MIN_TEST_MISSIONS,
                             RUBRIC_CHANGES, SPLITS, TEST_SHARE, Mission,
                             MissionMisdeclared, RubricChange, Suite,
                             check_the_suite_is_gradeable, load_suite,
                             missions_in)


def rebuilt(**changes) -> Suite:
    """The real suite with one thing changed."""
    return dataclasses.replace(SUITE, **changes)


def swapped(key: str, **changes) -> Suite:
    """The real suite with one mission changed."""
    missions = tuple(dataclasses.replace(m, **changes) if m.key == key else m
                     for m in SUITE.missions)
    return rebuilt(missions=missions)


def refused(suite: Suite) -> str:
    with pytest.raises(MissionMisdeclared) as exc:
        check_the_suite_is_gradeable(suite)
    return str(exc.value)


class TestTheInRepoSuiteIsGradeable:
    def test_it_passes_its_own_check(self):
        check_the_suite_is_gradeable(SUITE)

    def test_the_default_argument_is_the_in_repo_suite(self):
        """`check_the_suite_is_gradeable()` with nothing is `python -m
        core.eval check` with nothing, and both mean this suite."""
        check_the_suite_is_gradeable()

    def test_every_flag_is_captured_exactly_once(self):
        captured = [m.flag for m in SUITE.missions]
        assert sorted(captured) == sorted(FLAGS)

    def test_the_held_out_share_is_inside_the_band(self):
        held = [m for m in SUITE.missions if m.split == "test"]
        low, high = TEST_SHARE
        assert low <= len(held) / len(SUITE.missions) <= high
        assert len(held) >= MIN_TEST_MISSIONS

    def test_every_mission_says_why_it_exists(self):
        for mission in SUITE.missions:
            assert mission.because.strip(), mission.key
            assert mission.must and mission.must_not, mission.key

    def test_the_ledger_is_dated_and_reasoned(self):
        assert RUBRIC_CHANGES
        for entry in RUBRIC_CHANGES:
            assert isinstance(entry, tuple)
            for field in RubricChange._fields:
                assert str(getattr(entry, field)).strip(), field


class TestASuiteThatCannotBeGraded:
    """One broken thing each, and the message has to name it."""

    def test_a_flag_no_mission_captures(self):
        thinner = rebuilt(missions=tuple(
            m for m in SUITE.missions if m.flag != "synthesis"))
        assert "synthesis" in refused(thinner)

    def test_a_flag_that_is_not_in_the_table(self):
        assert "hunch" in refused(swapped("two_views_one_line", flag="hunch"))

    def test_a_prompt_that_names_a_tool(self):
        """Both spellings: the wire name and the bare one. A prompt saying
        `governed_view` has named the tool as surely as `mcp.governed_view`,
        and the namespace prefix is the harness's, not the author's."""
        for named in ("mcp.governed_view", "governed_view"):
            problem = refused(swapped(
                "two_views_one_line",
                prompt=f"For run r-3, work out the totals with {named}."))
            assert "the prompt names the tool" in problem
            assert "governed_view" in problem

    def test_a_prompt_naming_a_tool_inside_a_word_is_not_flagged(self):
        """`add` is a tool here, and a suite that could not say 'additional'
        would be a suite whose check gets switched off."""
        check_the_suite_is_gradeable(swapped(
            "two_views_one_line",
            prompt="For run r-3, give me the totals and any additional "
                   "context you have."))

    def test_a_duplicate_key(self):
        doubled = rebuilt(missions=SUITE.missions + (SUITE.missions[0],))
        assert "duplicate key" in refused(doubled)

    def test_a_test_share_below_the_band(self):
        trained = rebuilt(missions=tuple(
            dataclasses.replace(m, split="train") for m in SUITE.missions))
        problem = refused(trained)
        assert "0%" in problem
        assert "test mission" in problem

    def test_a_test_share_above_the_band(self):
        held = rebuilt(missions=tuple(
            dataclasses.replace(m, split="test") for m in SUITE.missions))
        assert "100%" in refused(held)

    def test_a_split_that_is_not_a_half(self):
        assert "'holdout'" in refused(
            swapped("two_views_one_line", split="holdout"))

    def test_an_outcome_the_contract_cannot_say(self):
        problem = refused(swapped("two_views_one_line",
                                  expects_outcome="succeeded"))
        assert "succeeded" in problem
        assert "answered_with_caveat" in problem

    def test_a_tool_the_plane_does_not_serve(self):
        problem = refused(swapped("two_views_one_line",
                                  expects_tools=("mcp.catalog_search",)))
        assert "mcp.catalog_search" in problem

    def test_a_prompt_naming_data_the_plane_does_not_hold(self):
        """The reference platform shipped a mission that was quietly
        measuring absence for a month, because its prompt named a corpus
        nobody had loaded."""
        problem = refused(swapped(
            "two_views_one_line",
            prompt="For asset.9999, how many records are there?"))
        assert "asset.9999" in problem
        assert "grading absence" in problem

    def test_a_flag_the_contract_does_not_publish(self):
        problem = refused(swapped("two_views_one_line",
                                  flags=("--turbo",)))
        assert "--turbo" in problem
        assert "CLI_FLAGS" in problem

    @pytest.mark.parametrize("flag", HARNESS_OWNED_FLAGS)
    def test_a_flag_the_harness_owns(self, flag):
        problem = refused(swapped("two_views_one_line", flags=(flag, "x")))
        assert flag in problem
        assert "the harness's to pass" in problem

    def test_a_regex_that_does_not_compile(self):
        problem = refused(swapped("two_views_one_line",
                                  answer_must_match=("(unclosed",)))
        assert "does not compile" in problem

    def test_a_mission_with_no_rubric_for_a_reader(self):
        assert "no `must`" in refused(
            swapped("two_views_one_line", must=()))
        assert "no `must_not`" in refused(
            swapped("two_views_one_line", must_not=()))

    def test_a_mission_with_no_reason_to_exist(self):
        assert "no stated reason" in refused(
            swapped("two_views_one_line", because=""))

    def test_every_problem_is_collected_not_just_the_first(self):
        """A table fixed one exception at a time is a table abandoned half
        corrected."""
        problem = refused(swapped("two_views_one_line", flag="hunch",
                                  because="", must=()))
        assert "hunch" in problem
        assert "no stated reason" in problem
        assert "no `must`" in problem

    def test_an_incomplete_ledger_entry(self):
        problem = refused(rebuilt(rubric_changes=(
            RubricChange(date="", key="k", what="w", why="y"),)))
        assert "'date'" in problem


class TestTheHalves:
    def test_missions_in_returns_one_half(self):
        held = missions_in("test", SUITE.missions)
        assert held
        assert {m.split for m in held} == {"test"}
        assert len(held) < len(SUITE.missions)

    def test_all_is_the_whole_suite(self):
        assert missions_in("all", SUITE.missions) == SUITE.missions

    def test_an_unknown_split_is_a_refusal_naming_the_halves(self):
        with pytest.raises(KeyError) as exc:
            missions_in("holdout", SUITE.missions)
        assert "train" in str(exc.value) and "test" in str(exc.value)

    def test_with_no_missions_it_answers_for_the_in_repo_suite(self):
        assert missions_in("all") == SUITE.missions

    def test_the_suite_method_and_the_function_agree(self):
        for half in (*SPLITS, "all"):
            assert SUITE.missions_in(half) == missions_in(half, SUITE.missions)

    def test_one_mission_by_key(self):
        assert SUITE.mission("two_views_one_line").flag == "synthesis"
        with pytest.raises(KeyError):
            SUITE.mission("nope")


class TestASuiteFromAFile:
    """A platform keeps its suite in its own repository; this is the loader.

    The in-repo suite is the round-trip subject on purpose: it exercises
    every field a mission has, and a loader tested against a hand-written
    two-mission file would silently stop carrying the field somebody added
    last week.
    """

    def _written(self, tmp_path, suite=SUITE, name="suite.json"):
        path = tmp_path / name
        path.write_text(json.dumps(suite.to_mapping(), indent=2),
                        encoding="utf-8")
        return path

    def test_json_round_trips_every_field(self, tmp_path):
        loaded = load_suite(self._written(tmp_path))
        assert loaded.missions == SUITE.missions
        assert loaded.tools == SUITE.tools
        assert loaded.assets == dict(SUITE.assets)
        assert loaded.identifier_pattern == SUITE.identifier_pattern
        assert loaded.rubric_changes == SUITE.rubric_changes

    def test_yaml_round_trips_too(self, tmp_path):
        yaml = pytest.importorskip("yaml")
        path = tmp_path / "suite.yaml"
        path.write_text(yaml.safe_dump(SUITE.to_mapping(), sort_keys=False),
                        encoding="utf-8")
        assert load_suite(path).missions == SUITE.missions

    def test_the_loader_refuses_a_suite_that_cannot_be_graded(self, tmp_path):
        broken = swapped("two_views_one_line", flag="hunch")
        with pytest.raises(MissionMisdeclared):
            load_suite(self._written(tmp_path, broken))

    def test_the_check_can_be_asked_not_to_run(self, tmp_path):
        broken = swapped("two_views_one_line", flag="hunch")
        loaded = load_suite(self._written(tmp_path, broken), check=False)
        assert loaded.mission("two_views_one_line").flag == "hunch"

    def test_a_misspelt_field_is_refused_rather_than_ignored(self, tmp_path):
        """`expect_tools` for `expects_tools` would otherwise be a mission
        that checks nothing, which is the failure a suite cannot notice."""
        raw = SUITE.to_mapping()
        raw["missions"][0]["expect_tools"] = ["mcp.echo"]
        path = tmp_path / "suite.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        with pytest.raises(MissionMisdeclared) as exc:
            load_suite(path)
        assert "expect_tools" in str(exc.value)

    def test_a_string_where_a_list_belongs_is_refused(self):
        with pytest.raises(MissionMisdeclared) as exc:
            Mission.from_mapping({"key": "k", "flag": "absence",
                                  "prompt": "p", "must": "one clause"})
        assert "list of strings" in str(exc.value)

    def test_a_mission_with_no_key_is_refused(self):
        with pytest.raises(MissionMisdeclared):
            Mission.from_mapping({"flag": "absence", "prompt": "p"})

    def test_an_unknown_suite_key_is_refused(self):
        with pytest.raises(MissionMisdeclared) as exc:
            Suite.from_mapping({"name": "x", "missions": [], "flagz": []})
        assert "flagz" in str(exc.value)

    def test_a_suite_that_is_not_a_mapping_is_refused(self):
        with pytest.raises(MissionMisdeclared):
            Suite.from_mapping([], source="rows.json")

    def test_a_ledger_entry_may_be_a_bare_tuple(self):
        loaded = Suite.from_mapping({
            "name": "x", "missions": [],
            "rubric_changes": [["2026-08-16", "k", "what", "why"]]})
        assert loaded.rubric_changes[0].date == "2026-08-16"

    def test_a_ledger_entry_missing_a_reason_is_refused(self):
        with pytest.raises(MissionMisdeclared) as exc:
            Suite.from_mapping({"name": "x", "missions": [],
                                "rubric_changes": [{"date": "2026-08-16",
                                                    "key": "k",
                                                    "what": "w"}]})
        assert "why" in str(exc.value)

    def test_defaults_are_not_written_back_out(self):
        """A round-tripped suite should read like one somebody wrote."""
        written = SUITE.mission("what_can_you_do_here").to_mapping()
        assert "forbids_tools" not in written
        assert "must_not_stage" not in written
        assert written["key"] and written["flag"] and written["prompt"]


class TestTheFlagTable:
    def test_every_flag_has_a_sentence(self):
        for name, description in FLAGS.items():
            assert description.strip(), name
            assert len(description) > 20, name

    def test_the_module_exports_what_it_documents(self):
        for name in suite_module.__all__:
            assert hasattr(suite_module, name), name
