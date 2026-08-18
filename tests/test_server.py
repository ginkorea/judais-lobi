# tests/test_server.py — the run store over HTTP, and the three rules it lives by

"""What a long-lived event stream is actually killed by, asserted.

The endpoints are the easy half and they are here for completeness. The half
worth the file is the operational one, because every rule in
:mod:`core.server.sse` is a rule about a *socket* — a proxy's connection
ceiling, a proxy's idle timeout, a status code a client has already stopped
being able to see — and none of them can be found by exercising the happy
path. A stream that works is indistinguishable from a stream that works; the
difference shows up at the 65th follower, at 60 seconds of silence, and at
the moment something fails after the response has started.

So each rule is tested twice over: once against
:func:`core.server.sse.stream` with a fake clock and a list, which is
deterministic and where the mutation shows, and once through the real
endpoint. Three tests bind a real port, because starlette's ``TestClient``
and httpx's ASGI transport both collect a response body before returning it
— which is fine for a run that has ended and useless for the questions
"does a heartbeat arrive" and "is the slot given back when the client walks
away".

Nothing here asserts a new record type. The server is a client of the store
and the wire is unchanged; ``TestTheRecordsAreTheRecordsOnDisk`` is the test
that says so.
"""

import ast
import contextlib
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("starlette", reason="the [server] extra is not installed")
pytest.importorskip("uvicorn", reason="the [server] extra is not installed")

import httpx                                    # noqa: E402 - after the skip
from starlette.testclient import TestClient     # noqa: E402 - after the skip

from core.durable import RunStore               # noqa: E402
from core.runtime import agui, contract         # noqa: E402
from core.server import (                       # noqa: E402
    SERVER_REQUIREMENT, WHY_NO_CONTROL_ENDPOINT, ServerUnavailable, create_app,
    reconcile_hook, require_server, resolve_store,
)
from core.server import sse                     # noqa: E402
from core.server.sse import (                   # noqa: E402
    HEARTBEAT, HEARTBEAT_S, MAX_STREAMS, PAGE_MAX, RETRY_AFTER_S,
    TRANSPORT_ERROR, AtCapacity, BadCursor, Records, StreamSlots, frame,
    page_size, parse_cursor, stream,
)

REPO = Path(__file__).resolve().parent.parent


# ── fixtures and the small readers ───────────────────────────────────────────

def a_mission(objective="find the thing"):
    """One whole run's records, in the order a mission produces them.

    Realistic rather than minimal — ``conforms`` is asserted over them in
    :class:`TestTheRecordsAreTheRecordsOnDisk`, so a field the contract
    starts requiring breaks this fixture rather than being quietly untested.
    """
    return [
        {"event": contract.MISSION_STARTED, "schema_version": 1,
         "objective": objective, "catalogue": ["read_file"], "gated": [],
         "max_steps": 0, "history": 0},
        {"event": contract.STEP_STARTED, "index": 1},
        {"event": contract.TOOL_CALL, "index": 1, "call": 1,
         "tool": "read_file", "arguments": {"path": "a.txt"}},
        {"event": contract.TOOL_RESULT, "index": 1, "call": 1,
         "tool": "read_file", "arguments": {"path": "a.txt"}, "ok": True,
         "exit_code": 0, "output": "42 widgets, é", "error": "",
         "handle": "", "truncated": False},
        {"event": contract.ANSWER, "index": 1, "text": "42 widgets",
         "outcome": "answered"},
        {"event": contract.GROUNDING, "ran": True, "grounded": True,
         "verified": 1, "repairs": 0, "repairing": False, "caveat": "",
         "unsupported": [], "silent": [], "uncited": [], "checks": []},
        {"event": contract.MISSION_FINISHED, "outcome": "answered",
         "steps": 1, "max_steps": 0, "elapsed_s": 0.5},
    ]


@pytest.fixture
def store(tmp_path):
    return RunStore(tmp_path / "runs")


@pytest.fixture
def finished(store):
    """A run with the whole of :func:`a_mission` on its log."""
    run = store.create(meta={"objective": "find the thing"})
    for record in a_mission():
        store.append(run.run_id, record)
    return run.run_id


@pytest.fixture
def thinking(store):
    """A run that has opened its stream and said nothing since."""
    run = store.create(meta={"objective": "think about it"})
    store.append(run.run_id, a_mission()[0])
    return run.run_id


def client_for(store, **kwargs):
    """A ``TestClient`` and the app behind it, so a test can read the slots.

    ``poll_s`` is small everywhere: the store's default is a second, and a
    test that waits a second per idle tick is a test somebody switches off.
    """
    kwargs.setdefault("poll_s", 0.01)
    app = create_app(store, **kwargs)
    return TestClient(app), app


def frames(text):
    """An event-stream body as a list of dicts.

    Comments come back as ``{"comment": ...}``, which is how the heartbeat is
    told apart from a record without either of them having to know about the
    other.
    """
    out = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        if block.startswith(":"):
            out.append({"comment": block[1:].strip()})
            continue
        item = {}
        for line in block.split("\n"):
            key, _, value = line.partition(": ")
            if key == "data":
                item["data"] = json.loads(value)
            elif key == "id":
                item["id"] = int(value)
            elif key == "event":
                item["event"] = value
        out.append(item)
    return out


@contextlib.contextmanager
def serving(app):
    """The app on a real ephemeral port, in a thread, for the length of a test.

    Bounded at both ends: the wait for ``started`` and the join both have a
    deadline, so a server that will not come up or will not go down fails the
    test rather than hanging the suite.
    """
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=0, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started, "the test server did not come up"
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def until(predicate, seconds=5.0):
    """Wait for something a background thread does, or give up and let the
    assertion that follows say what was expected."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# ── the endpoints ────────────────────────────────────────────────────────────


class TestTheEndpoints:
    def test_healthz_says_what_the_cap_is(self, store):
        client, _ = client_for(store, max_streams=7)
        body = client.get("/healthz").json()
        assert body["ok"] is True
        assert body["schema_version"] == contract.SCHEMA_VERSION
        assert body["streams"] == 0 and body["max_streams"] == 7

    def test_runs_lists_newest_first(self, store):
        older = store.create(meta={"objective": "one"})
        time.sleep(1.05)                        # created_at is to the second
        newer = store.create(meta={"objective": "two"})
        client, _ = client_for(store)
        listed = client.get("/runs").json()
        assert [r["run_id"] for r in listed["runs"]] == [newer.run_id,
                                                         older.run_id]
        assert listed["total"] == 2

    def test_the_page_is_bounded(self, store):
        for _ in range(4):
            store.create(meta={})
        client, _ = client_for(store)
        page = client.get("/runs?limit=2").json()
        assert len(page["runs"]) == 2 and page["total"] == 4
        assert page["limit"] == 2
        second = client.get("/runs?limit=2&offset=2").json()
        assert len(second["runs"]) == 2
        assert {r["run_id"] for r in second["runs"]} \
            .isdisjoint({r["run_id"] for r in page["runs"]})

    def test_an_enormous_limit_is_clamped_and_not_obeyed(self):
        """A store is a directory that grows for as long as a deployment
        runs; ``limit=100000`` is a request to read every ``meta.json`` on
        the disk."""
        assert page_size("100000") == PAGE_MAX
        assert page_size(None) == sse.PAGE_DEFAULT
        assert page_size("nonsense") == sse.PAGE_DEFAULT
        assert page_size("0") == 1

    def test_one_runs_metadata(self, store, finished):
        client, _ = client_for(store)
        body = client.get(f"/runs/{finished}").json()
        assert body["run_id"] == finished
        assert body["meta"]["objective"] == "find the thing"
        assert body["last_seq"] == len(a_mission())

    def test_an_unknown_run_and_a_traversal_get_the_same_answer(self, store):
        """:class:`core.durable.NoSuchRun` refuses to let a caller tell a
        typo from an attempt at a directory, and neither does this."""
        client, _ = client_for(store)
        assert client.get("/runs/run_nope").status_code == 404
        assert client.get("/runs/never-minted-here").status_code == 404
        assert client.get("/runs/run_nope/events").status_code == 404
        assert client.get("/runs/never-minted-here/events").status_code == 404

    def test_the_whole_run_streams_and_the_stream_ends(self, store, finished):
        client, _ = client_for(store)
        response = client.get(f"/runs/{finished}/events")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache, no-transform"
        assert response.headers["x-accel-buffering"] == "no"
        got = frames(response.text)
        assert [f["event"] for f in got] == [r["event"] for r in a_mission()]
        assert [f["id"] for f in got] == list(range(1, len(a_mission()) + 1))


# ── the records are the records ──────────────────────────────────────────────


class TestTheRecordsAreTheRecordsOnDisk:
    """The server is a client of the store, and a client that edited what it
    served would be a second author of a document the contract owns."""

    def test_the_fixture_is_a_conforming_stream(self):
        for record in a_mission():
            assert contract.conforms(record) == []

    def test_every_frame_round_trips_to_the_envelope_on_disk(
            self, store, finished):
        client, _ = client_for(store)
        got = frames(client.get(f"/runs/{finished}/events").text)
        on_disk = store.since(finished)
        assert len(got) == len(on_disk)
        for served, envelope in zip(got, on_disk):
            assert served["data"] == envelope["record"]
            assert served["id"] == envelope["seq"]
            assert served["event"] == envelope["record"]["event"]

    def test_nothing_is_widened_and_nothing_is_added(self, store, finished):
        """Already scrubbed at the emitter by :mod:`core.redact`, so this
        must not scrub again — and must not put back anything that is not on
        the disk either. Key sets, equal both ways."""
        client, _ = client_for(store)
        got = frames(client.get(f"/runs/{finished}/events").text)
        for served, envelope in zip(got, store.since(finished)):
            assert set(served["data"]) == set(envelope["record"])

    def test_the_envelope_itself_does_not_travel(self, store, finished):
        """``seq`` belongs in the SSE ``id:`` line and not in the record: a
        consumer switching on ``event`` reads exactly what it read off the
        NDJSON stream."""
        client, _ = client_for(store)
        for served in frames(client.get(f"/runs/{finished}/events").text):
            assert "seq" not in served["data"] and "at" not in served["data"]

    def test_the_transport_error_is_not_one_of_the_contracts_events(self):
        """The one frame this package authors. A consumer can tell it from a
        mission record without being told which is which."""
        assert TRANSPORT_ERROR not in contract.EVENTS


# ── rule (a): the cap below the connection ceiling ───────────────────────────


class TestTheStreamCapIsBelowTheConnectionCeiling:
    """:data:`core.server.sse.MAX_STREAMS`.

    An event stream is a connection held for the length of a mission. The
    failure it prevents has no error message in it: the request that
    exhausts the proxy's ceiling is refused by the proxy, every client sees a
    generic 502, and this process's logs say nothing at all.
    """

    def test_the_default_is_documented_as_a_number_to_put_under_another(self):
        """A cap whose reason is not written next to it is a number the next
        operator raises without raising the ceiling it sits under."""
        assert MAX_STREAMS == 64
        source = (REPO / "core" / "server" / "sse.py").read_text()
        assert "below the connection ceiling" in source.lower()
        assert "MAX_STREAMS = 64" in source

    def test_the_slots_refuse_the_one_past_the_limit(self):
        slots = StreamSlots(2)
        first = slots.claim()
        slots.claim()
        assert slots.active == 2
        with pytest.raises(AtCapacity):
            slots.claim()
        first()
        assert slots.active == 1
        assert slots.claim()                    # the freed slot is reusable

    def test_releasing_the_same_claim_twice_does_not_free_two(self):
        """The transport releases from the one place that always runs, and a
        generator finalizer may get there too. Counting one disconnect twice
        frees a slot that is still occupied, and the process then serves more
        streams than its cap — which is the cap not existing.

        Asserted with a *second* stream open, because a double release of
        the only claim is hidden by the floor at zero."""
        slots = StreamSlots(2)
        first = slots.claim()
        slots.claim()
        assert slots.active == 2
        first()
        first()
        assert slots.active == 1, "one disconnect freed two slots"
        with pytest.raises(AtCapacity):
            slots.claim(), slots.claim()

    def test_the_endpoint_refuses_with_503_and_a_retry_after(
            self, store, finished):
        client, app = client_for(store, max_streams=1)
        held = app.state.slots.claim()
        try:
            response = client.get(f"/runs/{finished}/events")
        finally:
            held()
        assert response.status_code == 503
        assert response.headers["retry-after"] == str(RETRY_AFTER_S)

    def test_the_refusal_comes_before_the_first_byte(self, store, finished):
        """A 503 with a ``text/event-stream`` body would be a stream that had
        already started, which is the thing rule (c) forbids."""
        client, app = client_for(store, max_streams=1)
        held = app.state.slots.claim()
        try:
            response = client.get(f"/runs/{finished}/events")
        finally:
            held()
        assert not response.headers["content-type"].startswith(
            "text/event-stream")
        assert response.json()["error"]

    def test_a_refused_follower_did_not_take_a_slot_on_its_way_out(
            self, store, finished):
        client, app = client_for(store, max_streams=1)
        held = app.state.slots.claim()
        try:
            client.get(f"/runs/{finished}/events")
            client.get("/runs/run_nope/events")
            client.get(f"/runs/{finished}/events?since=nonsense")
            assert app.state.slots.active == 1
        finally:
            held()
        assert app.state.slots.active == 0

    def test_a_finished_stream_gives_its_slot_back(self, store, finished):
        client, app = client_for(store, max_streams=1)
        assert client.get(f"/runs/{finished}/events").status_code == 200
        assert app.state.slots.active == 0
        assert client.get(f"/runs/{finished}/events").status_code == 200


# ── rule (b): the heartbeat inside the socket write timeout ──────────────────


class TestTheHeartbeatIsInsideTheSocketWriteTimeout:
    """:data:`core.server.sse.HEARTBEAT_S`.

    A mission that is thinking emits nothing for minutes. An idle socket is
    what a proxy cuts, and a cut stream is indistinguishable from an agent
    still working — ``EXIT_CONTRACT["finished"]``'s own failure, arriving by
    a different road.
    """

    def test_the_default_is_a_fraction_of_the_common_sixty_second_timeout(self):
        assert HEARTBEAT_S == 15.0
        assert HEARTBEAT_S * 3 < 60, (
            "three heartbeats have to fit inside the commonest proxy timeout")

    def test_an_idle_stream_gets_one_every_heartbeat_s(self):
        """A fake clock, so the interval is asserted and not approximated:
        the store's wait times out every 5 seconds of clock and the
        heartbeat is due at 15, 30 and 45."""
        now = [0.0]

        def idling(times):
            for _ in range(times):
                now[0] += 5.0
                yield None

        out = list(stream(idling(9), Records(), heartbeat_s=15.0,
                          clock=lambda: now[0]))
        assert out == [HEARTBEAT, HEARTBEAT, HEARTBEAT]

    def test_it_is_measured_from_the_last_byte_and_not_the_last_heartbeat(
            self):
        """A run that is talking never sends one. Measured from the last
        heartbeat instead, a run emitting a record every ten seconds would
        get a comment line between every pair of them — noise a client has
        to learn to ignore, on the stream least in need of one."""
        now = [0.0]

        def talking():
            """A record every ten seconds, with an idle tick between each
            pair — a mission that is working steadily."""
            for ordinal in range(1, 5):
                yield {"seq": ordinal,
                       "record": {"event": contract.STEP_STARTED,
                                  "index": ordinal}}
                now[0] += 10.0
                yield None

        out = list(stream(talking(), Records(), heartbeat_s=15.0,
                          clock=lambda: now[0]))
        assert out.count(HEARTBEAT) == 0, (
            "a run that has never been silent for 15s sends no heartbeat; "
            "measured from the last heartbeat instead, this run gets one "
            "between every other pair of records")
        assert len(out) == 4

    def test_the_comment_is_a_comment_and_not_an_event(self):
        """Two bytes of colon: ignored by every SSE client and by the
        specification, so a heartbeat cannot be mistaken for a record."""
        assert HEARTBEAT.startswith(": ") and HEARTBEAT.endswith("\n\n")
        assert "event:" not in HEARTBEAT and "data:" not in HEARTBEAT

    def test_heartbeats_actually_reach_a_socket(self, store, thinking):
        """The one question the in-process client cannot answer: starlette's
        ``TestClient`` and httpx's ASGI transport both collect the whole body
        before returning it, so "did bytes arrive while nothing happened" has
        to be asked over a real port."""
        app = create_app(store, heartbeat_s=0.05, poll_s=0.02)
        seen = []
        with serving(app) as base:
            with httpx.stream("GET", f"{base}/runs/{thinking}/events",
                              timeout=3.0) as response:
                assert response.status_code == 200
                try:
                    for line in response.iter_lines():
                        seen.append(line)
                        if sum(1 for s in seen
                               if s.startswith(": heartbeat")) >= 2:
                            break
                except httpx.ReadTimeout:       # nothing arrived: the failure
                    pass
        assert sum(1 for s in seen if s.startswith(": heartbeat")) >= 2, seen


# ── rule (c): no refusal after the first byte ────────────────────────────────


class TestNoRefusalAfterTheFirstByte:
    """Once the response has started the status is 200 forever.

    A client that has parsed a 200 and started rendering cannot see a 500
    that arrives later; what it sees is a stream that stopped, which is the
    spinner-forever state again.
    """

    def test_an_unreadable_cursor_is_400_before_anything(self, store, finished):
        client, _ = client_for(store)
        for bad in ("abc", "1.5", "-3"):
            response = client.get(f"/runs/{finished}/events?since={bad}")
            assert response.status_code == 400, bad
            assert not response.headers["content-type"].startswith(
                "text/event-stream")

    def test_the_cursor_is_never_quietly_defaulted(self):
        """Replaying a whole mission to a client that asked to resume near
        the end is the failure that looks like the harness repeating
        itself."""
        with pytest.raises(BadCursor):
            parse_cursor("abc")
        with pytest.raises(BadCursor):
            parse_cursor(None, "not-a-number")
        with pytest.raises(BadCursor):
            parse_cursor("-1")
        assert parse_cursor(None, None) == 0
        assert parse_cursor("", "") == 0
        assert parse_cursor(" 7 ") == 7

    def test_a_store_failure_mid_follow_becomes_a_final_frame(
            self, store, thinking, monkeypatch):
        """Not a 500: the 200 went out several records ago."""
        real = store.since
        calls = {"n": 0}

        def flaky(run_id, cursor=0):
            # Two reads happen before the follow: the connect-time tail
            # read that asks whether this run already ended, and the
            # replay. The third is the first poll of the follow, and that
            # is the one that breaks — after the 200 has gone out.
            calls["n"] += 1
            if calls["n"] > 2:
                raise OSError("the run directory went away")
            return real(run_id, cursor)

        monkeypatch.setattr(store, "since", flaky)
        client, _ = client_for(store)
        response = client.get(f"/runs/{thinking}/events")
        assert response.status_code == 200
        got = frames(response.text)
        assert got[0]["event"] == contract.MISSION_STARTED
        assert got[-1]["event"] == TRANSPORT_ERROR
        assert got[-1]["data"]["error"] == "OSError"
        assert "went away" in got[-1]["data"]["detail"]

    def test_the_loop_never_raises_into_a_transport(self):
        """Directly, because a transport that received an exception here
        would answer it with a status code nobody can read."""
        def exploding():
            yield {"seq": 1, "record": {"event": contract.STEP_STARTED,
                                        "index": 1}}
            raise RuntimeError("boom")

        out = list(stream(exploding(), Records()))
        assert out[-1].startswith(f"event: {TRANSPORT_ERROR}\n")
        assert "boom" in out[-1]

    def test_a_renderer_that_fails_is_the_same_answer(self):
        class Broken:
            finished = False

            def feed(self, envelope):
                raise ValueError("cannot render")
                yield ""                        # pragma: no cover

            def close(self):
                return iter(())

        out = list(stream([{"seq": 1, "record": {"event": "x"}}], Broken()))
        assert out == [frame(TRANSPORT_ERROR,
                             {"error": "ValueError",
                              "detail": "cannot render"})]


# ── rule (d): a run that ends closes, a client that leaves frees a slot ──────


class TestARunThatEndsClosesTheStream:
    def test_the_terminal_record_ends_it(self, store, finished):
        """``mission_finished`` comes out of a ``finally`` and is the
        contract's own end of stream. A follower that kept waiting after it
        would hold a slot for a run that is over."""
        client, app = client_for(store)
        got = frames(client.get(f"/runs/{finished}/events").text)
        assert got[-1]["event"] == contract.MISSION_FINISHED
        assert app.state.slots.active == 0

    def test_nothing_after_the_terminal_record_is_served(self, store, finished):
        """A second ``mission_finished`` appended by a reconciliation that
        raced the run's own must not extend somebody's stream."""
        store.append(finished, {"event": contract.MISSION_FINISHED,
                                "outcome": "incomplete", "steps": 1,
                                "max_steps": 0})
        client, _ = client_for(store)
        got = frames(client.get(f"/runs/{finished}/events").text)
        assert [f["event"] for f in got].count(contract.MISSION_FINISHED) == 1

    def test_a_reconciled_orphan_closes_it_too(self, store, thinking):
        """The other way a run ends: nobody is going to write its terminal
        record, so :func:`core.runtime.resume.reconcile_orphans` does — and
        the follower sees the ending it always had, through the ordinary
        path, with no word to learn about the reconciliation."""
        from core.runtime.resume import reconcile_orphans

        assert reconcile_orphans(store, stale_s=0.0) == [thinking]
        client, app = client_for(store)
        got = frames(client.get(f"/runs/{thinking}/events").text)
        assert got[-1]["event"] == contract.MISSION_FINISHED
        assert got[-1]["data"]["outcome"] == "incomplete"
        assert app.state.slots.active == 0

    def test_the_reconcile_hook_asks_at_most_once_a_window(self, store,
                                                            monkeypatch):
        """Sixty followers must not scan the store sixty times a minute. The
        hook decides *when to ask*; whether a run is an orphan stays the
        rule :func:`~core.runtime.resume.reconcile_orphans` owns, which is
        why this counts calls rather than looking at a log."""
        from core.runtime import resume

        asked = []
        monkeypatch.setattr(resume, "reconcile_orphans",
                            lambda store, **kw: asked.append(store) or [])
        now = [0.0]
        hook = reconcile_hook(store, stale_s=10.0, clock=lambda: now[0])
        hook(), hook()
        assert asked == []                      # not due
        now[0] = 11.0
        hook(), hook(), hook()
        assert len(asked) == 1
        now[0] = 22.0
        hook()
        assert len(asked) == 2

    def test_a_watcher_does_not_close_anybodys_log_unless_asked(
            self, store, finished, monkeypatch):
        """Off by default. ``reconcile_orphans`` cannot tell a dead run from
        a slow one, and a terminal record written into a *live* run's log by
        a process that is only watching is the one failure this server would
        cause rather than merely observe."""
        import core.server as server

        seen = {}
        real = server.stream

        def spy(envelopes, renderer, **kwargs):
            seen.update(kwargs)
            return real(envelopes, renderer, **kwargs)

        monkeypatch.setattr(server, "stream", spy)
        client, _ = client_for(store)
        client.get(f"/runs/{finished}/events")
        assert seen["on_idle"] is None
        client, _ = client_for(store, reconcile=True)
        client.get(f"/runs/{finished}/events")
        assert callable(seen["on_idle"])

    def test_housekeeping_that_fails_does_not_end_somebodys_stream(self):
        """It is called on every idle tick of every follower. A store that
        cannot be listed is a reason to stop reconciling, not a reason to
        cut a stream that is otherwise working."""
        calls = []

        def angry():
            calls.append(1)
            raise OSError("the store is unreadable")

        now = [0.0]

        def idling():
            for _ in range(3):
                now[0] += 5.0
                yield None

        out = list(stream(idling(), Records(), heartbeat_s=15.0,
                          clock=lambda: now[0], on_idle=angry))
        assert len(calls) == 3
        assert out == [HEARTBEAT]

    def test_a_client_that_walks_away_gives_the_slot_back(self, store,
                                                          thinking):
        """The count going back down is the whole test: a cap whose
        accounting leaks downwards refuses everybody after enough
        disconnects."""
        app = create_app(store, max_streams=1, heartbeat_s=0.02, poll_s=0.02)
        with serving(app) as base:
            with httpx.stream("GET", f"{base}/runs/{thinking}/events",
                              timeout=5.0) as response:
                assert response.status_code == 200
                next(response.iter_lines())
                assert app.state.slots.active == 1
            assert until(lambda: app.state.slots.active == 0), \
                "the slot was not released when the client disconnected"
            # And the freed slot is usable, which is what "released" has to
            # mean for the next follower.
            with httpx.stream("GET", f"{base}/runs/{thinking}/events",
                              timeout=5.0) as second:
                assert second.status_code == 200


# ── rule (e): resuming, and a cursor past the end ────────────────────────────


class TestResumingWhereAClientGotTo:
    def test_since_replays_from_after_the_cursor(self, store, finished):
        client, _ = client_for(store)
        got = frames(client.get(f"/runs/{finished}/events?since=4").text)
        assert [f["id"] for f in got] == [5, 6, 7]

    def test_last_event_id_does_the_same(self, store, finished):
        """What a browser's ``EventSource`` sends by itself after a
        reconnect, without the caller having to remember anything."""
        client, _ = client_for(store)
        got = frames(client.get(f"/runs/{finished}/events",
                                headers={"Last-Event-ID": "5"}).text)
        assert [f["id"] for f in got] == [6, 7]

    def test_an_explicit_since_wins_over_the_reconnect_header(self, store,
                                                              finished):
        """One is what this request asked for, the other is where the
        previous connection happened to get to; the newer opinion wins."""
        client, _ = client_for(store)
        got = frames(client.get(f"/runs/{finished}/events?since=6",
                                headers={"Last-Event-ID": "1"}).text)
        assert [f["id"] for f in got] == [7]

    def test_a_cursor_past_the_end_returns_nothing_and_follows(self, store,
                                                               thinking):
        """It must not replay from zero, it must not refuse, and above all
        it must not go deaf.

        The store yields what is ``seq > cursor``, so an unclamped 99 would
        hand this follower nothing at all — not now, and not for the next
        97 records either. That is the blank-pane failure ``core.durable``
        is written about, arriving from the reader's side.
        """
        client, app = client_for(store, heartbeat_s=0.0)
        appended = threading.Thread(
            target=lambda: (time.sleep(0.15),
                            store.append(thinking, a_mission()[-1])))
        appended.start()
        try:
            got = frames(client.get(f"/runs/{thinking}/events?since=99").text)
        finally:
            appended.join(timeout=5)
        records = [f for f in got if "event" in f]
        assert [f["event"] for f in records] == [contract.MISSION_FINISHED]
        assert records[0]["id"] == 2, "the clamp must not renumber anything"
        assert app.state.slots.active == 0

    def test_the_clamp_does_not_replay_what_the_client_already_has(
            self, store, finished):
        """Clamping to the end is not clamping to zero: a client ahead of
        the log gets the end of it, and nothing it has already seen."""
        client, _ = client_for(store)
        got = frames(client.get(f"/runs/{finished}/events?since=1000").text)
        assert got == []

    def test_the_id_is_the_stores_own_sequence_number(self, store, finished):
        client, _ = client_for(store)
        got = frames(client.get(f"/runs/{finished}/events").text)
        assert [f["id"] for f in got] == [e["seq"]
                                          for e in store.since(finished)]


# ── the AG-UI variant ────────────────────────────────────────────────────────


class TestTheAguiVariantIsTheOneTranslator:
    def test_it_is_frame_for_frame_what_the_translator_produces(
            self, store, finished):
        """One translator, not a second. The frames a browser gets over HTTP
        are the frames :func:`core.runtime.agui.translate` produces over the
        same records — asserted, so the two cannot drift."""
        client, _ = client_for(store)
        got = frames(client.get(f"/runs/{finished}/agui").text)
        expected = list(agui.translate(store.records(finished),
                                       run_id=finished))
        assert [f["data"] for f in got] == expected
        assert [f["event"] for f in got] == [f["type"] for f in expected]

    def test_the_id_goes_on_the_last_frame_of_a_record_and_no_other(self):
        """One record can become several frames. ``Last-Event-ID`` means "I
        have all of this seq", so a client cut off after the second of them
        must resume at the record before, not in the middle of one —
        stamping the id on the first frame would make it mean "I have some
        of it"."""
        renderer = sse.Agui(run_id="run_x")
        list(renderer.feed({"seq": 1, "record": a_mission()[0]}))
        out = list(renderer.feed({"seq": 5, "record": a_mission()[4]}))
        assert len(out) > 1, "the answer record should fan out"
        assert [chunk for chunk in out if "\nid: " in chunk] == [out[-1]]
        assert "\nid: 5\n" in out[-1]

    def test_the_ids_a_whole_translation_carries_are_the_stores_own(
            self, store, finished):
        client, _ = client_for(store)
        ids = [f.get("id") for f in frames(
            client.get(f"/runs/{finished}/agui").text)]
        stamped = [value for value in ids if value is not None]
        assert stamped == sorted(set(stamped))
        assert stamped[-1] == store.meta(finished).last_seq
        assert None in ids, "some records fan out into several frames"

    def test_resuming_the_translation_starts_where_the_client_got_to(
            self, store, finished):
        client, _ = client_for(store)
        got = frames(client.get(f"/runs/{finished}/agui",
                                headers={"Last-Event-ID": "5"}).text)
        assert got, "a resumed translation must still produce frames"
        assert all(f["id"] > 5 for f in got if "id" in f)

    def test_a_translation_that_never_saw_the_ending_says_so(self):
        """:meth:`Translator.close` is called at the end of the stream, so a
        run that stopped without its terminal record becomes a ``RUN_ERROR``
        rather than a pane that keeps spinning."""
        out = list(stream([{"seq": 1, "record": a_mission()[0]}],
                          sse.Agui(run_id="run_x")))
        assert f"event: {agui.RUN_ERROR}" in out[-1]


# ── the extra, and the refusal that names it ─────────────────────────────────


def _repo_env():
    """This checkout on ``PYTHONPATH``, for a subprocess started from a
    script somewhere else: ``sys.path[0]`` is the script's directory and not
    the working directory, so ``import core`` would otherwise find whatever
    is installed rather than what is being tested."""
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _setup_extras():
    tree = ast.parse((REPO / "setup.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "setup":
            for kw in node.keywords:
                if kw.arg == "extras_require":
                    return ast.literal_eval(kw.value)
    raise AssertionError("setup.py has no extras_require")


class TestTheExtraIsDeclaredAndTheRefusalNamesIt:
    def test_the_extra_exists_and_is_the_two_wheels_it_says(self):
        extras = _setup_extras()
        assert extras["server"] == ["starlette>=0.37", "uvicorn>=0.30"]

    def test_the_refusal_names_an_extra_that_carries_the_stack(self):
        """The lesson ``TestARefusalNamesAnExtraThatFixesIt`` in
        ``tests/test_packaging.py`` records: a sentence pointing at an extra
        that does not carry the thing is worse than no sentence."""
        source = (REPO / "core" / "server" / "__init__.py").read_text()
        assert "judais-lobi[server]" in source
        offered = {re.split(r"[<>=;\[ ]", item)[0]
                   for item in _setup_extras()["server"]}
        assert offered == {"starlette", "uvicorn"}

    def test_the_pin_in_the_refusal_is_the_pin_in_setup_py(self):
        """``extras_require`` is read with :func:`ast.literal_eval`, so the
        floors cannot be a shared name and have to be written twice. This is
        what keeps the two copies honest — the refusal quotes a pin an
        operator is about to type."""
        for item in _setup_extras()["server"]:
            assert item in SERVER_REQUIREMENT, item

    def test_require_server_refuses_by_name_when_the_stack_is_missing(
            self, monkeypatch):
        import builtins
        real = builtins.__import__

        def blocked(name, *args, **kwargs):
            if name.split(".")[0] == "starlette":
                raise ImportError("No module named 'starlette'")
            return real(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocked)
        with pytest.raises(ServerUnavailable) as caught:
            require_server()
        assert "pip install 'judais-lobi[server]'" in str(caught.value)

    def test_the_package_imports_without_the_extra_installed(self, tmp_path):
        """A subprocess with starlette and uvicorn poisoned in
        ``sys.modules``: importing ``core.server`` must still work, because
        an extra that breaks ``import core`` is not optional."""
        script = tmp_path / "no_extra.py"
        script.write_text(
            "import sys\n"
            "sys.modules['starlette'] = None\n"
            "sys.modules['uvicorn'] = None\n"
            "import core.server\n"
            "import core.server.sse\n"
            "assert core.server.WHY_NO_CONTROL_ENDPOINT\n"
            "print('imported')\n", encoding="utf-8")
        done = subprocess.run([sys.executable, str(script)], cwd=str(REPO),
                              env=_repo_env(), capture_output=True, text=True,
                              timeout=120)
        assert done.returncode == 0, done.stderr
        assert "imported" in done.stdout

    def test_the_module_entry_point_refuses_with_the_install_line(
            self, tmp_path):
        """``python -m core.server`` without the extra is a sentence on
        stderr and a non-zero status, never a traceback — the thing reading
        it is as likely to be another program as a person."""
        script = tmp_path / "run_it.py"
        script.write_text(
            "import sys\n"
            "sys.modules['starlette'] = None\n"
            "sys.modules['uvicorn'] = None\n"
            "from core.server.__main__ import main\n"
            f"sys.exit(main(['--runs', {str(tmp_path)!r}]))\n",
            encoding="utf-8")
        done = subprocess.run([sys.executable, str(script)], cwd=str(REPO),
                              env=_repo_env(), capture_output=True, text=True,
                              timeout=120)
        assert done.returncode != 0
        assert "pip install 'judais-lobi[server]'" in done.stderr
        assert "Traceback" not in done.stderr

    def test_the_entry_point_answers_help(self):
        done = subprocess.run(
            [sys.executable, "-m", "core.server", "--help"], cwd=str(REPO),
            env=_repo_env(), capture_output=True, text=True, timeout=120)
        assert done.returncode == 0
        assert "--max-streams" in done.stdout and "--heartbeat" in done.stdout
        assert "below" in done.stdout.lower()

    def test_a_store_that_is_switched_off_is_refused_at_the_door(self,
                                                                 capsys):
        """``JUDAIS_LOBI_RUNS=none`` says this deployment keeps no
        transcripts. A server whose whole purpose is to serve them says so,
        rather than answering every request with an empty list."""
        from core.server.__main__ import main

        with pytest.raises(ServerUnavailable):
            resolve_store("none")
        assert main(["--runs", "off"]) == 1
        assert "disable word" in capsys.readouterr().err

    def test_the_store_location_has_one_owner(self, tmp_path, monkeypatch):
        """``--runs`` goes through :func:`core.durable.open_run_store`, the
        same resolver the mission CLI writes through, so a deployment that
        has moved ``JUDAIS_LOBI_RUNS`` has thereby moved this."""
        monkeypatch.setenv("JUDAIS_LOBI_RUNS", str(tmp_path / "from-env"))
        assert resolve_store().root == tmp_path / "from-env"
        assert resolve_store(str(tmp_path / "asked")).root == \
            tmp_path / "asked"


# ── what this server deliberately does not do ────────────────────────────────


class TestThereIsNoControlEndpoint:
    """Read-only, and the reason is written down rather than left to be
    rediscovered by whoever tries to add one."""

    def test_posting_to_a_run_is_not_a_route(self, store, finished):
        client, _ = client_for(store)
        assert client.post(f"/runs/{finished}/control",
                           json={"control": "cancel"}).status_code == 404
        assert client.post("/runs", json={}).status_code == 405

    def test_the_reason_is_stated_and_not_left_to_be_rediscovered(self):
        assert "fd:N" in WHY_NO_CONTROL_ENDPOINT
        assert "end-of-file" in WHY_NO_CONTROL_ENDPOINT
        assert "read-only" in WHY_NO_CONTROL_ENDPOINT.lower()

    def test_the_control_reader_really_does_stop_at_end_of_file(self):
        """The half of the reason that is a fact about another module rather
        than an opinion about this one: a second writer appending to a
        regular-file control spec writes to a thread that has already
        returned."""
        source = (REPO / "core" / "runtime" / "control.py").read_text()
        assert "return                          # the writer is gone" in source
