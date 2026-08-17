# tests/test_answer_stream.py — reading an answer that has not finished arriving

"""The decoders, split everywhere a stream can be split.

A backend hands over frames, not sentences: a fragment ends where the
server's buffer ended, which is as often in the middle of a `\\u00e9` as
between two words. Every case below is the same reply cut a different
way, and the property being asserted is always one of two — the pieces
concatenate to the answer, or nothing was emitted at all.
"""

import json

import pytest

from core.runtime.answer_stream import (
    BOUND_CHARS, JSON_ANSWER_KEY, NATIVE_ANSWER_KEY, AnswerStream, drain,
)

ANSWER_TOOL = "mission_answer"


class _Delta:
    """One frame, in the shape every backend in this tree yields.

    Written as a class rather than a `SimpleNamespace` chain so a test
    below can read `frame.choices[0].delta.content` and mean it — the
    attribute walk IS what `AnswerStream` does, and a fake that answered
    to `.get` instead would be testing a different reader.
    """

    def __init__(self, content=None, tool_calls=None):
        self.choices = [_Choice(content, tool_calls)]


class _Choice:
    def __init__(self, content, tool_calls):
        self.delta = _DeltaBody(content, tool_calls)


class _DeltaBody:
    def __init__(self, content, tool_calls):
        self.content = content
        self.tool_calls = tool_calls


def content_frames(*pieces):
    return [_Delta(content=piece) for piece in pieces]


def call_frames(*fragments):
    return [_Delta(tool_calls=fragment) for fragment in fragments]


def fragment(index=0, name=None, arguments=None, call_id=None):
    """One `delta.tool_calls` entry, carrying only what a server sends.

    The first frame of a streamed call carries the id and the name; every
    frame after it carries the index and a few more characters of the
    arguments, which is exactly why the decoder cannot decide what it is
    looking at from one frame.
    """
    function = {}
    if name is not None:
        function["name"] = name
    if arguments is not None:
        function["arguments"] = arguments
    entry = {"index": index, "function": function}
    if call_id is not None:
        entry["id"] = call_id
    return [entry]


def streamed(frames, *, native=False, bound=BOUND_CHARS):
    """`(the reply, the fragments emitted)` for one drained call."""
    seen = []
    reply = drain(iter(frames), seen.append, native=native,
                  answer_tool=ANSWER_TOOL, bound=bound)
    return reply, seen


def cut(text, size):
    """*text* in pieces of *size* characters — a stream split on a grid."""
    return [text[at:at + size] for at in range(0, len(text), size)]


# ── the json protocol ────────────────────────────────────────────────────────


ANSWER = "the cable was cut on 3 August, per asset.5f21"
REPLY = json.dumps({"answer": ANSWER})


class TestTheJsonDecoder:
    """The value of the top-level `answer` key, as the object decodes."""

    @pytest.mark.parametrize("size", [1, 2, 3, 7, 13, 64, 4096])
    def test_the_fragments_concatenate_to_the_answer_however_it_is_cut(
            self, size):
        reply, seen = streamed(content_frames(*cut(REPLY, size)), bound=8)
        assert "".join(seen) == ANSWER
        assert reply == REPLY

    def test_one_frame_carrying_the_whole_reply(self):
        _reply, seen = streamed(content_frames(REPLY), bound=1000)
        assert seen == [ANSWER]

    def test_a_tool_call_reply_emits_nothing(self):
        """The key never appears, so there is nothing to be provisional
        about — and a `{"tool": …}` turn has no answer to show."""
        reply = json.dumps({"tool": "catalog.search", "arguments": {"q": "x"}})
        got, seen = streamed(content_frames(*cut(reply, 3)))
        assert seen == []
        assert got == reply

    def test_an_answer_key_inside_the_arguments_emits_nothing(self):
        """Only a TOP-LEVEL key counts. A nested one is a tool's argument
        that happens to be spelled the same, and streaming it would show a
        pane an answer the mission is not giving."""
        reply = json.dumps({"tool": "search",
                            "arguments": {"answer": "not the answer",
                                          "deeper": {"answer": "nor this"}}})
        _got, seen = streamed(content_frames(*cut(reply, 5)))
        assert seen == []

    def test_a_key_that_only_looks_like_the_answer_is_not_one(self):
        reply = json.dumps({"answered": "no", "answer": "yes"})
        _got, seen = streamed(content_frames(*cut(reply, 4)), bound=100)
        assert "".join(seen) == "yes"

    def test_a_fence_and_a_preamble_are_scanned_past(self):
        """`_parse` strips a fence off the finished reply; the decoder has
        to get through one while it is still arriving."""
        reply = f"Sure!\n```json\n{REPLY}\n```"
        _got, seen = streamed(content_frames(*cut(reply, 6)), bound=1000)
        assert "".join(seen) == ANSWER

    def test_a_non_string_answer_emits_nothing(self):
        _got, seen = streamed(content_frames('{"answer": 42}'))
        assert seen == []

    def test_an_object_that_closed_without_the_key_stops_looking(self):
        _got, seen = streamed(content_frames('{"tool": "x"}', '{"answer": "late"}'))
        assert seen == []

    def test_prose_that_is_not_json_at_all_emits_nothing_and_does_not_raise(self):
        got, seen = streamed(content_frames("I cannot ", "do that."))
        assert seen == []
        assert got == "I cannot do that."


class TestTheEscapesAFragmentCanBeCutThrough:
    """Every escape JSON has, split at every character of itself."""

    ESCAPED = {
        "a newline": ("line one\nline two", None),
        "a quote": ('she said "no"', None),
        "a backslash": ("C:\\path\\here", None),
        "a tab": ("col\tcol", None),
        "an accent": ("café", None),
        "an emoji beyond the BMP": ("done 😊", None),
        "a control character": ("bell\x07here", None),
    }

    @pytest.mark.parametrize("what", sorted(ESCAPED))
    @pytest.mark.parametrize("size", [1, 2, 3, 5])
    def test_it_survives_being_cut_anywhere(self, what, size):
        text = self.ESCAPED[what][0]
        reply = json.dumps({"answer": text})   # ensure_ascii: \uXXXX for all
        _got, seen = streamed(content_frames(*cut(reply, size)), bound=1000)
        assert "".join(seen) == text

    def test_an_unpaired_high_surrogate_is_dropped_rather_than_emitted(self):
        """A lone surrogate is not encodable UTF-8; the sink would have to
        mangle it, and the whole character arrives on `answer` anyway."""
        _got, seen = streamed(
            content_frames('{"answer": "a\\ud83db"}'), bound=1000)
        assert "".join(seen) == "ab"

    def test_a_broken_unicode_escape_stops_the_decoder_without_raising(self):
        _got, seen = streamed(
            content_frames('{"answer": "a\\uZZZZb"}'), bound=1000)
        assert "".join(seen) == "a"


class TestTheFragmentsAreBounded:
    """A record per token is a record every 17 ms. The rule, asserted."""

    def test_nothing_is_emitted_until_the_bound_is_reached(self):
        text = "x" * (BOUND_CHARS - 1)
        _got, seen = streamed(content_frames(json.dumps({"answer": text})))
        assert seen == [text], "one flush, at the end, and not before"

    def test_a_long_answer_is_cut_at_the_bound(self):
        text = "y" * (BOUND_CHARS * 3)
        _got, seen = streamed(content_frames(json.dumps({"answer": text})))
        assert [len(piece) for piece in seen] == [BOUND_CHARS] * 3
        assert "".join(seen) == text

    def test_a_newline_flushes_early(self):
        """A line break is where a reader's eye goes, and holding one back
        to fill a quota makes a list arrive in the wrong shape."""
        text = "- one\n- two\n"
        _got, seen = streamed(content_frames(json.dumps({"answer": text})))
        assert seen == ["- one\n", "- two\n"]

    def test_the_last_partial_fragment_is_flushed_when_the_stream_ends(self):
        text = "z" * (BOUND_CHARS + 5)
        _got, seen = streamed(content_frames(json.dumps({"answer": text})))
        assert [len(piece) for piece in seen] == [BOUND_CHARS, 5]


# ── the native protocol ──────────────────────────────────────────────────────


class TestTheNativeDecoder:
    """The `text` argument of the `mission_answer` call, as it arrives."""

    def test_the_arguments_stream_across_the_fragments_that_carry_them(self):
        _got, seen = streamed(call_frames(
            fragment(name=ANSWER_TOOL, arguments='{"te', call_id="a"),
            fragment(arguments='xt": "the cable '),
            fragment(arguments='was cut"}'),
        ), native=True, bound=1000)
        assert "".join(seen) == "the cable was cut"

    @pytest.mark.parametrize("size", [1, 2, 5, 11])
    def test_however_the_arguments_are_cut(self, size):
        arguments = json.dumps({"text": ANSWER})
        frames = [fragment(name=ANSWER_TOOL, arguments="", call_id="a")]
        frames += [fragment(arguments=piece) for piece in cut(arguments, size)]
        _got, seen = streamed(call_frames(*frames), native=True, bound=1000)
        assert "".join(seen) == ANSWER

    def test_a_tool_call_that_is_not_the_answer_emits_nothing(self):
        _got, seen = streamed(call_frames(
            fragment(name="catalog.search", arguments='{"q": '),
            fragment(arguments='"assets"}'),
        ), native=True)
        assert seen == []

    def test_an_answer_alongside_a_tool_call_streams_only_the_answer(self):
        """Two calls in one turn, kept apart by index exactly as
        `ToolCallAccumulator` keeps them apart."""
        _got, seen = streamed(call_frames(
            fragment(index=0, name="catalog.search", arguments='{"q":'),
            fragment(index=1, name=ANSWER_TOOL, arguments='{"text":'),
            fragment(index=0, arguments=' "x"}'),
            fragment(index=1, arguments=' "we hold three"}'),
        ), native=True, bound=1000)
        assert "".join(seen) == "we hold three"

    def test_arguments_that_arrive_before_the_name_does_are_not_lost(self):
        """A server is not obliged to put the name in the first frame."""
        _got, seen = streamed(call_frames(
            fragment(arguments='{"text": "held'),
            fragment(name=ANSWER_TOOL, arguments=' back"}'),
        ), native=True, bound=1000)
        assert "".join(seen) == "held back"

    def test_only_the_first_answer_call_streams(self):
        """Two `mission_answer` calls is a turn the loop refuses; rendering
        the second over the first would show text no answer will match."""
        _got, seen = streamed(call_frames(
            fragment(index=0, name=ANSWER_TOOL, arguments='{"text": "first"}'),
            fragment(index=1, name=ANSWER_TOOL, arguments='{"text": "second"}'),
        ), native=True, bound=1000)
        assert "".join(seen) == "first"

    def test_the_content_of_a_native_turn_is_not_the_answer(self):
        """A harmony model writes a preamble in `content` and the decision
        in the call. The preamble is the reply and never a fragment."""
        got, seen = streamed([
            _Delta(content="Let me think. "),
            _Delta(tool_calls=fragment(name=ANSWER_TOOL,
                                       arguments='{"text": "done"}')),
        ], native=True, bound=1000)
        assert got == "Let me think. "
        assert "".join(seen) == "done"

    def test_unreadable_arguments_never_raise(self):
        _got, seen = streamed(call_frames(
            fragment(name=ANSWER_TOOL, arguments="}{ nonsense"),
        ), native=True)
        assert seen == []


# ── what the caller gets back ────────────────────────────────────────────────


class TestTheReplyIsWhatTheLoopReads:
    def test_the_content_is_accumulated_whatever_the_decoder_did(self):
        got, _seen = streamed(content_frames("{", '"answer"', ": ", '"hi"}'))
        assert got == '{"answer": "hi"}'

    def test_frames_with_no_choices_are_ignored(self):
        """The usage frame: `choices` is empty and it is not a delta."""
        empty = _Delta()
        empty.choices = []
        got, seen = streamed([*content_frames('{"answer": "a"}'), empty],
                             bound=1000)
        assert got == '{"answer": "a"}'
        assert seen == ["a"]

    def test_a_frame_of_a_shape_nobody_sends_does_not_raise(self):
        got, seen = streamed([object(), None, _Delta(content="x")])
        assert got == "x"
        assert seen == []

    def test_an_iterator_that_dies_still_flushes_what_arrived(self):
        """A server that stopped mid-answer is a fact about the mission and
        the exception is the caller's — but the fragments already decoded
        were already true."""
        def dying():
            yield _Delta(content='{"answer": "half an ans')
            raise RuntimeError("the endpoint went away")

        seen = []
        with pytest.raises(RuntimeError):
            drain(dying(), seen.append, answer_tool=ANSWER_TOOL, bound=1000)
        assert "".join(seen) == "half an ans"

    def test_close_is_what_hands_the_reply_back(self):
        stream = AnswerStream(lambda _text: None)
        for frame in content_frames("a", "b"):
            stream.feed(frame)
        assert stream.close() == "ab"


class TestTheKeysMatchTheProtocolsTheyDecode:
    """A decoder streaming one key while the loop answers on another would
    show a pane text that never becomes an answer. Pinned, both ways."""

    def test_the_json_key_is_the_one_the_loop_parses(self):
        from core.runtime.mission import MissionRunner

        decision, problem = MissionRunner._parse(
            json.dumps({JSON_ANSWER_KEY: "done"}))
        assert problem is None
        assert decision[JSON_ANSWER_KEY] == "done"

    def test_the_native_key_is_the_one_the_answer_function_declares(self):
        from core.runtime.mission import ANSWER_FUNCTION, ANSWER_TOOL as TOOL

        parameters = ANSWER_FUNCTION["function"]["parameters"]
        assert parameters["required"] == [NATIVE_ANSWER_KEY]
        assert NATIVE_ANSWER_KEY in parameters["properties"]
        assert TOOL == ANSWER_TOOL
