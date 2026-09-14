# tests/test_model_state.py — the eleventh event: why you are waiting

"""A real socket, a real stall, a real 503, and one record for each.

Two halves.

The **emitter** (:class:`core.runtime.run._ModelStates`, reached through
``Model.watching``) is where the rule that keeps every recorded stream
byte-identical lives: a healthy call emits nothing, a wait is announced
once, and the ``loaded`` that closes it is the only ``loaded`` a consumer
sees.  Those tests drive it with reports directly, because the rule is
about the words and not about who said them.

The **local backend** is where the words are decided, and that half is
driven against a stub OpenAI-compatible server over a real socket — the
same choice ``tests/test_local_backend.py`` made and for the same reason.
The two situations a deployment spent two weeks unable to tell apart are
here as two servers: one that answers **503 while it loads weights** and
then serves, and one that **accepts the request and says nothing**.  A
mock would have proved that this file's idea of those two is
self-consistent, which is not the claim.

The stub is this module's own rather than
``tests/test_local_backend.py``'s: that one serves a healthy endpoint and
is shared by forty tests, and what is needed here is an endpoint that
behaves badly on purpose, per request, in three different ways.
"""

import asyncio
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from core.runtime import contract as c
from core.runtime.backends import policy, state
from core.runtime.backends.local_backend import LocalBackend
from core.runtime.run import Model, Observer


# ── driving the emitter ──────────────────────────────────────────────────────

class Recorded:
    """One run's observer, its model, and the records that reached a sink."""

    def __init__(self):
        self.seen = []
        self.observer = Observer(self.seen.append)
        self.model = Model(ask=lambda messages: "")

    def call(self, index=0):
        """A model call, watched exactly as ``Run._model_reply`` watches."""
        return self.model.watching(self.observer, index=index)

    @property
    def states(self):
        return [r["state"] for r in self.seen]


def faults(records):
    """Every contract violation in *records*, as sentences."""
    return [problem for record in records for problem in c.conforms(record)]


class TestAHealthyCallSaysNothing:
    """The rule the whole corpus rests on.

    Four recorded runs and nineteen recorded eval streams are committed in
    this repository, and a new record type that appeared on every model
    call would have changed every one of them.  It does not, because this
    event does not narrate a call — it explains a wait — and a call that
    did not make anybody wait has nothing to explain.  See
    ``tests/test_run_corpus.py``, which is the byte-for-byte proof; this
    is the reason.
    """

    def test_asking_then_loaded_emits_nothing_at_all(self):
        run = Recorded()
        with run.call():
            state.report(state.ASKING, provider="local", model="m")
            state.report(state.LOADED, provider="local", model="m")
        assert run.seen == []

    def test_a_call_nobody_reports_about_does_not_read_the_clock(
            self, monkeypatch):
        """Costs nothing, and "nothing" is measured rather than claimed.

        `tests/test_mission.py::TestTheWallClock` counts `time.monotonic`
        ticks to assert what a run's `elapsed_s` is, and it is right to:
        a clock read is a fact about the harness's own cost. A watch that
        took one per call would charge every mission for a record it was
        never going to emit — and would have broken that test, which is
        how this was found.
        """
        import core.runtime.run as run_module

        reads = []
        real = time.monotonic
        monkeypatch.setattr(run_module.time, "monotonic",
                            lambda: (reads.append(1), real())[1])
        run = Recorded()
        with run.call():
            pass
        assert reads == []

    def test_a_scripted_model_that_just_answers_emits_nothing(self):
        """The shape of every fixture in the corpus: no backend, no
        reports, and therefore no records."""
        run = Recorded()
        with run.call():
            pass
        assert run.seen == []

    def test_loaded_on_its_own_is_not_a_record(self):
        """A backend that only ever reports success is a backend a
        consumer never hears from."""
        run = Recorded()
        with run.call():
            state.report(state.LOADED, provider="local", model="m")
        assert run.seen == []

    def test_asking_is_never_on_the_wire_even_after_a_wait(self):
        run = Recorded()
        with run.call():
            state.report(state.COLD, provider="local", model="m")
            state.report(state.ASKING, provider="local", model="m")
            state.report(state.LOADED, provider="local", model="m")
        assert run.states == [state.COLD, state.LOADED]


class TestAWholeMissionAgainstAHealthyBackendIsUnchanged:
    """The corpus claim, made where the corpus cannot make it.

    ``tests/test_run_corpus.py`` replays four recorded runs and nineteen
    recorded streams and holds them byte-identical — but it replays them
    through a ``ReplayModel`` and a scripted client, which never touch a
    backend and so could never have reported a state.  The claim that
    matters is the stronger one: a mission against a backend that DOES
    report, and whose endpoint is behaving, produces the same records it
    produced before this event existed.  So here is one.
    """

    def _mission(self, reply, *, words=(state.ASKING, state.LOADED)):
        from core.runtime.mission import MissionRunner
        from tests.test_contract import _Bus

        def chat(messages):
            for word in words:
                state.report(word, provider="local", model="m")
            return reply

        seen = []
        MissionRunner(chat, _Bus(), ["catalog_search_assets"],
                      observer=seen.append, store_tool="").run("what do we hold")
        return seen

    def test_the_stream_is_the_one_a_consumer_always_read(self):
        seen = self._mission(json.dumps({"answer": "three assets"}))
        assert [r["event"] for r in seen] == [
            "mission_started", "step_started", "answer", "mission_finished"]

    def test_and_not_one_model_state_record_is_on_it(self):
        seen = self._mission(json.dumps({"answer": "done"}))
        assert not [r for r in seen if r["event"] == c.MODEL_STATE]
        assert faults(seen) == []

    def test_a_mission_whose_endpoint_stalled_does_carry_them(self):
        """Which is what makes the two tests above a claim rather than a
        silence: the loop's own call IS watched, so a wait on the same
        path reaches the same stream, in the step it happened in."""
        seen = self._mission(
            json.dumps({"answer": "done"}),
            words=(state.ASKING, state.QUEUED, state.LOADED))
        states = [r for r in seen if r["event"] == c.MODEL_STATE]
        assert [r["state"] for r in states] == [state.QUEUED, state.LOADED]
        assert [r["index"] for r in states] == [0, 0]
        assert faults(seen) == []


class TestAWaitIsAnnouncedOnceAndClosedOnce:
    def test_the_five_words_reach_the_wire(self):
        run = Recorded()
        for word in sorted(state.WAITING):
            with run.call():
                state.report(word, provider="local", model="m")
        assert run.states == sorted(state.WAITING)

    def test_loaded_after_a_wait_is_the_recovery_and_is_emitted(self):
        run = Recorded()
        with run.call():
            state.report(state.LOADING, provider="local", model="m")
            state.report(state.LOADED, provider="local", model="m")
        assert run.states == [state.LOADING, state.LOADED]

    def test_the_recovery_is_emitted_once_and_not_again(self):
        """Two calls, one wait: the second call was fine and says so by
        saying nothing."""
        run = Recorded()
        with run.call(index=0):
            state.report(state.QUEUED, provider="local", model="m")
            state.report(state.LOADED, provider="local", model="m")
        with run.call(index=1):
            state.report(state.LOADED, provider="local", model="m")
        assert run.states == [state.QUEUED, state.LOADED]

    def test_a_wait_that_returns_on_a_later_step_is_told_again(self):
        run = Recorded()
        with run.call(index=0):
            state.report(state.COLD, provider="local", model="m")
            state.report(state.LOADED, provider="local", model="m")
        with run.call(index=1):
            state.report(state.COLD, provider="local", model="m")
        assert run.states == [state.COLD, state.LOADED, state.COLD]


class TestTheSameWordTwiceIsOneRecord:
    """Three refused connects inside one retry budget are one fact.

    De-duplication is the run's and not the backend's, which is what lets
    ``LocalBackend._post`` report every refused attempt as it happens —
    seventeen seconds of retries is seventeen seconds somebody is staring
    at a pane — without putting four identical records on the stream.
    """

    def test_a_repeated_state_is_emitted_once(self):
        run = Recorded()
        with run.call():
            for _ in range(3):
                state.report(state.ABSENT, provider="local", model="m",
                             detail="ConnectionError: refused")
        assert run.states == [state.ABSENT]

    def test_it_stays_de_duplicated_across_calls(self):
        run = Recorded()
        for index in range(3):
            with run.call(index=index):
                state.report(state.ABSENT, provider="local", model="m")
        assert run.states == [state.ABSENT]

    def test_a_changed_retry_after_is_news_about_the_same_state(self):
        run = Recorded()
        with run.call():
            state.report(state.QUEUED, provider="p", model="m",
                         retry_after_s=10.0)
            state.report(state.QUEUED, provider="p", model="m",
                         retry_after_s=10.0)
            state.report(state.QUEUED, provider="p", model="m",
                         retry_after_s=60.0)
        assert [r.get("retry_after_s") for r in run.seen] == [10.0, 60.0]

    def test_a_different_state_is_always_news(self):
        run = Recorded()
        with run.call():
            state.report(state.LOADING, provider="p", model="m")
            state.report(state.FAILED, provider="p", model="m")
            state.report(state.LOADING, provider="p", model="m")
        assert run.states == [state.LOADING, state.FAILED, state.LOADING]


class TestWhatTheRecordCarries:
    def test_every_record_conforms(self):
        run = Recorded()
        with run.call(index=4):
            state.report(state.LOADING, provider="local", model="gpt-oss-20b",
                         detail="503: loading weights", retry_after_s=5.0)
            state.report(state.LOADED, provider="local", model="gpt-oss-20b")
        assert faults(run.seen) == []
        assert len(run.seen) == 2

    def test_the_required_three_are_the_backend_s_own_names(self):
        run = Recorded()
        with run.call():
            state.report(state.COLD, provider="local", model="gpt-oss-20b")
        record = run.seen[0]
        assert (record["state"], record["provider"], record["model"]) == (
            state.COLD, "local", "gpt-oss-20b")

    def test_the_step_it_happened_in_rides_the_record(self):
        run = Recorded()
        with run.call(index=7):
            state.report(state.QUEUED, provider="local", model="m")
        assert run.seen[0]["index"] == 7

    def test_a_call_with_no_step_carries_no_index(self):
        """OPTIONAL because a report is a fact about a call, and not every
        call this harness makes belongs to a numbered step."""
        run = Recorded()
        with run.call(index=None):
            state.report(state.QUEUED, provider="local", model="m")
        assert "index" not in run.seen[0]
        assert c.conforms(run.seen[0]) == []

    def test_detail_is_absent_when_nobody_said_anything(self):
        run = Recorded()
        with run.call():
            state.report(state.COLD, provider="local", model="m")
        assert "detail" not in run.seen[0]

    def test_retry_after_is_absent_when_none_was_asked_for(self):
        run = Recorded()
        with run.call():
            state.report(state.LOADING, provider="local", model="m",
                         detail="503")
        assert "retry_after_s" not in run.seen[0]

    def test_since_s_is_how_long_the_run_had_been_waiting(self):
        run = Recorded()
        with run.call():
            state.report(state.ASKING, provider="local", model="m")
            time.sleep(0.05)
            state.report(state.QUEUED, provider="local", model="m")
        assert run.seen[0]["since_s"] >= 0.05

    def test_the_clock_restarts_when_the_request_actually_goes_out(self):
        """A backend may say something before it asks — a probe that found
        the endpoint cold, say — and the wait for the REQUEST must not be
        reported as having started back there.  That is the whole job of
        `asking`, which is otherwise a word this stream never carries.
        """
        run = Recorded()
        with run.call():
            state.report(state.COLD, provider="local", model="m")
            time.sleep(0.06)
            state.report(state.ASKING, provider="local", model="m")
            state.report(state.FAILED, provider="local", model="m")
        assert run.seen[1]["since_s"] < 0.06

    def test_since_s_measures_from_the_call_and_not_from_the_run(self):
        """A second call that stalls immediately says so; it does not
        report the first call's seconds."""
        run = Recorded()
        with run.call(index=0):
            state.report(state.ASKING, provider="local", model="m")
            time.sleep(0.05)
            state.report(state.FAILED, provider="local", model="m")
        with run.call(index=1):
            state.report(state.ASKING, provider="local", model="m")
            state.report(state.COLD, provider="local", model="m")
        assert run.seen[1]["since_s"] < run.seen[0]["since_s"]

    def test_the_detail_goes_through_the_redactor_like_every_other_prose(self):
        """`Observer.emit` is the choke point and this record is not an
        exception to it: a server that echoed a bearer token back in its
        error body must not put it on the stream."""
        run = Recorded()
        with run.call():
            state.report(state.FAILED, provider="local", model="m",
                         detail="401 from the server: Bearer sk-livetoken")
        assert "sk-livetoken" not in json.dumps(run.seen[0])


class TestNobodyListeningCostsNothing:
    def test_a_report_outside_a_watch_goes_nowhere(self):
        """A chat session, a capability probe and a library caller with no
        observer all report into nothing, which is why a backend never has
        to ask whether it is inside a mission."""
        state.report(state.ABSENT, provider="local", model="m")

    def test_the_sink_is_taken_down_after_the_call(self):
        run = Recorded()
        with run.call():
            state.report(state.COLD, provider="local", model="m")
        state.report(state.FAILED, provider="local", model="m")
        assert run.states == [state.COLD]

    def test_the_sink_is_taken_down_even_when_the_call_raised(self):
        run = Recorded()
        with pytest.raises(RuntimeError):
            with run.call():
                raise RuntimeError("the endpoint went away")
        state.report(state.ABSENT, provider="local", model="m")
        assert run.seen == []

    def test_a_word_outside_the_vocabulary_raises_here_and_not_on_the_wire(self):
        run = Recorded()
        with run.call():
            with pytest.raises(ValueError, match="not one of the model states"):
                state.report("warming-up", provider="local", model="m")

    def test_a_sink_that_throws_does_not_end_the_call(self):
        """A mission must not fail because somebody was watching it."""
        def explode(record):
            raise RuntimeError("the browser closed")

        model = Model(ask=lambda messages: "")
        with model.watching(Observer(explode), index=0):
            state.report(state.ABSENT, provider="local", model="m")

    def test_the_contract_and_the_backends_declare_the_same_eight_words(self):
        assert c.MODEL_STATES == state.STATES


class TestReportsCrossThreads:
    def test_a_report_from_the_call_s_own_worker_thread_arrives(self):
        """The model call itself runs on one — ``Run._model_reply`` awaits
        :func:`asyncio.to_thread`, which copies the context — and the sink
        is installed on the loop's side of that.  If it were a plain
        global this would still pass; if it were a plain local it would
        not compile.  It is a ``ContextVar``, and this is the reason."""
        run = Recorded()

        async def call():
            with run.call():
                await asyncio.to_thread(
                    state.report, state.LOADING, provider="local", model="m")

        asyncio.run(call())
        assert run.states == [state.LOADING]

    def test_a_thread_the_call_did_not_start_reports_into_nothing(self):
        """The other half of the same fact, and the reason
        :func:`state.first_byte_within` copies the context by hand: a bare
        thread inherits none, so a timer that reported through a bare
        ``threading.Timer`` would report into silence."""
        run = Recorded()
        with run.call():
            worker = threading.Thread(
                target=lambda: state.report(state.LOADING, provider="local",
                                            model="m"))
            worker.start()
            worker.join(timeout=5)
        assert run.seen == []

    def test_the_first_byte_alarm_fires_in_the_caller_s_context(self):
        """A ``threading.Timer`` inherits no context of its own — the
        report would go nowhere without the copy
        :func:`state.first_byte_within` makes."""
        run = Recorded()
        with run.call():
            with state.first_byte_within(
                    0.01, lambda: state.report(state.QUEUED, provider="local",
                                               model="m")):
                time.sleep(0.2)
        assert run.states == [state.QUEUED]

    def test_an_answer_that_arrives_in_time_disarms_the_alarm(self):
        run = Recorded()
        with run.call():
            with state.first_byte_within(
                    5.0, lambda: state.report(state.QUEUED, provider="local",
                                              model="m")) as watch:
                watch.arrived()
        assert run.seen == []

    def test_no_alarm_is_armed_when_nobody_is_listening(self):
        """A chat session must not spawn a thread per call to notice
        something nobody asked to be told."""
        with state.first_byte_within(0.01, lambda: None) as watch:
            assert watch.armed is False

    def test_the_long_call_alarm_is_the_same_one_under_another_name(self):
        """Two call sites that read as what they are, one owner of the
        construction — so there is one set of rules about when nothing is
        armed rather than two that drift."""
        with state.alarm_after(0.01, lambda: None) as watch:
            assert watch.armed is False

    def test_and_it_fires_in_the_caller_s_context_too(self):
        run = Recorded()
        with run.call(index=2):
            with state.alarm_after(
                    0.01, lambda: state.report(state.STREAMING,
                                               provider="local", model="m")):
                time.sleep(0.2)
        assert run.states == [state.STREAMING]
        assert run.seen[0]["index"] == 2

    def test_an_alarm_nobody_disarms_is_still_taken_down_on_the_way_out(self):
        """The long-call alarm is never disarmed by a frame — only by the
        context manager — so a call that ends before it fires must not
        leave a timer thread behind."""
        run = Recorded()
        with run.call():
            with state.alarm_after(30.0, lambda: None) as watch:
                assert watch.armed is True
        assert watch.armed is False

    def test_and_taking_it_down_is_terminal_so_a_re_arm_cannot_undo_it(self):
        """What makes asking again safe.

        The re-arm runs on the timer thread and the context manager's
        ``finally`` runs on the call's, so the two race at the end of
        every long call. If the re-arm could win, a timer would outlive
        the call it was watching and report a model *still answering*
        after the run that made the call had finished — which is the
        failure mode the closing word exists to prevent, reintroduced by
        the machinery meant to help.
        """
        run = Recorded()
        with run.call():
            with state.alarm_after(30.0, lambda: True) as watch:
                pass
        watch.again()
        assert watch.armed is False


# ── the stub server that misbehaves on purpose ───────────────────────────────

class Endpoint:
    """What the stub serves, and how badly.

    Every knob is a situation somebody has actually met: a vLLM answering
    503 while it loads weights, a server behind a queue that accepts and
    says nothing, a ``/models`` that lists something other than what this
    run asked for, and a 429 with a ``Retry-After``.
    """

    def __init__(self):
        #: The ids ``GET /models`` lists.
        self.models = ["gpt-oss-20b"]
        #: The status ``GET /models`` answers with.
        self.models_status = 200
        #: Statuses to answer POSTs with, one per call, then 200 forever.
        #: ``[503]`` is a server that loads and then serves.
        self.statuses = []
        #: Headers to add to a non-2xx POST reply.
        self.headers = {}
        #: Seconds to hold a POST before answering it.
        self.stall_s = 0.0
        #: Seconds to hold BETWEEN the frames of a streamed answer — the
        #: server that is answering, and answering, and answering.
        #: Deliberately a different knob from ``stall_s``: the whole point
        #: of the eighth word is that a server which has not started and
        #: one which will not stop are different situations that looked
        #: identical from outside.
        self.trickle_s = 0.0
        #: How many content frames a streamed answer is made of, or
        #: ``None`` for the two that spell ``hello``.
        self.frames = None
        #: Stop writing after this many frames and drop the connection,
        #: with a ``Content-Length`` already promising more — the server
        #: that was answering and then was not.  ``None`` serves the whole
        #: stream.
        self.die_after = None
        #: How many completions have been asked for.
        self.posts = 0


def _handler(endpoint):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass

        def _send(self, status, payload, headers=()):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            for name, value in headers:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if endpoint.models_status != 200:
                self._send(endpoint.models_status, b'{"error":"boom"}')
                return
            self._send(200, json.dumps({
                "object": "list",
                "data": [{"id": name, "max_model_len": 4096}
                         for name in endpoint.models],
            }).encode())

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            endpoint.posts += 1
            if endpoint.stall_s:
                time.sleep(endpoint.stall_s)
            status = (endpoint.statuses.pop(0) if endpoint.statuses else 200)
            if status != 200:
                self._send(status, json.dumps(
                    {"message": "the model is still loading"}).encode(),
                    headers=tuple(endpoint.headers.items()))
                return
            if body.get("stream"):
                pieces = (["he", "llo"] if endpoint.frames is None
                          else [f"p{i}" for i in range(endpoint.frames)])
                frames = [
                    "data: " + json.dumps({
                        "id": "cmpl-1", "model": "gpt-oss-20b",
                        "choices": [{"index": 0,
                                     "delta": {"content": piece}}]}) + "\n\n"
                    for piece in pieces]
                frames.append("data: [DONE]\n\n")
                if endpoint.trickle_s:
                    # Each frame padded past the client's 512-byte read
                    # window with an SSE COMMENT, which the parser skips
                    # (`: ` is not `data:`) and which therefore changes
                    # nothing about the reply. Without it `iter_lines`
                    # blocks for a full buffer and a stream written over
                    # half a second arrives all at once — a test of the
                    # client's buffering rather than of a slow server.
                    frames = [f + ": " + "x" * 600 + "\n\n" for f in frames]
                payload = "".join(frames).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if not endpoint.trickle_s:
                    self.wfile.write(payload)
                    return
                # Written frame by frame with a pause between, because the
                # situation under test is a stream that keeps arriving and
                # a `Content-Length` written up front says nothing about
                # when the bytes come.
                for i, frame in enumerate(frames):
                    if (endpoint.die_after is not None
                            and i >= endpoint.die_after):
                        # The header promised more than this. Returning
                        # closes the socket, and the client raises on the
                        # short read — a stream that stopped mid-answer,
                        # which is not a status code and not a refused
                        # connect and so reaches neither of the two
                        # places this backend handles failures.
                        self.close_connection = True
                        return
                    self.wfile.write(frame.encode())
                    self.wfile.flush()
                    time.sleep(endpoint.trickle_s)
                return
            self._send(200, json.dumps({
                "id": "cmpl-1", "model": "gpt-oss-20b",
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant",
                                         "content": "hello"}}],
            }).encode())

    return Handler


@pytest.fixture
def endpoint():
    served = Endpoint()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(served))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever,
                              kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    served.base = f"http://{host}:{port}/v1"
    try:
        yield served
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def backend_for(endpoint, **kwargs):
    kwargs.setdefault("model", "gpt-oss-20b")
    kwargs.setdefault("first_byte_queued_s", 0.05)
    # Far enough away that the tests about the OTHER alarm never meet this
    # one; the tests about this one pass their own.
    kwargs.setdefault("streaming_long_s", 30.0)
    return LocalBackend(endpoint=endpoint.base, **kwargs)


def ask(run, backend, *, stream=False, index=0):
    """One watched model call, returning the reply or the exception."""
    with run.call(index=index):
        got = backend.chat("gpt-oss-20b", [{"role": "user", "content": "hi"}],
                           stream=stream)
        return "".join(
            chunk.choices[0].delta.content or ""
            for chunk in got) if stream else got


class TestTheServerThatIsLoading:
    """(a) 503 while the weights load, then it serves.

    ``loading`` is the server's OWN word here — its status and its body —
    and never a conclusion this harness drew from a silence.  That is the
    whole difference from ``queued`` below.
    """

    def test_a_503_is_loading_and_carries_what_the_server_said(self, endpoint):
        endpoint.statuses = [503]
        run = Recorded()
        with pytest.raises(Exception):
            ask(run, backend_for(endpoint))
        assert run.states == [state.LOADING]
        assert "still loading" in run.seen[0]["detail"]

    def test_the_retry_after_the_server_asked_for_travels(self, endpoint):
        endpoint.statuses = [503]
        endpoint.headers = {"Retry-After": "7"}
        run = Recorded()
        with pytest.raises(Exception):
            ask(run, backend_for(endpoint))
        assert run.seen[0]["retry_after_s"] == 7.0

    def test_then_it_loads_and_the_recovery_is_the_second_record(self, endpoint):
        endpoint.statuses = [503]
        run = Recorded()
        backend = backend_for(endpoint)
        with pytest.raises(Exception):
            ask(run, backend, index=0)
        assert ask(run, backend, index=1) == "hello"
        assert run.states == [state.LOADING, state.LOADED]
        assert faults(run.seen) == []

    def test_the_loaded_record_names_the_model_the_server_reported(self, endpoint):
        endpoint.statuses = [503]
        run = Recorded()
        backend = backend_for(endpoint, model=None)
        with pytest.raises(Exception):
            ask(run, backend)
        ask(run, backend)
        assert run.seen[-1]["model"] == "gpt-oss-20b"


class TestTheServerThatAcceptedAndSaidNothing:
    """(b) the request is in, the endpoint has the model, nothing is
    coming back.

    The deployment's exact confusion, and the reason ``queued`` is asked
    for rather than guessed: the harness goes and reads ``GET /models``
    before it uses the word.
    """

    def test_a_late_first_byte_with_the_model_loaded_is_queued(self, endpoint):
        endpoint.stall_s = 0.4
        run = Recorded()
        assert ask(run, backend_for(endpoint)) == "hello"
        assert run.states == [state.QUEUED, state.LOADED]
        assert "queue" in run.seen[0]["detail"]

    def test_the_same_wait_with_the_model_not_listed_is_cold(self, endpoint):
        """Not queued: there is nothing on that endpoint to be queued
        behind."""
        endpoint.stall_s = 0.4
        endpoint.models = ["some-other-model"]
        run = Recorded()
        ask(run, backend_for(endpoint))
        assert run.states == [state.COLD, state.LOADED]
        assert "some-other-model" in run.seen[0]["detail"]

    def test_an_endpoint_that_lists_nothing_at_all_is_cold_too(self, endpoint):
        endpoint.stall_s = 0.4
        endpoint.models = []
        run = Recorded()
        ask(run, backend_for(endpoint))
        assert run.states == [state.COLD, state.LOADED]
        assert "no model" in run.seen[0]["detail"]

    def test_a_wait_over_an_endpoint_that_stopped_answering_is_absent(self, endpoint):
        endpoint.stall_s = 0.4
        endpoint.models_status = 500
        run = Recorded()
        ask(run, backend_for(endpoint))
        assert run.states == [state.ABSENT, state.LOADED]

    def test_a_call_that_answers_in_time_says_nothing(self, endpoint):
        run = Recorded()
        assert ask(run, backend_for(endpoint, first_byte_queued_s=30)) == "hello"
        assert run.seen == []

    def test_since_s_says_how_long_the_wait_had_lasted(self, endpoint):
        endpoint.stall_s = 0.4
        run = Recorded()
        ask(run, backend_for(endpoint))
        assert run.seen[0]["since_s"] >= 0.05
        assert run.seen[1]["since_s"] >= run.seen[0]["since_s"]

    def test_a_streamed_call_is_watched_until_its_first_frame(self, endpoint):
        endpoint.stall_s = 0.4
        run = Recorded()
        assert ask(run, backend_for(endpoint), stream=True) == "hello"
        assert run.states == [state.QUEUED, state.LOADED]


class TestTheServerThatWillNotStopAnswering:
    """(c) the first token arrived and the model is *still* going.

    The third situation, and the one no instrument here used to watch.
    ``first_byte_within`` stands down the moment a frame lands, so before
    the eighth word a call that trickled for two hundred seconds produced
    the same stream as a call that had not started: a ``step_started`` and
    then nothing. Five stalls of exactly that shape are what
    ``evidence/diagnosis-v1.4.0-regression-2026-09-14.md`` is made of.

    Driven against the stub's ``trickle_s`` — a real socket delivering
    real frames slowly — because the claim is about frames going past and
    a mock would only prove this file agrees with itself.
    """

    #: Six frames 100ms apart — six tenths of a second of a server that
    #: started answering straight away and is not finished.  The numbers
    #: are deliberately loose: the threshold below sits at 0.2s, so the
    #: first frame has ~0.18s of slack to land in and the stream has
    #: ~0.4s left to run when the word goes out.  Sub-second constants
    #: are fragile enough without being tight as well.
    TRICKLE_S = 0.1
    FRAMES = 6

    def _trickling(self, endpoint, frames=None, die_after=None):
        endpoint.trickle_s = self.TRICKLE_S
        endpoint.frames = self.FRAMES if frames is None else frames
        endpoint.die_after = die_after
        return endpoint

    def _long(self, endpoint, **kwargs):
        # Above the first frame's arrival and well below the whole
        # stream's, so the threshold is what decides and not a race.
        kwargs.setdefault("first_byte_queued_s", 30.0)
        kwargs.setdefault("streaming_long_s", 0.2)
        return backend_for(endpoint, **kwargs)

    def test_a_call_that_keeps_streaming_says_so(self, endpoint):
        run = Recorded()
        self._trickling(endpoint)
        ask(run, self._long(endpoint), stream=True)
        assert state.STREAMING in run.states

    def test_it_does_not_fire_before_the_threshold(self, endpoint):
        """The same trickle, with the threshold above it. A word that
        appeared either way would be a word about nothing."""
        run = Recorded()
        self._trickling(endpoint)
        ask(run, self._long(endpoint, streaming_long_s=30.0), stream=True)
        assert run.seen == []

    def test_a_short_call_under_the_same_threshold_says_nothing(self, endpoint):
        run = Recorded()
        ask(run, self._long(endpoint, streaming_long_s=5.0), stream=True)
        assert run.seen == []

    def test_it_is_said_once_and_not_once_a_minute(self, endpoint):
        """A state channel, not a metronome: the word says *this call is
        still going*, and saying it again says nothing the first one did
        not.  Ten frames is five thresholds' worth of stream."""
        run = Recorded()
        self._trickling(endpoint, frames=10)
        ask(run, self._long(endpoint), stream=True)
        assert run.states.count(state.STREAMING) == 1

    def test_the_wait_it_opens_is_closed_when_the_frames_stop(self, endpoint):
        run = Recorded()
        self._trickling(endpoint)
        ask(run, self._long(endpoint), stream=True)
        assert run.states == [state.STREAMING, state.LOADED]

    def test_the_detail_says_what_the_harness_watched_go_past(self, endpoint):
        """Not a guess about a server — a count of frames this backend
        saw. That is the difference between this word and `queued`, so
        the NUMBERS are asserted and not just the nouns: prose naming
        frames and characters without them would read the same and mean
        nothing."""
        run = Recorded()
        self._trickling(endpoint)
        ask(run, self._long(endpoint), stream=True)
        detail = run.seen[0]["detail"]
        assert "still answering" in detail
        frames, chars = re.findall(r"(\d+) frames and (\d+) characters",
                                   detail)[0]
        assert 1 <= int(frames) <= self.FRAMES
        assert int(chars) >= 1

    def test_the_closing_record_says_how_much_arrived_in_the_end(self, endpoint):
        run = Recorded()
        self._trickling(endpoint)
        ask(run, self._long(endpoint), stream=True)
        assert f"{self.FRAMES} frames" in run.seen[1]["detail"]

    def test_since_s_is_measured_from_the_request_going_out(self, endpoint):
        run = Recorded()
        self._trickling(endpoint)
        ask(run, self._long(endpoint), stream=True)
        assert run.seen[0]["since_s"] >= 0.1
        assert run.seen[1]["since_s"] >= run.seen[0]["since_s"]

    def test_every_record_conforms(self, endpoint):
        run = Recorded()
        self._trickling(endpoint)
        ask(run, self._long(endpoint), stream=True)
        assert faults(run.seen) == []

    def test_a_silence_is_still_the_first_bytes_business(self, endpoint):
        """Both alarms armed, nothing streaming: the word is `queued`,
        because `/models` was asked. This backend must not hold two
        opinions about one silence — and the long-call alarm passing
        through three of its windows in that silence must not add one."""
        endpoint.stall_s = 0.5
        run = Recorded()
        ask(run, self._long(endpoint, first_byte_queued_s=0.05,
                            streaming_long_s=0.1), stream=True)
        assert state.STREAMING not in run.states
        assert run.states == [state.QUEUED, state.LOADED]

    def test_a_first_frame_after_the_threshold_still_gets_the_word(
            self, endpoint):
        """THE regression this class exists for a second time.

        A one-shot that stood down on *no frame yet* would mean the
        server that is slow to start AND slow to finish — the worse
        version of the same afternoon — is never reported at all:
        `loaded` when the token finally lands, and then the whole long
        answer in silence, with a wait opened and closed to make the hole
        look accounted for. The alarm asks again instead, so the word
        arrives in the window after the frames do.
        """
        endpoint.stall_s = 0.3          # three thresholds of nothing
        self._trickling(endpoint)       # then six tenths of answering
        run = Recorded()
        ask(run, self._long(endpoint, streaming_long_s=0.1), stream=True)
        assert state.STREAMING in run.states
        assert run.states[-1] == state.LOADED

    def test_the_detail_states_no_elapsed_time_for_since_s_to_contradict(
            self, endpoint):
        """The clock has ONE owner, and re-arming is what proves it must.

        A sentence naming the threshold is right on the first window and
        wrong on every later one — and every record on the path the
        re-arm newly enables comes from a later one. Here the call is
        silent for three windows before it answers, so `since_s` is
        several times the threshold; prose beside it saying the request
        went out one threshold ago would be two fields of one record
        disagreeing about one fact.
        """
        endpoint.stall_s = 0.3          # three windows before a frame
        self._trickling(endpoint)
        run = Recorded()
        ask(run, self._long(endpoint, streaming_long_s=0.1), stream=True)
        record = run.seen[0]
        assert record["state"] == state.STREAMING
        assert "ago" not in record["detail"]
        assert "0.1" not in record["detail"]
        # And the figure that would have been wrong, on the field that is
        # entitled to carry it.
        assert record["since_s"] > 0.2

    def test_and_a_call_that_never_starts_is_never_called_streaming(
            self, endpoint):
        """Asking again is not inventing: many windows may pass, and
        every one of them says nothing until a frame has been seen."""
        endpoint.stall_s = 0.5
        run = Recorded()
        ask(run, self._long(endpoint, streaming_long_s=0.05), stream=True)
        assert state.STREAMING not in run.states

    def test_a_reply_that_never_streamed_is_not_called_streaming(self, endpoint):
        """A non-streamed call has no frames to count, so there is nothing
        this word could honestly be said about — the wait before a whole
        JSON body arrives is the first-byte instrument's."""
        endpoint.stall_s = 0.3
        run = Recorded()
        ask(run, self._long(endpoint))
        assert state.STREAMING not in run.states

    def test_an_unwatched_call_is_told_nothing_and_still_answers(self, endpoint):
        """A chat session, a probe, a library caller with no observer:
        the alarm is not armed at all — see
        :func:`core.runtime.backends.state.alarm_after` — and the reply is
        the reply."""
        self._trickling(endpoint)
        got = self._long(endpoint).chat(
            "gpt-oss-20b", [{"role": "user", "content": "hi"}], stream=True)
        assert "".join(c.choices[0].delta.content or "" for c in got) == (
            "".join(f"p{i}" for i in range(self.FRAMES)))


class TestAStreamThatDiesStillClosesItsWait:
    """A wait this backend opens is a wait this backend closes.

    The hole: a socket that drops mid-answer reaches neither `_post`'s
    retry (the connect succeeded) nor `_raise_for_status` (the status was
    200), so before this nothing said anything and the run's
    de-duplicator kept the wait open — and then spent the NEXT, healthy
    call's `loaded` closing it, which is a `loaded` on a call where
    nothing went wrong and which `CONTRACT.md` forbids in as many words.
    Worse when the failure ends the run: the last word on the stream is a
    model still answering, after `mission_finished`.
    """

    TRICKLE_S = 0.1
    FRAMES = 10

    def _dying(self, endpoint, die_after):
        endpoint.trickle_s = self.TRICKLE_S
        endpoint.frames = self.FRAMES
        endpoint.die_after = die_after
        return endpoint

    def _long(self, endpoint, **kwargs):
        kwargs.setdefault("first_byte_queued_s", 30.0)
        kwargs.setdefault("streaming_long_s", 0.2)
        return backend_for(endpoint, **kwargs)

    def test_the_wait_is_closed_when_the_stream_dies(self, endpoint):
        self._dying(endpoint, die_after=6)
        run = Recorded()
        with pytest.raises(Exception):
            ask(run, self._long(endpoint), stream=True)
        assert run.states == [state.STREAMING, state.FAILED]

    def test_the_word_is_the_one_the_error_policy_names(self, endpoint):
        """Not written here. The `timeout` row's reasoning IS this case:
        *the request IS in flight — the server may be decoding it right
        now*."""
        self._dying(endpoint, die_after=6)
        run = Recorded()
        with pytest.raises(Exception):
            ask(run, self._long(endpoint), stream=True)
        assert run.states[-1] == policy.ERROR_POLICY["timeout"].state

    def test_the_detail_says_how_far_it_got_and_what_stopped_it(self, endpoint):
        self._dying(endpoint, die_after=6)
        run = Recorded()
        with pytest.raises(Exception):
            ask(run, self._long(endpoint), stream=True)
        assert "the stream stopped after" in run.seen[-1]["detail"]

    def test_the_next_healthy_call_pays_for_nothing_of_this_ones(self, endpoint):
        """The defect stated as an assertion, and the assertion is not
        quite *the next call emits nothing*.

        What `CONTRACT.md` forbids is a `loaded` with nothing outstanding
        for it to close — the boring half of a healthy call, on the wire.
        Unfixed, that is exactly what the next call produced: the
        streaming wait was still open, so an ordinary call nobody waited
        on emitted a recovery.

        Fixed, the dead stream leaves a `failed` ON THE WIRE, and the
        next `loaded` is that word's documented close — the same
        sequence a 500 has produced since this event existed, and the
        thing a pane needs in order to stop showing red. So the claim is
        that the next call emits **at most its close, and only because a
        failure was reported**: one record, `loaded`, against a `failed`
        a consumer was actually shown.
        """
        self._dying(endpoint, die_after=6)
        run = Recorded()
        backend = self._long(endpoint)
        with pytest.raises(Exception):
            ask(run, backend, stream=True)
        assert run.states == [state.STREAMING, state.FAILED]
        before = len(run.seen)
        endpoint.trickle_s = 0.0
        endpoint.frames = None
        endpoint.die_after = None
        assert ask(run, backend, stream=True, index=1) == "hello"
        after = run.seen[before:]
        assert [r["state"] for r in after] == [state.LOADED]

    def test_and_a_healthy_call_after_a_healthy_one_still_emits_nothing(
            self, endpoint):
        """The control. Nothing outstanding, nothing said — which is what
        makes the record above a close and not a leak."""
        endpoint.trickle_s = 0.0
        endpoint.frames = None
        run = Recorded()
        backend = self._long(endpoint)
        assert ask(run, backend, stream=True) == "hello"
        assert ask(run, backend, stream=True, index=1) == "hello"
        assert run.seen == []

    def test_a_stream_that_dies_before_the_word_opens_no_wait(self, endpoint):
        """Nothing was said, so there is nothing to close — and the
        exception on its way to the caller is the whole of what
        happened."""
        self._dying(endpoint, die_after=1)
        run = Recorded()
        with pytest.raises(Exception):
            ask(run, self._long(endpoint, streaming_long_s=30.0), stream=True)
        assert run.seen == []

    def test_a_consumer_that_walks_away_does_not_leave_one_open(self, endpoint):
        """The abandoned generator — a cancelled run, a driver that
        stopped reading. `GeneratorExit` is not an error, but the wait is
        just as open and the pane would show a model still answering
        after `mission_finished`."""
        self._dying(endpoint, die_after=None)
        run = Recorded()
        with run.call(index=0):
            frames = self._long(endpoint).chat(
                "gpt-oss-20b", [{"role": "user", "content": "hi"}],
                stream=True)
            for _ in frames:
                if state.STREAMING in run.states:
                    break
            frames.close()
        assert run.states == [state.STREAMING, state.FAILED]

    def test_every_record_conforms(self, endpoint):
        self._dying(endpoint, die_after=6)
        run = Recorded()
        with pytest.raises(Exception):
            ask(run, self._long(endpoint), stream=True)
        assert faults(run.seen) == []


class TestTwoSlowChildrenAreTwoFacts:
    """`streaming` is the first word that is about ONE CALL.

    The other six are about the ENDPOINT, which a run shares with its
    children by identity, and one shared slot is right for them: three
    children saying `absent` about one dead socket is one fact told three
    times. Applying that slot to `streaming` loses a `--swarm` turn's
    second child twice over — its word dropped as a repeat, and then its
    close dropped because the first child's `loaded` had already cleared
    the flag.
    """

    def _report(self, run, word, index, **kwargs):
        with run.call(index=index):
            state.report(word, provider="local", model="m", **kwargs)

    def test_two_children_streaming_at_once_are_two_records(self):
        run = Recorded()
        self._report(run, state.STREAMING, 0)
        self._report(run, state.STREAMING, 1)
        assert run.states == [state.STREAMING, state.STREAMING]
        assert [r["index"] for r in run.seen] == [0, 1]

    def test_and_each_ones_close_is_its_own(self):
        run = Recorded()
        self._report(run, state.STREAMING, 0)
        self._report(run, state.STREAMING, 1)
        self._report(run, state.LOADED, 0)
        self._report(run, state.LOADED, 1)
        assert run.states == [state.STREAMING, state.STREAMING,
                              state.LOADED, state.LOADED]
        assert [r["index"] for r in run.seen] == [0, 1, 0, 1]

    def test_one_childs_close_does_not_close_the_other(self):
        """The half a single flag gets wrong even when the word survives:
        child 1 finishing must not take child 2's wait down with it."""
        run = Recorded()
        self._report(run, state.STREAMING, 0)
        self._report(run, state.STREAMING, 1)
        self._report(run, state.LOADED, 0)
        assert run.states[-1] == state.LOADED
        assert run.seen[-1]["index"] == 0
        self._report(run, state.LOADED, 1)
        assert run.seen[-1]["index"] == 1

    def test_a_failed_close_is_keyed_the_same_way(self):
        run = Recorded()
        self._report(run, state.STREAMING, 0)
        self._report(run, state.STREAMING, 1)
        self._report(run, state.FAILED, 1)
        assert [(r["state"], r["index"]) for r in run.seen] == [
            (state.STREAMING, 0), (state.STREAMING, 1), (state.FAILED, 1)]

    def test_the_same_call_saying_it_twice_is_still_one_record(self):
        run = Recorded()
        self._report(run, state.STREAMING, 0)
        self._report(run, state.STREAMING, 0)
        assert run.states == [state.STREAMING]

    def test_and_a_later_call_at_the_same_step_may_say_it_again(self):
        """A repair turn keeps its step number. Once the first call's
        wait is closed the step is free to open another."""
        run = Recorded()
        self._report(run, state.STREAMING, 0)
        self._report(run, state.LOADED, 0)
        self._report(run, state.STREAMING, 0)
        assert run.states == [state.STREAMING, state.LOADED, state.STREAMING]

    def test_the_endpoint_words_are_still_de_duplicated_across_children(self):
        """The other channel, untouched: one dead socket reported by two
        children is one record."""
        run = Recorded()
        self._report(run, state.ABSENT, 0)
        self._report(run, state.ABSENT, 1)
        assert run.states == [state.ABSENT]

    def test_and_a_healthy_call_beside_a_streaming_one_still_says_nothing(self):
        run = Recorded()
        self._report(run, state.STREAMING, 0)
        self._report(run, state.LOADED, 1)
        assert run.states == [state.STREAMING]

    def test_a_loaded_closing_both_of_one_calls_waits_leaves_none_behind(self):
        """One call may carry both — `queued` at twenty seconds, then
        `streaming` at sixty. Its `loaded` closes the pair; otherwise the
        endpoint half stays open and the next healthy call pays for it
        with a recovery nobody was waiting for."""
        run = Recorded()
        self._report(run, state.QUEUED, 0)
        self._report(run, state.STREAMING, 0)
        self._report(run, state.LOADED, 0)
        before = len(run.seen)
        self._report(run, state.LOADED, 1)
        assert run.seen[before:] == []

    def test_every_record_conforms(self):
        run = Recorded()
        self._report(run, state.STREAMING, 0)
        self._report(run, state.STREAMING, 1)
        self._report(run, state.LOADED, 0)
        self._report(run, state.FAILED, 1)
        assert faults(run.seen) == []


class TestTheEndpointThatIsNotThere:
    def test_a_refused_connect_is_absent(self):
        run = Recorded()
        backend = LocalBackend(endpoint="http://127.0.0.1:1/v1",
                               model="gpt-oss-20b")
        backend.CONNECT_RETRIES = ()
        with pytest.raises(Exception):
            ask(run, backend)
        assert run.states == [state.ABSENT]
        assert "Error" in run.seen[0]["detail"]

    def test_every_refused_retry_reports_and_the_run_says_it_once(self):
        """Reported as they happen — seventeen seconds of retries is
        seventeen seconds of somebody watching nothing — and one record,
        because it is one fact."""
        run = Recorded()
        backend = LocalBackend(endpoint="http://127.0.0.1:1/v1",
                               model="gpt-oss-20b")
        backend.CONNECT_RETRIES = (0.0, 0.0)
        with pytest.raises(Exception):
            ask(run, backend)
        assert run.states == [state.ABSENT]

    def test_the_word_is_the_one_the_error_policy_names(self):
        assert policy.ERROR_POLICY["connect"].state == state.ABSENT


class TestWhatTheStatusCodeSays:
    def test_a_429_is_a_queue_and_not_a_broken_request(self, endpoint):
        endpoint.statuses = [429]
        endpoint.headers = {"Retry-After": "2"}
        run = Recorded()
        with pytest.raises(Exception):
            ask(run, backend_for(endpoint))
        assert run.states == [state.QUEUED]
        assert run.seen[0]["retry_after_s"] == 2.0

    def test_any_other_failure_is_the_policy_class_s_word(self, endpoint):
        endpoint.statuses = [400]
        run = Recorded()
        with pytest.raises(Exception):
            ask(run, backend_for(endpoint))
        assert run.states == [policy.ERROR_POLICY["4xx"].state]
        assert run.states == [state.FAILED]

    def test_a_500_is_failed_and_not_loading(self, endpoint):
        """Only 503 means loading. A server that is simply broken must not
        be rendered as one that is coming up."""
        endpoint.statuses = [500]
        run = Recorded()
        with pytest.raises(Exception):
            ask(run, backend_for(endpoint))
        assert run.states == [state.FAILED]

    def test_the_two_codes_read_more_precisely_than_their_class(self):
        assert policy.STATUS_STATES == {429: state.QUEUED, 503: state.LOADING}
        assert policy.state_for_status(200) == ""


class TestTheProbeSaysWhatItFound:
    def test_an_endpoint_that_lists_something_else_is_cold(self, endpoint):
        endpoint.models = ["another-model"]
        run = Recorded()
        backend = backend_for(endpoint)
        with run.call():
            backend.probe(refresh=True)
        assert run.states == [state.COLD]

    def test_an_endpoint_that_lists_the_model_says_nothing(self, endpoint):
        run = Recorded()
        backend = backend_for(endpoint)
        with run.call():
            backend.probe(refresh=True)
        assert run.seen == []

    def test_an_unreachable_endpoint_is_absent(self):
        run = Recorded()
        backend = LocalBackend(endpoint="http://127.0.0.1:1/v1", model="m")
        with run.call():
            backend.probe(refresh=True)
        assert run.states == [state.ABSENT]

    def test_the_list_is_kept_and_not_collapsed(self, endpoint):
        endpoint.models = ["a", "b"]
        backend = backend_for(endpoint, model="b")
        assert backend.probe().served == ("a", "b")
        assert backend.lists() is True

    def test_a_backend_that_named_no_model_takes_whatever_is_served(self, endpoint):
        assert backend_for(endpoint, model=None).lists() is True

    def test_and_is_cold_when_nothing_is_served_at_all(self, endpoint):
        endpoint.models = []
        assert backend_for(endpoint, model=None).lists() is False


class TestRetryAfterIsReadTheWayServersWriteIt:
    def test_seconds(self):
        assert state.retry_after_seconds({"Retry-After": "30"}) == 30.0

    def test_the_header_is_case_insensitive(self):
        assert state.retry_after_seconds({"retry-after": "5"}) == 5.0

    def test_an_http_date_is_read_against_the_server_s_own_clock(self):
        assert state.retry_after_seconds({
            "Retry-After": "Wed, 18 Aug 2026 00:01:00 GMT",
            "Date": "Wed, 18 Aug 2026 00:00:00 GMT"}) == 60.0

    def test_a_wait_in_the_past_is_over(self):
        assert state.retry_after_seconds({"Retry-After": "-5"}) == 0.0

    def test_nothing_said_is_nothing_read(self):
        assert state.retry_after_seconds({}) is None
        assert state.retry_after_seconds(None) is None
        assert state.retry_after_seconds({"Retry-After": "soon"}) is None


class TestTheConsoleSaysWhyItIsWaiting:
    """`_ProgressiveAnswer` prints the one line a person at a terminal
    needs when the stream carries `model_state` — and nothing when a call
    is healthy, because then there is no record to print."""

    def _printer(self):
        from rich.console import Console
        from io import StringIO
        from core.cli import _ProgressiveAnswer
        buf = StringIO()
        console = Console(file=buf, force_terminal=False, width=200)
        return _ProgressiveAnswer(console, "cyan", "Tai"), buf

    def test_a_queued_state_is_one_yellow_line(self):
        printer, buf = self._printer()
        printer({"event": "model_state", "state": "queued", "provider": "local",
                 "model": "m", "since_s": 21.5, "retry_after_s": 5.0,
                 "detail": "429"})
        out = buf.getvalue()
        assert "⏳ model: queued" in out
        assert "after 21.5s" in out and "429" in out and "asks for 5s" in out

    def test_loaded_closes_the_wait(self):
        printer, buf = self._printer()
        printer({"event": "model_state", "state": "loaded", "provider": "local",
                 "model": "m", "since_s": 3.0})
        assert "✅ model: loaded after 3s" in buf.getvalue()

    def test_a_healthy_stream_prints_nothing_of_the_kind(self):
        printer, buf = self._printer()
        printer({"event": "step_started", "index": 0})
        assert "model:" not in buf.getvalue()
