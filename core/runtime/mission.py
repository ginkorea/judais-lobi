# core/runtime/mission.py — the loop where the model chooses the tool

"""A plan/act loop seeded with ``tools/list``.

Everywhere else in this package the *operator* chooses the tool: you
type ``--shell`` and a shell tool runs, ``--search`` and a search tool
runs.  That works because the tool set is fixed and the person typing
knows it.

It cannot work for an agent talking to a server it discovers at runtime.
Nobody can add a flag for a tool that did not exist when the CLI was
written.  So the mission flow inverts it: the catalogue is put in front
of the model, and the model names the tool.

The loop is deliberately small and its refusals are deliberately loud:

* every call goes through ``ToolBus.dispatch``, so capability gating,
  the panic switch and the audit log all still apply.  The runner never
  touches a store, a path or a compute plane itself, and holds no HTTP
  client of its own;
* the model replies with **one** JSON object and nothing else.  A reply
  that does not parse is handed back to the model as a parse error
  rather than guessed at;
* a tool the model invented is a refused step with the real catalogue
  repeated, not a crash;
* the step budget is a hard stop.  Running out is a recorded outcome
  (``budget_exhausted``) and not a silent truncation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

#: The whole protocol between the loop and the model.  Kept in one string
#: because a contract split across three f-strings is a contract that
#: drifts from the parser below it.
PROTOCOL = """\
You are working a mission with tools. Reply with exactly one JSON object \
and no other text, no code fence, no commentary.

To use a tool:
  {"tool": "<tool name from the catalogue>", "arguments": {...}}

To finish:
  {"answer": "<your final answer>"}

Use only tool names from the catalogue below, spelled exactly. Call one \
tool per reply. Base every statement on a tool result you actually \
received; if the tools cannot support a statement, say so in the answer \
instead of asserting it.
"""

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


@dataclass
class MissionStep:
    """One turn: what the model said, and what came back."""

    index: int
    raw_reply: str
    tool: Optional[str] = None
    arguments: Dict[str, Any] = field(default_factory=dict)
    exit_code: Optional[int] = None
    output: str = ""
    error: str = ""

    @property
    def refused(self) -> bool:
        return self.exit_code is not None and self.exit_code != 0


@dataclass
class MissionTranscript:
    """The whole run, in the order it happened."""

    objective: str
    catalogue: List[str] = field(default_factory=list)
    steps: List[MissionStep] = field(default_factory=list)
    answer: Optional[str] = None
    outcome: str = "incomplete"

    @property
    def completed(self) -> bool:
        return self.outcome == "answered"


class MissionRunner:
    """Seed the plan with a tool catalogue, then let the model drive.

    Parameters
    ----------
    chat_fn:
        ``messages -> str``.  Injected rather than an ``Agent`` so the
        loop is testable without a backend and so it cannot reach past
        the client it was given.
    bus:
        A :class:`~core.tools.bus.ToolBus`.  The only way out of here.
    tool_names:
        Which registered tools this mission may use.  A subset, not the
        whole bus: a mission agent is given the mission's tools, and
        handing it ``run_shell_command`` because it happened to be
        registered is how a governed run stops being governed.
    """

    def __init__(
        self,
        chat_fn: Callable[[List[Dict[str, str]]], Any],
        bus: Any,
        tool_names: Sequence[str],
        *,
        system_message: str = "",
        max_steps: int = 8,
    ):
        self._chat = chat_fn
        self._bus = bus
        self._tool_names = list(tool_names)
        self._system_message = system_message
        self._max_steps = max_steps

    # ── the catalogue ───────────────────────────────────────────────────

    def catalogue(self) -> str:
        """Render the bus's own descriptions; do not restate them.

        ``describe_tool`` is what ``tools/list`` became once it crossed
        the bridge.  Rewriting it here would be a second copy of a tool's
        contract, and the two would disagree the first time a server
        changed a description.
        """
        lines = []
        for name in self._tool_names:
            info = self._bus.describe_tool(name)
            if "error" in info:
                continue
            desc = info.get("description") or ""
            lines.append(f"- {name}: {desc}".rstrip())
        return "\n".join(lines) if lines else "(no tools available)"

    def seed(self, objective: str) -> List[Dict[str, str]]:
        """The PLAN-phase messages: persona, protocol, catalogue, objective."""
        system = "\n\n".join(
            part for part in (
                self._system_message.strip(),
                PROTOCOL.strip(),
                "Tool catalogue:\n" + self.catalogue(),
            ) if part
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": objective},
        ]

    # ── the loop ────────────────────────────────────────────────────────

    def run(self, objective: str) -> MissionTranscript:
        transcript = MissionTranscript(
            objective=objective, catalogue=list(self._tool_names),
        )
        messages = self.seed(objective)

        for index in range(self._max_steps):
            reply = str(self._chat(messages) or "")
            step = MissionStep(index=index, raw_reply=reply)
            messages.append({"role": "assistant", "content": reply})

            decision, problem = self._parse(reply)
            if problem:
                step.error = problem
                transcript.steps.append(step)
                messages.append({"role": "user", "content": problem})
                continue

            if "answer" in decision:
                transcript.answer = str(decision["answer"])
                transcript.outcome = "answered"
                transcript.steps.append(step)
                return transcript

            name = str(decision.get("tool") or "")
            arguments = decision.get("arguments") or {}
            if not isinstance(arguments, dict):
                problem = (
                    f'"arguments" must be a JSON object, got '
                    f"{type(arguments).__name__}. Retry with one JSON object."
                )
                step.tool, step.error = name, problem
                transcript.steps.append(step)
                messages.append({"role": "user", "content": problem})
                continue

            step.tool, step.arguments = name, dict(arguments)

            if name not in self._tool_names:
                problem = (
                    f"There is no tool named {name!r} in this mission. "
                    f"Choose one of: {', '.join(self._tool_names) or '(none)'}."
                )
                step.error = problem
                transcript.steps.append(step)
                messages.append({"role": "user", "content": problem})
                continue

            result = self._bus.dispatch(name, **arguments)
            step.exit_code = result.exit_code
            step.output = result.stdout
            step.error = result.stderr
            transcript.steps.append(step)
            messages.append({
                "role": "user",
                "content": self._render_result(name, result),
            })

        transcript.outcome = "budget_exhausted"
        return transcript

    # ── parsing ─────────────────────────────────────────────────────────

    @staticmethod
    def _parse(reply: str):
        """Return ``(decision, problem)``; exactly one is truthy.

        A model that wrapped its JSON in a fence gets the fence stripped
        — that is a formatting slip, not a different decision.  A model
        that said something else entirely gets told what was expected,
        because guessing an intent out of prose is how a loop calls a
        tool nobody asked for.
        """
        text = _FENCE.sub("", (reply or "").strip()).strip()
        if not text:
            return None, "Empty reply. Reply with one JSON object."
        try:
            decision = json.loads(text)
        except json.JSONDecodeError as exc:
            return None, (
                f"That was not valid JSON ({exc.msg}). Reply with exactly one "
                f'JSON object: {{"tool": ..., "arguments": {{...}}}} or '
                f'{{"answer": ...}}.'
            )
        if not isinstance(decision, dict):
            return None, (
                f"Expected a JSON object, got a {type(decision).__name__}. "
                f"Reply with one JSON object."
            )
        if "answer" not in decision and "tool" not in decision:
            return None, (
                'The object needs either a "tool" key or an "answer" key. '
                "Reply with one JSON object."
            )
        return decision, None

    @staticmethod
    def _render_result(name: str, result: Any) -> str:
        if result.exit_code == 0:
            body = result.stdout or "(no output)"
            return f"Result of {name} (ok):\n{body}"
        body = result.stderr or result.stdout or "(no detail)"
        return (
            f"Result of {name} (refused, exit {result.exit_code}):\n{body}\n"
            f"Do not retry the same call unchanged."
        )
