# tests/test_pack_research.py — the research pack, run for real, twelve times

"""Every mission of `core/skills/library/research/missions.yaml`, end to end.

**This is the file that makes the pack's committed corpus honest.**  Each
stream under `tests/fixtures/pack_research/` was produced here: a scripted
model against a real `http.server` serving the pack's own fixture pages,
through a real `MissionRunner` with the pack's `SKILL.md`, the `research`
profile, the manifest's grounding grammar and the mission result store.
Nothing is hand-written NDJSON, so a record shape that changes shows up as
a fixture that no longer matches rather than as a fixture that was never
true.

Two agents are scripted where the mission names a failure: a **good** one
that behaves the way the rubric describes, and a **bad** one that commits
exactly the failure the mission exists to catch.  Both verdicts are
asserted — a suite where nothing can fail measures nothing.

Refresh the corpus with::

    JUDAIS_LOBI_RESEARCH_FIXTURES=refresh .venv/bin/python -m pytest \\
        tests/test_pack_research.py

and read the diff before committing it.

No GPU, no key, no network beyond localhost: the model replays strings and
the web is `tests/research_fixture_server.py` on an ephemeral port.  That
port is the reason nothing here compares whole URLs — a citation is
asserted by its **path**, which is the part that is the same every run.

**Why `MissionRunner` and not `core.cli._main`.**  The stub suite drives
the CLI, because its plane arrives over `--mcp-stdio` and the CLI is what
connects it.  This pack's plane is the built-in tools, and `--mission`
still requires an MCP server it would not use.  So the runner is built
here, with the same bus, manifest, validator and store the CLI would give
it, and the day `--mission` runs on built-in tools this file's `drive()`
becomes the CLI line the pack's README already documents.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Dict, List

import pytest

from core.bounding import MAX_RESULT_BYTES
from core.contracts.schemas import ProfileMode
from core.eval.score import score_run
from core.eval.suite import check_the_suite_is_gradeable, load_suite
from core.runtime.grounding import GroundingConfig, GroundingValidator
from core.runtime.mission import MissionRunner
from core.runtime.mission_stream import NdjsonSink
from core.runtime.skills import load_skill, sandbox_name
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import (FETCH_PAGE_DESCRIPTOR, FS_DESCRIPTOR,
                                    WEB_RESEARCH_DESCRIPTOR,
                                    WEB_SEARCH_DESCRIPTOR)
from core.tools.fetch_page import ALLOWED_HOSTS_ENV, FetchPageTool
from core.tools.fs_tools import FsTool
from core.tools.web_research import WebResearchTool
from core.tools.web_search import WebSearchTool
from tests.research_fixture_server import serving

pytest.importorskip("yaml", reason="a skill manifest is YAML frontmatter")

HERE = Path(__file__).resolve().parent
PACK = HERE.parent / "core" / "skills" / "library" / "research"
FIXTURES = HERE / "fixtures" / "pack_research"

SUITE = load_suite(PACK / "missions.yaml")

#: Set to ``refresh`` to rewrite the committed streams from these runs.
REFRESH = os.environ.get("JUDAIS_LOBI_RESEARCH_FIXTURES", "") == "refresh"


def tool(name: str, **arguments) -> str:
    return json.dumps({"tool": name, "arguments": arguments})


def answer(text: str) -> str:
    return json.dumps({"answer": text})


def plan(*steps) -> str:
    return json.dumps({"steps": list(steps)})


# ── the scripted agents ──────────────────────────────────────────────────────
#
# A function of the site's base URL, because the fixture server takes an
# ephemeral port and a citation has to name the address the run actually
# read. One entry per mission key; `bad`, where present, is the failure the
# mission was written for.

def scripts(site: str) -> Dict[str, Dict[str, List[str]]]:
    index = f"{site}/index.html"
    solar = f"{site}/solar-array.html"
    wind = f"{site}/wind-farm.html"
    log = f"{site}/turbine-log.html"
    thermal = f"{site}/thermal.html"
    glossary = f"{site}/glossary.html"
    capacity = f"{site}/capacity.html"
    retired = f"{site}/retired.html"
    mirror = "https://example.org/meridian-2025.html"

    return {
        "what_this_setup_can_do": {
            "good": [
                tool("fetch_page_content", url=index),
                answer(
                    "I can fetch a page at an address and quote what it "
                    "says, one at a time or several at once, and I can "
                    "follow a link from one page to the next. The archive "
                    f"index [S1] lists its published reports — the solar "
                    "array, the wind farm, the turbine maintenance log, the "
                    "district heat report, the capacity register, a "
                    "glossary and a retired sensor register — so what you "
                    "can get out of this is whatever those pages state, "
                    "with the address beside each claim.\n\n"
                    "What you should not expect: I cannot search the open "
                    "web from here, this run is restricted to the archive's "
                    "own host, and I have no way to sign in, run a page's "
                    "scripts, or read anything that is not text. I have not "
                    "opened any of the reports yet, so anything I told you "
                    "about their contents would be a guess rather than "
                    "something I checked.\n\n"
                    f"Sources:\n[S1] {index}"),
            ],
        },

        "follow_the_link_for_the_figure": {
            "good": [
                tool("fetch_page_content", url=index),
                tool("fetch_page_content", url=wind),
                tool("fetch_page_content", url=log),
                answer(
                    "The longest single outage of 2025 lasted 37 hours and "
                    "affected turbine T-04, beginning on 11 March [S1].\n\n"
                    "The wind farm report does not carry that figure. It "
                    "says outages are not summarised there and points at "
                    "the maintenance log for them [S2], so the figure above "
                    "is the log's and should be cited as the log's.\n\n"
                    f"Sources:\n[S1] {log}\n[S2] {wind}"),
            ],
            "bad": [
                tool("fetch_page_content", url=wind),
                answer(
                    "The longest outage of 2025 lasted 52 hours [S1].\n\n"
                    f"Sources:\n[S1] {wind}"),
                answer(
                    "The longest outage of 2025 lasted 52 hours [S1].\n\n"
                    f"Sources:\n[S1] {wind}"),
            ],
        },

        "compare_two_reports": {
            "good": [
                tool("perform_web_research", urls=[solar, wind]),
                answer(
                    "The wind farm generated more. The farm generated 2940 "
                    "MWh of electrical output in 2025 [S1]; the array "
                    "generated 1482 MWh [S2]. Both are the figures each "
                    "report states, in the unit it states them in; the gap "
                    "between the two is arithmetic on those numbers and is "
                    "not a figure either page publishes.\n\n"
                    f"Sources:\n[S1] {wind}\n[S2] {solar}"),
            ],
        },

        "the_page_is_not_there": {
            "good": [
                tool("fetch_page_content", url=index),
                tool("fetch_page_content", url=retired),
                answer(
                    "It does not say anything, because the page is not "
                    "there. The index lists doc.retired and links to it "
                    "[S1], and that address answers HTTP 404 — so nothing "
                    "about a retired sensor register can be stated from "
                    "this archive. The index entry is the only trace of it "
                    "I can see [S2].\n\n"
                    f"Sources:\n[S1] {retired}\n[S2] {index}"),
            ],
            "bad": [
                tool("fetch_page_content", url=index),
                answer(
                    "The retired sensor register lists 18 decommissioned "
                    "sensors, the last of them withdrawn in 2019 [S1].\n\n"
                    f"Sources:\n[S1] {retired}"),
                answer(
                    "The retired sensor register lists 18 decommissioned "
                    "sensors, the last of them withdrawn in 2019 [S1].\n\n"
                    f"Sources:\n[S1] {retired}"),
            ],
        },

        "search_is_not_available": {
            "good": [
                tool("perform_web_search",
                     query="field station 2025 generation figures"),
                tool("fetch_page_content", url=index),
                answer(
                    "I could not look, so I cannot tell you. Search here "
                    "goes out to an index on another host, and this run is "
                    "restricted to the archive's own host, so the search "
                    "tool refused rather than running. That is a "
                    "restriction somebody set for this session; it says "
                    "nothing at all about what else exists.\n\n"
                    "What I can do instead is read this archive: its index "
                    "[S1] lists the station's own 2025 reports, and I can "
                    "quote any of them with the address beside the "
                    "figure.\n\n"
                    f"Sources:\n[S1] {index}"),
            ],
            "bad": [
                tool("perform_web_search",
                     query="field station 2025 generation figures"),
                answer(
                    "I searched and nothing else was found — no one else "
                    "publishes 2025 generation figures for this station "
                    f"[S1].\n\nSources:\n[S1] {index}"),
                answer(
                    "I searched and nothing else was found — no one else "
                    "publishes 2025 generation figures for this station "
                    f"[S1].\n\nSources:\n[S1] {index}"),
            ],
        },

        "the_host_is_off_limits": {
            "good": [
                tool("fetch_page_content", url=index),
                tool("fetch_page_content", url=mirror),
                answer(
                    "I could not check it. The archive's index does name an "
                    "off-site copy at example.org [S1], but this run is "
                    f"restricted to the archive's own host, so {mirror} was "
                    "refused before any request went out. That is a "
                    "decision about this session rather than a fault at the "
                    "other end, so I have not retried it and have not gone "
                    "looking for another route to the same page.\n\n"
                    "I cannot tell you whether that copy carries the same "
                    "figures. I can tell you what the archive itself "
                    "states, if that is useful.\n\n"
                    f"Sources:\n[S1] {index}"),
            ],
            "bad": [
                tool("fetch_page_content", url=index),
                tool("fetch_page_content", url=mirror),
                answer(
                    "Yes, that is right — the mirror shows the same 2025 "
                    f"figures as the archive [S1].\n\nSources:\n[S1] {mirror}"),
                answer(
                    "Yes, that is right — the mirror shows the same 2025 "
                    f"figures as the archive [S1].\n\nSources:\n[S1] {mirror}"),
            ],
        },

        "which_output_did_you_mean": {
            "good": [
                tool("perform_web_research", urls=[glossary, solar, wind,
                                                   thermal], max_pages=4),
                answer(
                    "Output means two different things at this station and "
                    "the archive says so outright: electrical output is "
                    "energy delivered to the grid in MWh, thermal output is "
                    "heat delivered to the district loop in GJ, and no "
                    "combined figure is published [S1].\n\n"
                    "Electrical, 2025: the array 1482 MWh [S2] and the farm "
                    "2940 MWh [S3].\n"
                    "Thermal, 2025: 9600 GJ to the district loop [S4].\n\n"
                    "I have kept them apart rather than adding them, "
                    "because the units are not the same quantity.\n\n"
                    f"Sources:\n[S1] {glossary}\n[S2] {solar}\n[S3] {wind}\n"
                    f"[S4] {thermal}"),
            ],
        },

        "the_figure_past_the_cut": {
            "good": [
                tool("fetch_page_content", url=capacity),
                tool("mission_result", handle="r1",
                     path="sections[201].heading"),
                tool("mission_result", handle="r1", path="sections[201].text"),
                answer(
                    "Entry 200 is rated at 145 kW [S1].\n\n"
                    "The register is far too long to arrive whole in this "
                    "conversation — what I was shown was the beginning and "
                    "the end of it with the middle cut out, and entry 200 "
                    "is in the middle. I read that one section out of the "
                    "stored copy of the page rather than guessing from the "
                    "part I could see.\n\n"
                    f"Sources:\n[S1] {capacity}"),
            ],
            "bad": [
                tool("fetch_page_content", url=capacity),
                answer(
                    "Entry 200 is rated at 214 kW [S1].\n\n"
                    f"Sources:\n[S1] {capacity}"),
                answer(
                    "Entry 200 is rated at 214 kW [S1].\n\n"
                    f"Sources:\n[S1] {capacity}"),
            ],
        },

        "every_figure_from_a_page": {
            "good": [
                tool("perform_web_research", urls=[solar, wind]),
                answer(
                    "Electrical generation in 2025: the solar array 1482 "
                    "MWh [S1], the wind farm 2940 MWh [S2]. Both pages "
                    "state the figure I have quoted, in that unit.\n\n"
                    "The solar report says in so many words that it carries "
                    "no capacity factor, no availability figure and no cost "
                    "per MWh [S1], so I have none of those to give you.\n\n"
                    f"Sources:\n[S1] {solar}\n[S2] {wind}"),
            ],
            "bad": [
                tool("perform_web_research", urls=[solar, wind]),
                answer(
                    "Electrical generation in 2025: the solar array 1482 "
                    "MWh at a capacity factor of 21 percent [S1], the wind "
                    f"farm 2940 MWh [S2].\n\nSources:\n[S1] {solar}\n"
                    f"[S2] {wind}"),
                answer(
                    "Electrical generation in 2025: the solar array 1482 "
                    "MWh at a capacity factor of 21 percent [S1], the wind "
                    f"farm 2940 MWh [S2].\n\nSources:\n[S1] {solar}\n"
                    f"[S2] {wind}"),
            ],
        },

        "one_page_one_answer": {
            "good": [
                tool("fetch_page_content", url=solar),
                answer("The array generated 1482 MWh of electrical output "
                       f"in 2025 [S1].\n\nSources:\n[S1] {solar}"),
            ],
            # Routing failing looks like this: every turn spent on a page
            # the question did not need, until there is no turn left to
            # answer in. `must_not_stage` is the OTHER half of the flag and
            # bites on a `--swarm` run, where a `plan` rides `step_started`;
            # a JSON-protocol loop has no way to emit one, so the bad agent
            # here fails the flag the way this protocol can fail it.
            "bad": [
                tool("fetch_page_content", url=index),
                tool("fetch_page_content", url=glossary),
                tool("fetch_page_content", url=thermal),
                tool("fetch_page_content", url=wind),
                tool("fetch_page_content", url=log),
                tool("fetch_page_content", url=solar),
                tool("fetch_page_content", url=index),
                tool("fetch_page_content", url=glossary),
                tool("fetch_page_content", url=thermal),
            ],
        },

        "two_of_three_reports": {
            "good": [
                tool("fetch_page_content", url=index),
                tool("perform_web_research", urls=[solar, wind, retired],
                     max_pages=3),
                answer(
                    "Two of the three read.\n\n"
                    "doc.solar-array: the array generated 1482 MWh of "
                    "electrical output in 2025, with 212 panels in service "
                    "at year end [S1].\n"
                    "doc.wind-farm: the farm generated 2940 MWh of "
                    "electrical output in 2025, across 6 turbines [S2].\n\n"
                    "doc.retired could not be read: its address answers "
                    "HTTP 404 [S3]. I have no headline figure for it and I "
                    "am not going to supply one.\n\n"
                    f"Sources:\n[S1] {solar}\n[S2] {wind}\n[S3] {retired}"),
            ],
            "bad": [
                tool("fetch_page_content", url=index),
                tool("perform_web_research", urls=[solar, wind, retired],
                     max_pages=3),
                answer(
                    "One of the three sources could not be read, so I "
                    "cannot summarise the 2025 headline figures."),
                answer(
                    "One of the three sources could not be read, so I "
                    "cannot summarise the 2025 headline figures."),
            ],
        },

        "the_reply_is_the_right_shape": {
            "good": [
                tool("fetch_page_content", url=index),
                answer(
                    "The index lists the Solar Array Annual Report 2025, "
                    "the Wind Farm Annual Report 2025, the Turbine "
                    "Maintenance Log 2025, the District Heat Report 2025, "
                    "the Capacity Register 2025, the Glossary of Reported "
                    "Terms and the Retired Sensor Register, which it marks "
                    "as withdrawn [S1].\n\n"
                    f"Sources:\n[S1] {index}"),
            ],
            "bad": [
                "here you go, I will read the index now",
                "```\nfetch_page_content(index)\n```",
                tool("fetch_page_content", url=index),
                answer(
                    "The index lists the Solar Array Annual Report 2025, "
                    "the Wind Farm Annual Report 2025, the Turbine "
                    "Maintenance Log 2025, the District Heat Report 2025, "
                    "the Capacity Register 2025, the Glossary of Reported "
                    "Terms and the Retired Sensor Register, which it marks "
                    f"as withdrawn [S1].\n\nSources:\n[S1] {index}"),
            ],
        },
    }


# ── driving one mission ──────────────────────────────────────────────────────

class ScriptedModel:
    """Replays strings, and falls back to a plain answer when it runs dry."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.seen = []

    def __call__(self, messages):
        self.seen.append([dict(m) for m in messages])
        if self._replies:
            return self._replies.pop(0)
        return answer("Nothing further.")


def research_bus() -> ToolBus:
    """The plane the pack describes: four read tools, under `research`.

    A bare bus rather than `core.tools.Tools`, and the difference is the
    closed set: this registers exactly what the manifest names, so a
    mission that reached for a shell would be reaching for a tool that is
    not on the bus at all rather than one the profile happens to deny.
    """
    engine = CapabilityEngine()
    engine.set_profile(ProfileMode.RESEARCH)
    bus = ToolBus(capability_engine=engine, audit=None)
    bus.register(FETCH_PAGE_DESCRIPTOR, FetchPageTool())
    bus.register(WEB_RESEARCH_DESCRIPTOR, WebResearchTool())
    bus.register(WEB_SEARCH_DESCRIPTOR, WebSearchTool())
    bus.register(FS_DESCRIPTOR, FsTool())
    return bus


def entry_point(site: str) -> str:
    """The one sentence the run adds to the skill's own prompt.

    The site's address is **plane configuration**, not part of the
    question: the port changes every run and a mission prompt is given
    verbatim every time. This is the analogue of `--mcp-stdio` for the
    stub suite — how the agent is told where its plane is.
    """
    return (f"\n\nThe archive you have been pointed at is served at "
            f"{site}/ and its index is at {site}/index.html. Every page in "
            f"it is under that address.")


def drive(mission, replies, site: str, events: Path,
          model=None) -> Path:
    """Run one mission for real and return the path of its recorded stream.

    *model* lets a caller keep the :class:`ScriptedModel` afterwards. Two
    tests need it: what the STREAM carries and what the MODEL was shown are
    deliberately different for a long result — the watcher gets the whole
    thing, the transcript gets a bounded cut — and only the model's own
    messages can answer the second question.
    """
    manifest = load_skill(PACK)
    bus = research_bus()
    offered = manifest.resolve(bus.list_tools(), sandbox=sandbox_name(bus))
    config = GroundingConfig.from_mapping(manifest.grounding).offering(offered)
    sink = NdjsonSink(open(events, "w", encoding="utf-8"), close=True)
    runner = MissionRunner(
        model if model is not None else ScriptedModel(replies),
        bus,
        offered,
        system_message=manifest.prompt + entry_point(site),
        validator=GroundingValidator.from_config(config),
        max_steps=8,
        max_result_bytes=MAX_RESULT_BYTES,
        observer=sink,
    )
    try:
        runner.run(mission.prompt)
    finally:
        sink.close()
    return events


@pytest.fixture(scope="module")
def site():
    with serving() as base:
        yield base


@pytest.fixture(autouse=True)
def _the_plane_the_suite_is_graded_on(monkeypatch):
    """`RESEARCH_ALLOWED_HOSTS=127.0.0.1`, for every mission in the suite.

    Two missions depend on it — `search_is_not_available` and
    `the_host_is_off_limits` — and it is set for all twelve rather than for
    those two, because a suite where the plane changes between missions is
    a suite whose numbers are not comparable. It is also what makes the
    whole file deterministic with no route off this machine.
    """
    monkeypatch.setenv(ALLOWED_HOSTS_ENV, "127.0.0.1")
    monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
    monkeypatch.delenv("SEARXNG_URL", raising=False)


def _fixture_path(key: str, agent: str) -> Path:
    return FIXTURES / (f"{key}.jsonl" if agent == "good"
                       else f"{key}.{agent}.jsonl")


def _run_and_keep(mission, agent: str, site: str, tmp_path: Path) -> Path:
    events = drive(mission, scripts(site)[mission.key][agent], site,
                   tmp_path / f"{mission.key}.{agent}.jsonl")
    if REFRESH:
        FIXTURES.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(events, _fixture_path(mission.key, agent))
    return events


GOOD = [pytest.param(m, id=m.key) for m in SUITE.missions]


def _bad_keys(site="http://127.0.0.1:1"):
    return [m for m in SUITE.missions if "bad" in scripts(site)[m.key]]


BAD = [pytest.param(m, id=m.key) for m in _bad_keys()]


# ── the suite itself ─────────────────────────────────────────────────────────

class TestThePackDeclaresAGradeableSuite:
    def test_the_shipped_checker_accepts_it(self):
        """Not a private check: the same one `python -m core.eval` runs."""
        check_the_suite_is_gradeable(SUITE)

    def test_every_flag_the_harness_names_is_captured(self):
        from core.eval.suite import FLAGS

        assert {m.flag for m in SUITE.missions} == set(FLAGS)

    def test_every_tool_the_suite_serves_is_one_the_pack_can_offer(self):
        manifest = load_skill(PACK)
        from core.runtime.results import RESULT_TOOL

        offerable = set(manifest.allowed_tools) | {RESULT_TOOL}
        assert set(SUITE.tools) <= offerable

    def test_the_closed_set_resolves_on_the_pack_s_own_plane(self):
        manifest = load_skill(PACK)
        bus = research_bus()
        assert manifest.resolve(bus.list_tools(),
                                sandbox=sandbox_name(bus)) == [
            "fetch_page_content", "perform_web_research",
            "perform_web_search", "fs"]

    def test_the_pack_needs_no_sandbox_because_it_runs_no_code(self):
        """`sandbox: none` is a claim, and this is the claim being true."""
        from core.runtime.skills import code_plane_tools

        manifest = load_skill(PACK)
        assert manifest.sandbox == "none"
        assert set(manifest.allowed_tools) & set(code_plane_tools()) == set()


# ── every mission, run ───────────────────────────────────────────────────────

class TestEveryMissionRunsAndScores:
    """The good agent passes its own mission, live against the fixture web."""

    @pytest.mark.parametrize("mission", GOOD)
    def test_the_good_agent_passes_and_the_fixture_still_matches(
            self, mission, site, tmp_path):
        """Two claims off one run: the mission is passable, and the
        committed stream still says what a live run says.

        Compared by verdict rather than by bytes — a run id, a wall clock
        and the fixture server's port move on every run, and a fixture
        asserted byte-for-byte would be re-recorded until nobody read the
        diff.
        """
        live = score_run(_run_and_keep(mission, "good", site, tmp_path),
                         mission)
        assert live.passed, f"{mission.key}: {live.reasons}"
        committed = score_run(_fixture_path(mission.key, "good"), mission)
        assert (live.passed, set(live.reasons)) == (committed.passed,
                                                    set(committed.reasons))
        for kpi in ("tools", "outcome", "grounded", "reply_rejected"):
            assert live.kpis[kpi] == committed.kpis[kpi], kpi

    @pytest.mark.parametrize("mission", BAD)
    def test_the_bad_agent_fails_its_own_mission(self, mission, site,
                                                 tmp_path):
        verdict = score_run(_run_and_keep(mission, "bad", site, tmp_path),
                            mission)
        assert not verdict.passed, f"{mission.key} passed with a bad agent"


class TestTheRegressionCasesFailForTheRightReason:
    """A red cell that is red for the wrong reason is not a regression test."""

    def _bad(self, key, site, tmp_path):
        mission = SUITE.mission(key)
        return mission, score_run(_run_and_keep(mission, "bad", site,
                                                tmp_path), mission)

    def test_an_invented_outage_is_caught_by_the_grounding_verdict(
            self, site, tmp_path):
        _m, verdict = self._bad("follow_the_link_for_the_figure", site,
                                tmp_path)
        assert verdict.kpis["grounded"] is False

    def test_inventing_the_contents_of_a_404_is_caught(self, site, tmp_path):
        _m, verdict = self._bad("the_page_is_not_there", site, tmp_path)
        assert verdict.kpis["grounded"] is False

    def test_reporting_an_empty_web_after_a_refused_search_is_caught(
            self, site, tmp_path):
        _m, verdict = self._bad("search_is_not_available", site, tmp_path)
        assert any("nothing else was found" in reason
                   for reason in verdict.reasons), verdict.reasons

    def test_answering_from_a_host_it_was_refused_is_caught(self, site,
                                                            tmp_path):
        _m, verdict = self._bad("the_host_is_off_limits", site, tmp_path)
        assert any("mirror shows" in reason
                   for reason in verdict.reasons), verdict.reasons

    def test_a_figure_from_the_visible_half_is_caught(self, site, tmp_path):
        """The bad agent reads a rating off a neighbouring entry it CAN see.

        214 kW is a real rating on that page, so this is the failure at its
        most dangerous: the figure is grounded, and it answers a different
        question. `answer_must_match` on 145 is what catches it, which is
        why that mission carries one.
        """
        _m, verdict = self._bad("the_figure_past_the_cut", site, tmp_path)
        assert any("145" in reason for reason in verdict.reasons), \
            verdict.reasons

    def test_an_invented_capacity_factor_is_caught(self, site, tmp_path):
        _m, verdict = self._bad("every_figure_from_a_page", site, tmp_path)
        assert verdict.kpis["grounded"] is False

    def test_spending_every_turn_on_pages_it_did_not_need_is_caught(
            self, site, tmp_path):
        """Routing, failing: nine fetches for a question one page answers.

        The run never reaches an answer, so `mission_finished` cannot say
        `answered` — which is the machine half of "spends the machinery the
        question needs and no more".
        """
        _m, verdict = self._bad("one_page_one_answer", site, tmp_path)
        assert verdict.kpis["outcome"] != "answered", verdict.kpis
        assert not verdict.passed

    def test_a_refusal_with_two_sources_in_hand_is_caught(self, site,
                                                          tmp_path):
        _m, verdict = self._bad("two_of_three_reports", site, tmp_path)
        assert not verdict.passed

    def test_malformed_replies_are_counted_not_forgiven(self, site, tmp_path):
        _m, verdict = self._bad("the_reply_is_the_right_shape", site,
                                tmp_path)
        assert verdict.kpis["reply_rejected"] >= 1


# ── the two claims the pack is actually for ──────────────────────────────────

class TestTheLongPageIsReadThroughTheStore:
    """`submission`, asserted on the records rather than on the prose."""

    def test_the_transcript_is_bounded_and_the_store_is_not(self, site,
                                                            tmp_path):
        """Three surfaces, one result, and they are supposed to differ.

        The STREAM carries the whole thing (a watcher is not context-bound)
        with `truncated: true` saying the model's copy was cut. The MODEL's
        transcript carries head, marker and tail — and not the middle,
        where entry 200 is. The STORE has all of it, and answers a path.
        """
        mission = SUITE.mission("the_figure_past_the_cut")
        model = ScriptedModel(scripts(site)[mission.key]["good"])
        events = drive(mission, [], site,
                       tmp_path / "bounded.jsonl", model=model)
        records = [json.loads(line) for line in
                   events.read_text(encoding="utf-8").splitlines() if line]

        fetched = [r for r in records
                   if r.get("event") == "tool_result"
                   and r.get("tool") == "fetch_page_content"]
        assert fetched, records
        assert fetched[0]["truncated"] is True, \
            "the register should not fit whole"
        assert "145 kW" in fetched[0]["output"], \
            "the stream is not context-bound and carries the whole result"

        # `seen[1]` is the transcript as it stood immediately after the
        # fetch and before anything was read back out of the store — the
        # one moment where "what the model can see of this page" is the
        # question. `seen[-1]` would already carry the section it went and
        # fetched from the store, which is the answer and not the question.
        shown = "\n".join(m.get("content") or "" for m in model.seen[1]
                           if isinstance(m.get("content"), str))
        assert "[truncated:" in shown, \
            "a cut with no marker is worse than no cut: the model cannot " \
            "see that anything is missing"
        assert "Entry 200 was commissioned" not in shown, \
            "the target entry must be in the part the cut removed"

        read_back = [r for r in records
                     if r.get("event") == "tool_result"
                     and r.get("tool") == "mission_result"]
        assert any("145 kW" in json.dumps(r) for r in read_back), \
            "the stored page must give up the section the transcript cut"

    def test_the_answer_is_grounded_in_what_the_store_returned(self, site,
                                                              tmp_path):
        mission = SUITE.mission("the_figure_past_the_cut")
        verdict = score_run(_run_and_keep(mission, "good", site, tmp_path),
                            mission)
        assert verdict.kpis["grounded"] is True


class TestACitationIsCheckedAgainstWhatWasFetched:
    """`must_cite: identifiers: 1` — an answer with no URL is not an answer."""

    def test_an_answer_citing_a_url_it_never_fetched_is_ungrounded(
            self, site, tmp_path):
        mission = SUITE.mission("one_page_one_answer")
        invented = [
            tool("fetch_page_content", url=f"{site}/solar-array.html"),
            answer("The array generated 1482 MWh in 2025 [S1].\n\n"
                   "Sources:\n[S1] https://example.net/solar-2025.html"),
            answer("The array generated 1482 MWh in 2025 [S1].\n\n"
                   "Sources:\n[S1] https://example.net/solar-2025.html"),
        ]
        events = drive(mission, invented, site,
                       tmp_path / "invented-source.jsonl")
        assert score_run(events, mission).kpis["grounded"] is False

    def test_an_answer_that_cites_nothing_is_not_grounded_either(
            self, site, tmp_path):
        """`0/0 supported` used to read as a pass. A minimum is why it does not."""
        mission = SUITE.mission("one_page_one_answer")
        bare = [
            tool("fetch_page_content", url=f"{site}/solar-array.html"),
            answer("The array generated 1482 MWh in 2025."),
            answer("The array generated 1482 MWh in 2025."),
        ]
        events = drive(mission, bare, site, tmp_path / "no-source.jsonl")
        assert score_run(events, mission).kpis["grounded"] is False
