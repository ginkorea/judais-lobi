# core/runtime/answer_stream.py — the answer, while it is still being written

"""Read the answer out of a reply that has not finished arriving.

A mission on a 59 tok/s local endpoint spends most of its wall clock
inside one model call, and until that call returns the loop has nothing
to say.  ``tool_call`` and ``tool_result`` already cover the middle of a
mission; the part with no records at all is the last turn, the one where
the model is writing the answer somebody is waiting to read.

So the model call streams, and the fragments of the answer go out as
:data:`~core.runtime.contract.ANSWER_DELTA` records.  **The grounding
verdict rides the answer's own frames** — a deployment that fanned one
finished ``answer`` into bounded pieces on its own side could show text
arriving, but it could not show text arriving *before the harness knew
whether it was grounded*, and it had to guess at where the pieces went.
Here the pieces are the model's, the ordinal is the harness's, and the
``answer`` record that follows is still the authority.

**This module owns one thing: turning delta frames into answer text.**
It decides nothing about the loop, emits no records itself, and holds no
opinion about what a mission is.  :meth:`AnswerStream.close` hands back
the accumulated ``content`` and the caller carries on with exactly the
string a non-streamed call would have returned.

Two decoders, because there are two protocols and the answer is in a
different place in each:

* **json** — the reply is one JSON object and the answer is the value of
  its top-level ``"answer"`` key.  Only a **top-level** key counts: a
  ``{"tool": …, "arguments": {"answer": …}}`` reply must emit nothing,
  and the way to be sure of that while the object is still half-written
  is to track brace depth rather than to search for a substring.
* **native** — the answer is the ``"text"`` argument of the
  ``mission_answer`` call, and the arguments arrive as pieces of a JSON
  string spread over many ``delta.tool_calls`` fragments.  Same decoder,
  pointed at a different key of a different object.

**Nothing here may raise into the loop.**  A decoder that meets something
it does not understand stops emitting — that is the whole error policy,
and it is safe precisely because the deltas are provisional: the final
``answer`` is produced from the complete reply by the same parser that
always produced it, so a decoder that gave up costs a pane its live
rendering and costs the mission nothing.

**Fragments are bounded before they are emitted.**  A record per token is
a record every 17 ms on a local endpoint, most of them three characters
long, and the cost of that is paid by the durable log and by every
consumer.  :data:`BOUND_CHARS` characters, or a newline, whichever comes
first — see :class:`_Bounded`.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional

from core.runtime.backends.base import attr_or_key

__all__ = [
    "BOUND_CHARS", "JSON_ANSWER_KEY", "NATIVE_ANSWER_KEY", "AnswerStream",
    "drain",
]

#: How much decoded answer text is allowed to pile up before a fragment is
#: emitted.  A newline flushes early, because a line break is where a
#: reader's eye goes and holding one back to fill a quota makes a list
#: arrive in the wrong shape.
#:
#: 64 was chosen against the endpoint this framework is measured on: a
#: served gpt-oss-20b at ~59 tok/s emits roughly 15 tokens a second of
#: three or four characters each, so this is a record about every second
#: — often enough to read as live, rare enough that a 4,000-character
#: answer is ~60 records rather than ~1,000.  It is a display bound and
#: not a protocol constant: a consumer must never assume a fragment
#: boundary means anything.
BOUND_CHARS = 64

#: The top-level key of a JSON-protocol reply whose value is the answer.
#: The same word :meth:`~core.runtime.mission.MissionRunner._parse` reads
#: out of the finished object; a test pins the two together, because a
#: decoder streaming one key while the loop answers on another would show
#: a pane text that never becomes an answer.
JSON_ANSWER_KEY = "answer"

#: The argument of the native protocol's answer function that carries the
#: answer — :data:`~core.runtime.mission.ANSWER_FUNCTION` declares it, and
#: the same test pins these together.
NATIVE_ANSWER_KEY = "text"

#: What a two-character escape decodes to.  Anything else after a
#: backslash is passed through as itself, which is what a lenient reader
#: does with ``\\q``: the finished reply is parsed by :mod:`json` and this
#: is a display rendering of it.
_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f",
            "n": "\n", "r": "\r", "t": "\t"}


class _TopLevelString:
    """Decode the value of one top-level string key, as the text arrives.

    Fed the raw characters of a JSON object in whatever pieces they came
    in — ``feed`` may be called with one character or with the whole
    thing — and returns the decoded fragment of the wanted value that
    became readable on that call.  ``""`` until the key is reached, and
    ``""`` forever after :attr:`done`.

    The awkward cases are all "the piece ended in the middle of
    something": mid-``\\``-escape, mid-``\\uXXXX``, mid-surrogate-pair,
    mid-key.  Every one of them is handled by consuming only what is
    complete and leaving the rest in :attr:`_buf` for the next call, so a
    caller may split the stream anywhere at all.

    **Top level means depth 1.**  Depth is counted over ``{[`` and ``]}``
    and a key is only a key when the ``:`` that follows it is read at
    depth 1, so the ``"answer"`` inside ``{"tool": "x", "arguments":
    {"answer": "no"}}`` is never mistaken for the answer.  Text before the
    opening brace — a fence, a harmony preamble — is scanned at depth 0
    and cannot start anything.

    An unpaired surrogate is **dropped** rather than emitted.  A lone
    ``\\ud83d`` is not encodable UTF-8, the sink would have to mangle it,
    and the character it was half of arrives whole on the ``answer``
    record either way.
    """

    def __init__(self, key: str):
        self._key = key
        self._buf = ""
        self._depth = 0
        self._in_string = False
        self._escaped = False
        self._current: List[str] = []
        self._last_string: Optional[str] = None
        self._expect_value = False
        self._streaming = False
        #: Set when the value has been fully read, when the object closed
        #: without it, or when something was met that this cannot decode.
        #: Either way the answer to "is there more?" is no.
        self.done = False

    def feed(self, text: str) -> str:
        """The decoded fragment of the wanted value in *text*, or ``""``."""
        if self.done or not text:
            return ""
        self._buf += text
        out: List[str] = []
        index = 0
        limit = len(self._buf)
        while index < limit and not self.done:
            char = self._buf[index]
            if self._streaming:
                if char == "\\":
                    consumed, piece = self._escape_at(index)
                    if not consumed:
                        break                   # mid-escape; wait for more
                    out.append(piece)
                    index += consumed
                    continue
                if char == '"':
                    self._streaming = False
                    self.done = True
                    index += 1
                    continue
                out.append(char)
                index += 1
                continue
            index = self._scan(char, index)
        self._buf = self._buf[index:]
        return "".join(out)

    # ── the structure around the value ──────────────────────────────────

    def _scan(self, char: str, index: int) -> int:
        """One character of the object outside the wanted value."""
        if self._in_string:
            if self._escaped:
                self._escaped = False
                self._current.append(char)
            elif char == "\\":
                self._escaped = True
            elif char == '"':
                self._in_string = False
                self._last_string = "".join(self._current)
                self._current = []
            else:
                self._current.append(char)
            return index + 1
        if char == '"':
            if self._expect_value:
                # The value of the key we came for, and it is a string.
                self._expect_value = False
                self._streaming = True
                return index + 1
            self._in_string = True
            self._current = []
            self._last_string = None
            return index + 1
        if self._expect_value and not char.isspace():
            # The key's value is a number, a literal, an object or a list.
            # Nothing to stream, and nothing further worth reading.
            self.done = True
            return index
        if char in "{[":
            self._depth += 1
            self._last_string = None
        elif char in "}]":
            if self._depth > 0:
                self._depth -= 1
                if self._depth == 0:
                    # The object closed and the key never appeared.
                    self.done = True
            self._last_string = None
        elif char == ":":
            if self._depth == 1 and self._last_string == self._key:
                self._expect_value = True
            self._last_string = None
        elif char == ",":
            self._last_string = None
        return index + 1

    # ── escapes ─────────────────────────────────────────────────────────

    def _escape_at(self, index: int) -> tuple:
        """``(characters consumed, decoded text)``; ``(0, "")`` means wait.

        Zero consumed is the whole of the "a fragment split mid-escape"
        story: nothing is emitted, nothing is thrown away, and the same
        characters are looked at again when the rest of them arrive.
        """
        buf = self._buf
        if index + 1 >= len(buf):
            return 0, ""
        marker = buf[index + 1]
        if marker != "u":
            return 2, _ESCAPES.get(marker, marker)
        if index + 6 > len(buf):
            return 0, ""
        point = self._hex(buf[index + 2:index + 6])
        if point is None:
            # Not JSON any writer produced. Stop rather than guess: the
            # `answer` record is made from the whole reply and is unharmed.
            self.done = True
            return 0, ""
        if 0xDC00 <= point <= 0xDFFF:
            return 6, ""                        # a low surrogate on its own
        if not 0xD800 <= point <= 0xDBFF:
            return 6, chr(point)
        # A high surrogate: it means nothing without the low one that
        # follows it, and whether one follows is not knowable yet.
        if index + 8 > len(buf):
            return 0, ""
        if buf[index + 6:index + 8] != "\\u":
            return 6, ""                        # unpaired; dropped
        if index + 12 > len(buf):
            return 0, ""
        low = self._hex(buf[index + 8:index + 12])
        if low is None or not 0xDC00 <= low <= 0xDFFF:
            return 6, ""
        return 12, chr(0x10000 + ((point - 0xD800) << 10) + (low - 0xDC00))

    @staticmethod
    def _hex(digits: str) -> Optional[int]:
        try:
            return int(digits, 16)
        except ValueError:
            return None


class _Bounded:
    """Hold decoded text back until there is enough of it to be a record.

    The rule, in one place: emit when :data:`BOUND_CHARS` characters have
    piled up, or as soon as a newline arrives — up to and including it —
    and flush whatever is left when the stream ends.  A fragment boundary
    therefore says nothing about the text: it is not a token, not a word,
    not a sentence.  Concatenating the fragments is the only operation a
    consumer may perform on them.
    """

    def __init__(self, on_delta: Callable[[str], None], bound: int = BOUND_CHARS):
        self._on_delta = on_delta
        self._bound = max(1, int(bound))
        self._pending = ""

    def add(self, text: str) -> None:
        if not text:
            return
        self._pending += text
        while self._pending:
            cut = self._pending.find("\n")
            if cut >= 0:
                self._emit(cut + 1)
                continue
            if len(self._pending) >= self._bound:
                self._emit(self._bound)
                continue
            break

    def close(self) -> None:
        if self._pending:
            self._emit(len(self._pending))

    def _emit(self, upto: int) -> None:
        piece, self._pending = self._pending[:upto], self._pending[upto:]
        self._on_delta(piece)


class AnswerStream:
    """Drain a backend's delta iterator: keep the reply, emit the answer.

    One instance per model call.  :meth:`feed` takes the objects a
    streaming backend yields — ``chunk.choices[0].delta`` with ``content``
    and ``tool_calls``, the OpenAI shape every backend in this tree
    matches — and :meth:`close` returns the accumulated ``content``, which
    is the ``reply`` string the loop then treats exactly as it treats a
    non-streamed one.

    *on_delta* is called with each bounded fragment of the answer, in
    order.  It is the caller's job to number them and put them on the
    stream: this class does not know what a record is.

    The content is accumulated **whatever the decoder does**.  Decoding is
    a rendering and the reply is the mission's; a decoder that gave up
    must not be able to cost the loop its turn.
    """

    def __init__(self, on_delta: Callable[[str], None], *,
                 native: bool = False, answer_tool: str = "",
                 bound: int = BOUND_CHARS):
        self._content: List[str] = []
        self._bounded = _Bounded(on_delta, bound)
        self._native = bool(native)
        self._answer_tool = str(answer_tool or "")
        self._decoder: Optional[_TopLevelString] = (
            None if self._native else _TopLevelString(JSON_ANSWER_KEY))
        #: Native only: one slot per ``delta.tool_calls`` index, because
        #: the name arrives on the first fragment and the arguments on all
        #: of them, and which call is the answer is not knowable until the
        #: name has been seen.
        self._slots: Dict[Any, Dict[str, Any]] = {}
        self._answering: Any = None
        self._broken = False

    def feed(self, chunk: Any) -> None:
        """Fold one frame in.  Never raises."""
        for choice in _as_sequence(attr_or_key(chunk, "choices")):
            delta = attr_or_key(choice, "delta")
            if delta is None:
                continue
            content = attr_or_key(delta, "content")
            if isinstance(content, str) and content:
                self._content.append(content)
            try:
                if self._native:
                    self._fragments(attr_or_key(delta, "tool_calls"))
                elif isinstance(content, str) and content:
                    self._decode(content)
            except Exception:               # pragma: no cover - defensive
                # The error policy, in one place: stop rendering, keep the
                # reply. See the module docstring.
                self._broken = True
                self._decoder = None

    def close(self) -> str:
        """Flush the last fragment and hand back the whole reply."""
        try:
            self._bounded.close()
        except Exception:                   # pragma: no cover - defensive
            self._broken = True
        return "".join(self._content)

    @property
    def broken(self) -> bool:
        """Whether the decoder gave up.  Diagnostic; nothing branches on it."""
        return self._broken

    # ── the json protocol ───────────────────────────────────────────────

    def _decode(self, content: str) -> None:
        if self._decoder is None or self._decoder.done:
            return
        self._bounded.add(self._decoder.feed(content))

    # ── the native protocol ─────────────────────────────────────────────

    def _fragments(self, fragments: Any) -> None:
        """Stream the ``text`` argument of the ``mission_answer`` call.

        Fragments are keyed by ``index`` exactly as
        :class:`~core.runtime.backends.base.ToolCallAccumulator` keys
        them, and for the same reason: after the first frame that is all
        a fragment carries.  Arguments that arrive before the name does
        are held, because a frame may well carry ``{"te`` before anything
        has said which function it belongs to.

        Only the FIRST ``mission_answer`` call streams.  A turn that
        called it twice is refused by the loop, and rendering the second
        one over the first would show a pane text no answer will match.
        """
        if not self._answer_tool:
            return
        for position, fragment in enumerate(_as_sequence(fragments)):
            if fragment is None:
                continue
            index = attr_or_key(fragment, "index")
            if not isinstance(index, int) or isinstance(index, bool):
                index = f"position-{position}"
            slot = self._slots.setdefault(
                index, {"name": "", "pending": "", "decoder": None})
            function = attr_or_key(fragment, "function")
            name = attr_or_key(function, "name")
            if name:
                slot["name"] = str(name)
            arguments = attr_or_key(function, "arguments")
            if isinstance(arguments, str) and arguments:
                slot["pending"] += arguments
            if (self._answering is None
                    and slot["name"] == self._answer_tool):
                self._answering = index
                slot["decoder"] = _TopLevelString(NATIVE_ANSWER_KEY)
            if index != self._answering or slot["decoder"] is None:
                continue
            held, slot["pending"] = slot["pending"], ""
            if held and not slot["decoder"].done:
                self._bounded.add(slot["decoder"].feed(held))


def _as_sequence(value: Any) -> Iterable[Any]:
    """*value* when it is a list or a tuple, and ``()`` for anything else."""
    return value if isinstance(value, (list, tuple)) else ()


def drain(chunks: Iterable[Any], on_delta: Callable[[str], None], *,
          native: bool = False, answer_tool: str = "",
          bound: int = BOUND_CHARS) -> str:
    """Consume a streamed model call and return the reply it amounts to.

    The one function the loop calls.  Iteration errors are the caller's —
    a server that died mid-answer is a fact about the mission and not
    something to swallow — but whatever had been decoded by then is
    flushed on the way out, in a ``finally``, so a consumer keeps the
    fragments it was already shown.
    """
    stream = AnswerStream(on_delta, native=native, answer_tool=answer_tool,
                          bound=bound)
    try:
        for chunk in chunks:
            stream.feed(chunk)
    finally:
        reply = stream.close()
    return reply
