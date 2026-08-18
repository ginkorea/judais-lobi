# tests/test_grant.py — --grant: what an operator may widen, and how far

"""February named three ways a capability gets granted.  This is the third.

``ROADMAP.md`` §2.6b: *"``--grant`` (Feb's second capability-grant mode —
session-scoped pre-authorisation of scopes; the interactive prompt behind
``--gate-wait``'s seam is the first; a policy file the third)"*.  Before
this, the only way to reach one scope was to opt the whole run up to the
profile that carries it: a mission that needed ``http.read`` had to run
under ``ops``, which also hands it ``git.push``, ``pip.install`` and
``fs.delete``.  That is not least privilege, it is a staircase.

Four claims, and each of them is a section below.

* **It widens.**  ``fetch_page_content`` needs ``http.read``, which lives
  in OPS; under ``safe`` it is refused, and with ``--grant http.read`` it
  dispatches — while ``git.push``, the other OPS scope, stays refused.
* **It has a ceiling.**  A scope no profile names is refused *by name*,
  with the known set listed, and ``*`` is refused with the sentence saying
  that ``--profile god`` is what that means.  Not a warning: an operator
  who mistypes a scope and is told nothing watches a mission be refused
  for a capability they believe they granted.
* **It does not widen anything that is not a scope.**  The sandbox, the
  gated set and the skill's closed set are untouched, and a step narrowed
  past the grant is still refused — *naming the grant*, so the refusal
  does not send somebody after a ceiling they have already cleared.
* **It is on the wire and on the console.**  ``mission_started`` gains the
  OPTIONAL ``granted``, absent on every run nobody widened, and the CLI
  says so in a line a person reading a terminal afterwards can find.
"""

import json

import pytest

from core.contracts.schemas import PolicyPack, ProfileMode
from core.policy.profiles import (
    GRANT_FLAG, denial_reason, known_scopes, parse_grants, policy_for_profile,
)
from core.runtime.contract import MISSION_STARTED
from core.runtime.run import Model, Run, ToolPlane
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.tools.descriptors import ToolDescriptor
from tests.test_contract import _faults
from tests.test_mission import ScriptedModel
from tests.test_run import six


# ── the plane and the bus these run against ─────────────────────────────────


def safe_bus(calls=None):
    """A bus under the DEFAULT profile, offering one OPS-scoped tool.

    ``fetch_page_content``'s real descriptor, because the scope that has to
    be granted is a fact about that tool and not about this test: it wants
    ``http.read``, ``http.read`` is in OPS, and the deny-by-default profile
    is SAFE.  That is the exact situation ``ROADMAP.md`` §2.6b calls the
    0.9.0 residual — "``http.read`` is an OPS scope so web research is
    denied under ``safe``/``dev``" — and it is the situation this flag
    exists for.
    """
    engine = CapabilityEngine(policy_for_profile(ProfileMode.SAFE))
    engine.set_profile(ProfileMode.SAFE)
    bus = ToolBus(capability_engine=engine)

    def fetch(**kw):
        if calls is not None:
            calls.append(dict(kw))
        return (0, f"page at {kw.get('url')}", "")

    bus.register(
        ToolDescriptor(tool_name="fetch_page_content",
                       required_scopes=["http.read"],
                       description="Fetches a URL. Second sentence."),
        fetch)
    bus.register(
        ToolDescriptor(tool_name="read_notes", required_scopes=["fs.read"],
                       description="Reads a note. Second sentence."),
        lambda **kw: (0, "a note", ""))
    return bus


def tool_call(name, **arguments):
    return json.dumps({"tool": name, "arguments": arguments})


def answered(text="done"):
    return json.dumps({"answer": text})


def mission(bus, records, *, grant=(), replies=()):
    """One run over *bus*, optionally widened, and what it emitted."""
    built = six(bus, records)
    built["plane"] = ToolPlane(
        bus=bus, offered=["fetch_page_content", "read_notes"]).grant(grant)
    built["model"] = Model(ask=ScriptedModel(*replies))
    return Run(**built).run("fetch the page")


def events(records, event):
    return [record for record in records if record["event"] == event]


# ── it widens ───────────────────────────────────────────────────────────────


class TestAGrantReachesAScopeTheProfileDoesNot:
    """The whole point of the flag, from both sides of one tool call."""

    def test_without_a_grant_the_call_is_refused_naming_the_scope(self):
        calls, records = [], []
        transcript = mission(
            safe_bus(calls), records,
            replies=[tool_call("fetch_page_content", url="http://x/"),
                     answered("could not")])
        assert calls == [], "the tool ran under a profile that denies it"
        result = events(records, "tool_result")[0]
        assert result["ok"] is False
        assert "http.read" in result["output"] + result["error"]

    def test_with_the_grant_the_same_call_dispatches(self):
        calls, records = [], []
        mission(safe_bus(calls), records, grant=["http.read"],
                replies=[tool_call("fetch_page_content", url="http://x/"),
                         answered("fetched")])
        assert calls == [{"url": "http://x/"}]
        assert events(records, "tool_result")[0]["ok"] is True

    def test_a_grant_widens_only_what_it_names(self):
        """``http.read`` and ``git.push`` are both OPS.  Granting one is
        not opting up to the level that carries both — which is the whole
        difference between this flag and ``--profile ops``."""
        engine = safe_bus().capability_engine
        engine.grant_scopes(["http.read"])
        assert engine.check("fetch_page_content", ["http.read"]).allowed
        assert not engine.check("anything", ["git.push"]).allowed

    def test_a_granted_scope_is_not_consumed_by_using_it(self):
        """A session grant is a permission, not a ticket: the second call
        of a run is as allowed as the first.  An invocation-scoped grant
        would be spent by :meth:`CapabilityEngine.check`."""
        engine = safe_bus().capability_engine
        engine.grant_scopes(["http.read"])
        for _ in range(3):
            assert engine.check("fetch_page_content", ["http.read"]).allowed

    def test_granting_the_same_scope_twice_leaves_one_grant(self):
        engine = safe_bus().capability_engine
        engine.grant_scopes(["http.read"])
        assert engine.grant_scopes(["http.read"]) == []
        assert engine.session_scopes() == ["http.read"]


# ── the ceiling ─────────────────────────────────────────────────────────────


class TestWhatAGrantMayNotSay:
    """A grant may name a scope above the profile — that is the point — and
    it may not invent one, and it may not be a wildcard."""

    def test_every_known_scope_is_grantable(self):
        """Derived from ``PROFILE_SCOPES`` and not listed twice, so a scope
        added to a profile is grantable the same day."""
        assert parse_grants([",".join(known_scopes())]) == known_scopes()

    def test_an_unknown_scope_is_refused_by_name(self):
        with pytest.raises(ValueError) as caught:
            parse_grants(["shel.exec"])
        assert "'shel.exec'" in str(caught.value)
        assert "shell.exec" in str(caught.value), \
            "the refusal has to list what the known scopes are"

    def test_the_wildcard_is_refused_and_names_the_flag_that_means_it(self):
        with pytest.raises(ValueError) as caught:
            parse_grants(["*"])
        assert "--profile god" in str(caught.value)

    def test_one_bad_scope_refuses_the_whole_flag(self):
        """Not "grant the good ones and warn": a partly-applied grant is a
        run whose permissions are not the ones anybody typed."""
        with pytest.raises(ValueError):
            parse_grants(["fs.read,nonsense"])

    def test_comma_separated_and_repeatable_are_the_same_grant(self):
        assert parse_grants(["http.read,fs.write"]) == \
            parse_grants(["http.read", "fs.write"]) == \
            ("fs.write", "http.read")

    def test_nothing_granted_is_the_empty_tuple_and_not_a_refusal(self):
        assert parse_grants(None) == () and parse_grants([""]) == ()

    def test_the_flag_names_itself_in_its_own_refusal(self):
        with pytest.raises(ValueError) as caught:
            parse_grants(["nope"])
        assert GRANT_FLAG in str(caught.value)


class TestThePlaneIsTheOneOwnerOfTheCheck:
    """The refusals belong to the object that performs the widening.

    They were written into `parse_grants`, which is the CLI's door, and
    `ToolPlane.grant` took whatever it was handed. So a library caller —
    and `SwarmRunner` is one — could grant `*`, or a scope no profile
    names, have the engine record it, and have the name advertised on
    `mission_started.granted`: a run announcing a capability it does not
    have. The door still refuses first, with the whole known set listed;
    this is the check that cannot be walked around.
    """

    @pytest.fixture
    def bus(self):
        return safe_bus()

    @pytest.fixture
    def plane(self, bus):
        return ToolPlane(bus=bus, offered=["fetch_page_content"])

    def test_a_library_caller_cannot_grant_the_wildcard(self, plane):
        with pytest.raises(ValueError, match=r"\*"):
            plane.grant(["*"])

    def test_the_wildcard_refusal_names_what_it_actually_is(self, plane):
        with pytest.raises(ValueError, match="god"):
            plane.grant(["*"])

    def test_a_scope_no_profile_names_is_refused_by_name(self, plane):
        with pytest.raises(ValueError, match="shel.exec"):
            plane.grant(["shel.exec"])

    def test_the_known_set_is_listed_so_the_typo_is_findable(self, plane):
        with pytest.raises(ValueError) as exc:
            plane.grant(["shel.exec"])
        assert "shell.exec" in str(exc.value)

    def test_nothing_is_granted_and_nothing_is_advertised(self, plane, bus):
        """A refusal leaves the engine and the plane exactly as they were —
        the refusal is not a partial grant."""
        with pytest.raises(ValueError):
            plane.grant(["http.read", "shel.exec"])
        assert plane.granted == ()
        assert bus.capability_engine.session_scopes() == []

    def test_a_known_scope_is_still_granted(self, plane):
        assert plane.grant(["http.read"]).granted == ("http.read",)


class TestAGrantDoesNotWidenWhatIsNotAScope:
    """Three things a grant is not, each stated as a test because each is a
    thing somebody could reasonably have assumed it did."""

    def test_the_sandbox_is_unchanged(self):
        """``python.exec`` granted to a run whose bus sandboxes its
        subprocesses is still a sandboxed run: a grant says what may be
        asked for, never how it is isolated."""
        bus = safe_bus()
        before = bus.sandbox_name
        plane = ToolPlane(bus=bus, offered=[]).grant(["python.exec"])
        assert plane.sandbox == before

    def test_the_gated_set_is_unchanged(self):
        """A gate is a decision about one call; a grant is a decision about
        a capability. Granting the scope a gated tool needs does not
        answer its gate."""
        plane = ToolPlane(bus=safe_bus(), offered=["fetch_page_content"],
                          gated=frozenset({"fetch_page_content"}))
        assert plane.grant(["http.read"]).gated == \
            frozenset({"fetch_page_content"})

    def test_the_closed_set_is_unchanged(self):
        """A scope is not a tool. Granting one offers nothing new."""
        plane = ToolPlane(bus=safe_bus(), offered=["read_notes"])
        assert list(plane.grant(["http.read"]).offered) == ["read_notes"]


class TestARefusalUnderAGrantNamesTheGrant:
    """The one wording change, and the reason for it.

    A granted scope that is *still* denied means something narrower said no
    — a campaign step's effective scopes, a role's ``narrow``. Naming the
    profile there would send an operator to raise a ceiling they have
    already cleared, so the sentence says what actually happened.
    """

    def test_a_narrowed_step_is_refused_naming_the_grant(self):
        engine = safe_bus().capability_engine
        engine.grant_scopes(["http.read"])
        engine.set_scope_constraints(["fs.read"])
        verdict = engine.check("fetch_page_content", ["http.read"])
        assert not verdict.allowed
        assert "granted for this run" in verdict.reason
        assert "http.read" in verdict.reason

    def test_an_ungranted_scope_still_names_the_profile(self):
        """The old sentence, unchanged, for the case it was written for."""
        engine = safe_bus().capability_engine
        verdict = engine.check("fetch_page_content", ["http.read"])
        # The LOWEST profile that grants it — `research` since lane M.
        assert "http.read needs --profile research" in verdict.reason
        assert "granted for this run" not in verdict.reason

    def test_the_two_sentences_come_from_one_function(self):
        assert "granted for this run" in denial_reason(
            ["http.read"], current_profile="safe", granted=["http.read"])
        assert "granted for this run" not in denial_reason(
            ["http.read"], current_profile="safe")


# ── the plane, the object ───────────────────────────────────────────────────


class TestGrantIsNarrowsNeighbour:
    """``narrow`` constrains and ``grant`` widens; one object owns both, so
    "what may this run ask for" is read in one place."""

    def test_grant_returns_a_new_plane_and_leaves_the_old_one(self):
        plane = ToolPlane(bus=safe_bus(), offered=["read_notes"])
        widened = plane.grant(["http.read"])
        assert widened is not plane
        assert plane.granted == () and widened.granted == ("http.read",)

    def test_granting_nothing_returns_the_plane_itself(self):
        plane = ToolPlane(bus=safe_bus(), offered=[])
        assert plane.grant([]) is plane

    def test_the_grant_survives_a_lease_and_a_narrow(self):
        """A child of a widened run is a widened run: `lease` and `narrow`
        both go through `replace`, and a step that lost the grant would be
        a step refused for a capability the operator granted the mission."""
        plane = ToolPlane(bus=safe_bus(), offered=[]).grant(["http.read"])
        assert plane.lease("s1").granted == ("http.read",)
        assert plane.narrow(["http.read"]).granted == ("http.read",)

    def test_a_bus_with_no_capability_engine_is_a_no_op_not_a_failure(self):
        """The reading `narrow` gives: a bus whose dispatch was never
        scope-gated is one there is nothing to widen on. The plane still
        records what was asked for, so the opening frame is honest."""
        class Bare:
            def dispatch(self, *a, **kw):
                raise AssertionError("not called")

            def describe_tool(self, name):
                return {}

        plane = ToolPlane(bus=Bare(), offered=[]).grant(["http.read"])
        assert plane.granted == ("http.read",)

    def test_the_scopes_are_sorted_and_deduplicated(self):
        plane = ToolPlane(bus=safe_bus(), offered=[]).grant(
            ["http.read", "fs.write", "http.read"])
        assert plane.granted == ("fs.write", "http.read")


# ── the wire ────────────────────────────────────────────────────────────────


class TestTheOpeningFrameSaysWhatWasGranted:
    """``profile`` stopped being the whole answer to "what may this run do"
    the moment a scope could be added beside it."""

    def test_a_widened_run_says_so_on_mission_started(self):
        records = []
        mission(safe_bus(), records, grant=["http.read"],
                replies=[answered("hello")])
        assert events(records, MISSION_STARTED)[0]["granted"] == ["http.read"]

    def test_a_run_nobody_widened_carries_no_such_field(self):
        """Absence and not an empty list, which is the rule every OPTIONAL
        field in this contract follows: a consumer that has never heard of
        it reads the stream it always read."""
        records = []
        mission(safe_bus(), records, replies=[answered("hello")])
        assert "granted" not in events(records, MISSION_STARTED)[0]

    def test_the_field_is_declared_and_the_stream_still_conforms(self):
        records = []
        mission(safe_bus(), records, grant=["http.read", "fs.write"],
                replies=[answered("hello")])
        assert _faults(records) == []

    def test_dropping_the_field_leaves_the_records_a_consumer_read(self):
        records = []
        mission(safe_bus(), records, grant=["http.read"],
                replies=[answered("hello")])
        without = [{k: v for k, v in r.items() if k != "granted"}
                   for r in records]
        assert _faults(without) == []

    def test_the_field_is_the_planes_and_the_plane_is_the_one_owner(self):
        """One builder for "is there a field and what does it say", exactly
        as `profile_field` is one — so the console line, the record and a
        library caller cannot disagree about what was granted."""
        plane = ToolPlane(bus=safe_bus(), offered=[])
        assert plane.granted_field == {}
        assert plane.grant(["http.read"]).granted_field == {
            "granted": ["http.read"]}


# ── the command line ────────────────────────────────────────────────────────


class TestTheFlag:
    def test_the_parser_takes_it_comma_separated_and_repeated(self):
        from tests.test_contract import _mission_parser

        args = _mission_parser().parse_args(
            ["go", "--grant", "http.read,fs.write", "--grant", "git.push"])
        assert args.grant == ["http.read,fs.write", "git.push"]

    def test_a_bad_scope_is_a_refusal_at_the_door(self):
        from core.cli import _grants_of

        with pytest.raises(SystemExit) as caught:
            _grants_of(type("A", (), {"grant": ["nonsense"]})())
        assert "nonsense" in str(caught.value)

    def test_the_cli_helper_returns_what_the_parser_gave_it(self):
        from core.cli import _grants_of

        assert _grants_of(
            type("A", (), {"grant": ["http.read,fs.write"]})()) == \
            ("fs.write", "http.read")

    def test_a_command_line_with_no_grant_widens_nothing(self):
        from core.cli import _grants_of

        assert _grants_of(type("A", (), {})()) == ()

    def test_the_plane_builder_applies_it(self):
        """`_plane_of` is the CLI's one call onto `ToolPlane`, so the
        widening happens where the plane is made and nowhere else."""
        from core.cli import _plane_of

        plane = _plane_of(safe_bus(), ["read_notes"], frozenset(), None,
                          None, ("http.read",))
        assert plane.granted == ("http.read",)
        assert plane.bus.capability_engine.session_scopes() == ["http.read"]


# ── the constraint is per task, because two children can run at once ────────


class TestTwoChildrenMayBeNarrowedDifferently:
    """Why the engine's allowlist is a context variable.

    One engine hangs off one bus and the bus is shared by identity, so that
    two children of a run cannot end up governed differently *by accident*.
    Since lane D two children can run at the same time and each may be
    narrowed to its own step's scopes on purpose — which an attribute could
    not express: the last narrow before the ``gather`` would win for
    everybody, and a step would silently run under a sibling's permissions.
    """

    def test_a_narrow_inside_one_task_does_not_reach_its_sibling(self):
        import asyncio

        engine = CapabilityEngine(PolicyPack(allowed_scopes=["*"]))

        async def child(scopes, seen):
            engine.set_scope_constraints(scopes)
            await asyncio.sleep(0)
            seen.append(sorted(engine.scope_constraints))

        async def both():
            seen = []
            await asyncio.gather(child(["fs.read"], seen),
                                 child(["http.read"], seen))
            return seen

        assert sorted(asyncio.run(both())) == [["fs.read"], ["http.read"]]

    def test_a_narrow_inside_a_task_does_not_leak_to_the_parent(self):
        import asyncio

        engine = CapabilityEngine(PolicyPack(allowed_scopes=["*"]))

        async def parent():
            async def child():
                engine.set_scope_constraints(["fs.read"])

            await asyncio.gather(child())
            return engine.scope_constraints

        assert asyncio.run(parent()) is None

    def test_the_constraint_reaches_the_worker_thread_a_dispatch_runs_on(
            self):
        """A dispatch goes out through :func:`asyncio.to_thread`, which
        copies the context — so a narrow set in a child's coroutine is
        still in force where the check actually happens.  Without that, a
        step's least privilege would be a decoration."""
        import asyncio

        engine = CapabilityEngine(PolicyPack(allowed_scopes=["*"]))

        async def child():
            engine.set_scope_constraints(["fs.read"])
            return await asyncio.to_thread(
                engine.check, "anything", ["http.read"])

        assert not asyncio.run(child()).allowed

    def test_a_synchronous_caller_sees_what_it_always_saw(self):
        """The kernel orchestrator narrows once per phase in one thread,
        and this method behaved as a plain attribute for it. It still
        does."""
        engine = CapabilityEngine(PolicyPack(allowed_scopes=["*"]))
        engine.set_scope_constraints(["fs.read"])
        assert engine.scope_constraints == ["fs.read"]
        assert not engine.check("anything", ["http.read"]).allowed
        engine.clear_scope_constraints()
        assert engine.scope_constraints is None
        assert engine.check("anything", ["http.read"]).allowed
