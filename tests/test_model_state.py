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

    def test_the_contract_and_the_backends_declare_the_same_seven_words(self):
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
                frames = "".join(
                    "data: " + json.dumps({
                        "id": "cmpl-1", "model": "gpt-oss-20b",
                        "choices": [{"index": 0,
                                     "delta": {"content": piece}}]}) + "\n\n"
                    for piece in ("he", "llo"))
                payload = (frames + "data: [DONE]\n\n").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
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
