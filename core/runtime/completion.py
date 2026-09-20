"""Keep usable answer text when generation stops at its output ceiling.

This is not a tool-argument repairer. Only answer strings may be recovered;
an incomplete action envelope never becomes an executable decision here.
"""

from dataclasses import dataclass
import json
import re
from typing import Any, Dict, Optional, Sequence

from core.runtime.mission import ANSWER_TOOL, strip_envelope


def _text_prefix(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    # A cut between an escaped UTF-16 surrogate pair is not a complete
    # Unicode character. Keep the valid prefix rather than break UTF-8 output.
    if value and 0xD800 <= ord(value[-1]) <= 0xDBFF:
        return value[:-1]
    return value


def _answer_string(text: str, field: str) -> Optional[str]:
    match = re.match(r'^\{\s*"' + field + r'"\s*:\s*', text)
    if match is None:
        return None
    value = text[match.end():]
    try:
        parsed, _ = json.JSONDecoder().raw_decode(value)
        return _text_prefix(parsed)
    except json.JSONDecodeError:
        if not value.startswith('"'):
            return None
    # Close only an unterminated answer string. Up to six terminal characters
    # may be an incomplete JSON escape (e.g. \u123); no other repairs or
    # arbitrary executable fields are accepted. json.loads checks the prefix.
    for cut in range(min(7, len(value))):
        prefix = value if cut == 0 else value[:-cut]
        try:
            parsed = json.loads(prefix + '"')
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, str):
            return _text_prefix(parsed)
    return None


def answer_fragment(reply: str, calls: Sequence[Dict[str, Any]]) -> Optional[str]:
    """Return answer prose only, never raw incomplete JSON or action arguments."""
    if calls:
        if len(calls) != 1 or calls[0]["name"] != ANSWER_TOOL:
            return None
        call = calls[0]
        text = call["arguments"].get("text")
        if isinstance(text, str):
            return text
        return _answer_string(str(call.get("raw") or ""), "text")
    # Trailing whitespace can be INSIDE an unfinished JSON string, including
    # one preceded by a channel marker or code fence.
    text = strip_envelope(reply, preserve_trailing=True)
    unwrapped = text == reply.lstrip()
    if text.startswith("{"):
        return _answer_string(text, "answer")
    # Lists and fenced JSON cannot be safely presented as a prose answer when
    # they are unfinished. The raw model recording still keeps the bytes.
    if text.startswith(("[", "```json")):
        return None
    return (reply if unwrapped else text) if text else None


@dataclass
class AnswerContinuation:
    """At most two text-only continuation calls, within the run's own bounds."""

    text: str = ""
    attempts: int = 0
    maximum: int = 2

    def append(self, fragment: str) -> bool:
        before = self.text
        if fragment.startswith(before):
            self.text = fragment
        elif not before.endswith(fragment):
            overlap = next((n for n in range(min(len(before), len(fragment), 4096), 11, -1)
                            if before[-n:] == fragment[:n]), 0)
            self.text += fragment[overlap:]
        return self.text != before

    def prompt(self) -> str:
        return (
            "The answer was cut off by the output-token limit. The preceding "
            "assistant text is a partial answer already retained, not a new task. "
            "Continue with ONLY the remaining answer text, using the normal answer "
            "envelope or mission_answer. Do not repeat completed sections. Start "
            "with any whitespace needed at the boundary. Do not call tools, "
            "repeat searches, or repeat an action to regenerate text. If the "
            "remaining material cannot be supported, state what remains unresolved.")
