# core/runtime/skills.py — a skill manifest: what the model is told, and what it may call

"""Load a ``SKILL.md`` — YAML frontmatter plus a Markdown body — into the
three things a mission needs from it.

A mission agent has two halves.  The loop lives here
(:mod:`core.runtime.mission`); the *operational knowledge* — which facet
to query first, which tool answers which question, what an identifier
looks like, what must never be invented — belongs to whoever operates the
platform being driven.  A manifest is how that half arrives, and this
module is deliberately the only place that reads one.

Six things come out of a manifest, and nothing else does:

* a **closed tool subset**, intersected with what was actually
  discovered.  A skill that names a tool the server does not offer is a
  refusal listing every missing name, never a silent narrowing: a
  manifest whose closed set quietly became empty produces an agent that
  answers from memory, which is the exact failure the closed set exists
  to prevent;
* **prompt text** — the frontmatter's operational fields and the whole
  Markdown body — injected into the mission's system message;
* an optional **grounding configuration**: the identifier grammar and
  the strictness a :mod:`core.runtime.grounding` validator enforces over
  the answer.  The grammar is content and lives in the file.  What the
  harness owns is the checking;
* an optional **rule pack** (``cognition:``): the cardinalities, horn
  clauses, goals and constraints a run reasons under when ``--cognition``
  is on.  Read
  by :class:`core.runtime.cognition.RulePack` and never here beyond its
  shape — same division as ``grounding:``, and for the same reason.  It is
  where ``ROADMAP.md`` §2.9.4 puts rule authorship: *rules arrive through
  skills*, because a runtime that derives has to say who wrote the clauses
  and what they cost to write;
* an optional **plane declaration block** (``tools:``): which of a tool's
  result keys are *identifiers* of which kind of subject, what a call
  can establish, and what it produces later through which other call.
  Read by :class:`core.runtime.declarations.ToolsBlock` and never here
  beyond its shape — ``grounding:``'s and ``cognition:``'s arrangement
  exactly.  It is the **fallback** door: the wire owns shape, a server's
  own ``outputSchema`` wins wherever it published one, and this block is
  how a platform declares the same things about a server it does not
  control.  Nothing in it reaches the model;
* an optional **SDK import name** (``sdk_import``): what a platform calls
  itself to Python.  A planner that can propose *code which fetches
  platform data itself* has to name the module that does the fetching,
  and the harness cannot know it — the framework drives whatever platform
  it is pointed at.  Declared here, it composes the sentence
  :mod:`core.runtime.swarm` shows the executor; undeclared, that whole
  rung is withheld rather than offered with a blank where the name goes.

One thing a manifest is *refused* for, and it is the reason
:attr:`SkillManifest.sandbox` exists: a closed set that names a tool
which **runs code the model composed on this host** — a shell, an
interpreter, a ``pip install`` — and does not say ``sandbox: bwrap``
next to it.  A governed mission that can run arbitrary code on the host
without isolation is the hazard TAIPAN's
``HOSTED_SDK_CODE_PLANE_DESIGN.md`` names, and it is not one a hosted
platform should have to find in a transcript.  The check runs in both
directions — the declaration is required of the manifest, and the
isolation is required of the bus the mission is about to run on, because
a manifest that asked for bwrap and got ``none`` asked for nothing.

*On this host* is load-bearing and is the correction 0.14 made to it.
A **bridged** tool — ``mcp.run_shell_command``, a name this bus resolves
to a ``tools/call`` on a discovered server — executes on the server, and
bwrap here would isolate nothing about it.  Gating it on that rule
demanded a declaration nobody could honestly make; it is not gated, and
what governs it instead is the server, the closed set, the ``mcp.call``
capability and ``--gate-tool``.  See
:meth:`SkillManifest.code_plane_entries`.

**Skills compose.**  ``--skill`` repeats, and several manifests fold
into one by :func:`compose_manifests` — the first is the primary and owns
the mission's identity and its answer shape; the rest bring tools, prompt
and grounding strictness, unioned.  One manifest folds to itself,
unchanged.  That function is the only place that knows what running two
skills at once means, for the reason this module is the only place that
knows what one skill means.

**The format is generic.**  Frontmatter between ``---`` fences, an
optional ``skill:`` block for the operational fields, a Markdown body.
Fields this module has never heard of are rendered into the prompt
anyway rather than dropped, because a manifest is content and the
harness is not the authority on which of it matters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from core.tools.descriptors import ALL_DESCRIPTORS, same_tool, tool_key

#: Frontmatter fence.  A line that is exactly three dashes.
_FENCE = re.compile(r"^---[ \t]*$", re.MULTILINE)

#: The scopes that mean *this tool runs code the model composed*.
#:
#: Derived-from rather than a list of names on purpose: a fourth tool
#: that asks for ``shell.exec`` tomorrow is a code-plane tool the day it
#: is registered, without anyone remembering to add it here.  Today they
#: reduce to ``run_shell_command``, ``run_python_code`` and
#: ``install_project``.
#:
#: ``verify.run`` is deliberately absent.  ``verify`` also ends in a
#: subprocess, but the command it runs is the one the *repository*
#: configured in ``.judais-lobi.yml``; the model chooses which of lint,
#: test, typecheck and format to invoke and cannot compose the command.
#: The line this set draws is *who wrote the code that runs*.
CODE_PLANE_SCOPES = frozenset({"python.exec", "shell.exec", "pip.install"})

#: What ``sandbox:`` may say.  ``bwrap`` is the only isolation this
#: framework has a backend for; ``none`` is the explicit statement that
#: none was asked for, which is a legal thing for a manifest with no
#: code-plane tool to say and a refusal for one that has them.  Absent is
#: not the same as ``none`` — absent is silence, and silence is what this
#: check exists to stop being an answer.
SANDBOX_VALUES: Tuple[str, ...] = ("bwrap", "none")

#: The one value that asks for isolation.
BWRAP = "bwrap"

#: An ``allowed_tools`` entry may end in ``?`` to mean *use it if the
#: server offers it*.  Same marker the ``inputs:`` grammar already uses
#: for an optional input (``compare_to: string?``), so a manifest author
#: does not learn a second convention.  Everything without it is
#: required, and a missing required tool is a refusal.
_OPTIONAL = "?"

#: Keys the loader consumes structurally.  They are not rendered into the
#: prompt as prose, because each already reaches the model another way:
#: the tool subset becomes the catalogue, the grounding block becomes a
#: validator, the identity becomes the header line.
#:
#: ``sandbox`` is consumed structurally too and is deliberately **not**
#: held back: it reaches the model no other way, and a model running
#: inside bwrap should be told so.  Network is denied in there, so an
#: agent that has not been told reads ``ENETUNREACH`` as a broken tool
#: and spends a turn retrying it.  It renders like any other field the
#: loader has never heard of — ``Sandbox: bwrap``.
#:
#: ``cognition`` is held back for the plainest of those reasons: it reaches
#: the model through the *conclusions it produces* — the compiled view's
#: derived facts — and a block of YAML horn clauses rendered into a system
#: message would be the runtime asking a 20B to do the inference the
#: runtime just did.
#:
#: ``tools`` is held back for the same reason and one more: it is a
#: statement about what the plane RETURNS, the model is shown what it may
#: call, and the difference between those two is the whole argument for
#: keeping schemas out of a catalogue whose size is a measured hazard.
_STRUCTURAL = frozenset({
    "name", "skill_id", "version", "description",
    "allowed_tools", "grounding", "sdk_import", "cognition", "tools",
})

#: Operational fields rendered first, in this order, with these labels.
#: The order is an argument: what the skill is for, what it may be given,
#: how to retrieve, how to order, what is forbidden, what evidence is
#: required.  ``output_format`` is deliberately absent — it is rendered
#: last, after the body, because it is the instruction a model is acting
#: on when it stops.
_PROMPT_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("when_to_use", "When to use"),
    ("inputs", "Inputs"),
    ("retrieval_strategy", "Retrieval strategy"),
    ("ranking", "Ranking"),
    ("policy", "Policy"),
    ("evidence_requirements", "Evidence requirements"),
)

_OUTPUT_FIELD = "output_format"

#: The label :meth:`SkillManifest._render_prompt` writes the output contract
#: under, and the one :func:`compose_manifests` has to find again to take a
#: supporting skill's answer shape back off.  A literal in both places is two
#: owners of one fact, and the second one drifts silently: a composed prompt
#: would simply keep the supporting contract and the mission would be told to
#: produce two answer shapes.
_OUTPUT_LABEL = "Output format"


def code_plane_tools() -> Dict[str, Tuple[str, ...]]:
    """Every registered tool that runs code, to the scopes that say so.

    ``{"run_shell_command": ("shell.exec",), ...}`` — the name a
    descriptor gave itself, and the members of :data:`CODE_PLANE_SCOPES`
    it asks for, sorted so a refusal reads the same twice.

    Read off :data:`~core.tools.descriptors.ALL_DESCRIPTORS` at call
    time rather than frozen into a constant here, because a second
    hand-maintained list of the dangerous tools is a list that is
    correct until the day it matters.  Per-action scopes count too: a
    multi-action tool whose *one* action asks for ``shell.exec`` is a
    code plane through that action.
    """
    found: Dict[str, Tuple[str, ...]] = {}
    for descriptor in ALL_DESCRIPTORS:
        scopes = set(descriptor.required_scopes or ())
        for action_scopes in (descriptor.action_scopes or {}).values():
            scopes.update(action_scopes or ())
        hit = scopes & CODE_PLANE_SCOPES
        if hit:
            found[descriptor.tool_name] = tuple(sorted(hit))
    return found


def sandbox_name(bus: Any) -> str:
    """What the sandbox on *bus* calls itself: ``bwrap``, ``none``, ``""``.

    THE SEAM, and deliberately the smallest one available: a
    :class:`~core.tools.bus.ToolBus` exposes the runner it will wrap a
    subprocess in as ``bus.sandbox``, and that object's identity is the
    only honest answer to *is this mission isolated*.  It is a question
    about the bus that is about to run, not about a flag somebody passed
    — a ``--unsandboxed`` that did not take effect and a bwrap that is
    not installed have to look the same here, because they are the same
    thing to the manifest that asked for isolation.

    ``""`` means *the caller did not say*, which is not the same as
    ``none``: a library caller holding no bus is not told its manifest
    is unsafe, it is simply not told anything, and
    :meth:`SkillManifest.resolve` skips the runtime half of the check.
    """
    runner = getattr(bus, "sandbox", None)
    if runner is None:
        return ""
    from core.tools.sandbox import BwrapSandbox, NoneSandbox

    if isinstance(runner, BwrapSandbox):
        return BWRAP
    if isinstance(runner, NoneSandbox):
        return "none"
    # A backend nobody has written yet still gets to name itself, on the
    # convention every backend in `core.tools.sandbox` already follows.
    label = type(runner).__name__
    suffix = "Sandbox"
    if label.endswith(suffix) and len(label) > len(suffix):
        label = label[:-len(suffix)]
    return label.lower()


class SkillManifestError(ValueError):
    """A file is not a usable skill manifest, with every reason at once."""


class SkillToolsUnavailable(RuntimeError):
    """A skill's closed set cannot be run here, with every reason at once.

    Two kinds of reason, one refusal, because an operator fixing a
    manifest wants the whole list and not the first line of it:

    * tools the manifest names and this server did not offer.  Raised
      instead of narrowing the set, and it carries what *was* on offer.
      A mission that starts with a silently reduced toolset is a mission
      that answers from the model's memory of the platform, and the
      transcript looks fine;
    * a code plane without isolation — the closed set names a tool that
      runs code the model composed and the manifest never said
      ``sandbox: bwrap``, or it said so and the bus is not running under
      bwrap.  Same shape of failure: the run would look ordinary.
    """


def _require_yaml(path: Path):
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - optional extra
        raise SkillManifestError(
            f"{path.name} has YAML frontmatter, which needs pyyaml: "
            f"pip install 'judais-lobi[mission]'"
        ) from exc
    return yaml


def _render_value(value: Any, indent: str = "") -> str:
    """One frontmatter value as prompt text.

    Folded YAML scalars arrive as one long line; lists arrive as lists;
    ``inputs:`` arrives as a mapping.  All three are things a person
    wrote to be read, so all three are rendered rather than repr'd.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, Mapping):
        return "\n".join(
            f"{indent}- {key}: {_render_value(val)}" for key, val in value.items()
        )
    if isinstance(value, (list, tuple)):
        return "\n".join(f"{indent}- {_render_value(item)}" for item in value)
    return str(value)


@dataclass(frozen=True)
class SkillManifest:
    """One loaded ``SKILL.md``.

    Immutable: a manifest is read once and then quoted, and a mission
    that could edit its own closed set is not operating under one.
    """

    name: str
    description: str = ""
    version: str = ""
    #: Every name in the closed set, in file order, markers stripped.
    allowed_tools: Tuple[str, ...] = ()
    #: The subset of :attr:`allowed_tools` that was marked optional.
    optional_tools: frozenset = frozenset()
    #: The rendered operational fields plus the Markdown body.
    prompt: str = ""
    #: ``output_format``, rendered.  Also the tail of :attr:`prompt`.
    output_contract: str = ""
    #: The raw ``grounding:`` block, or ``None``.  Interpreted by
    #: :mod:`core.runtime.grounding`, never here.
    grounding: Optional[Dict[str, Any]] = None
    #: The raw ``cognition:`` block — the skill's rule pack — or ``None``.
    #: Interpreted by :class:`core.runtime.cognition.RulePack`, never here
    #: beyond its shape, which is ``grounding``'s arrangement exactly.
    #: ``None`` is a skill that wrote none; ``{}`` is a skill that wrote an
    #: empty one, and composition keeps the difference.
    cognition: Optional[Dict[str, Any]] = None
    #: The raw ``tools:`` block — what this platform says its plane returns
    #: — or ``None``.  Interpreted by
    #: :class:`core.runtime.declarations.ToolsBlock`, never here beyond its
    #: shape, and resolved against the wire's own ``outputSchema`` at
    #: fleet-connect, where both halves are in hand.  ``None`` is a skill
    #: that declared nothing; ``{}`` is a skill that wrote an empty block,
    #: and composition keeps the difference.
    tools: Optional[Dict[str, Any]] = None
    #: What the platform's SDK is called to ``import``, or ``""``.  Read
    #: by :mod:`core.runtime.swarm` to compose the ``code+sdk`` rung, and
    #: the reason that rung is offered at all.  Empty is not a defect: a
    #: platform reached only through its tools has no SDK to name.
    sdk_import: str = ""
    #: The isolation the manifest asks for: ``"bwrap"``, ``"none"``, or
    #: ``""`` for a manifest that never mentioned it.  Required to be
    #: ``"bwrap"`` the moment :attr:`allowed_tools` names a code-plane
    #: tool **this host would run** — see :meth:`code_plane_entries` for
    #: why a bridged one is the server's — and checked against the bus by
    #: :meth:`resolve`.  Unlike the
    #: fields above it is not content the platform owns — it is a
    #: statement about the host, which is why the harness is allowed to
    #: have an opinion about it.
    sandbox: str = ""
    source: Optional[Path] = None
    #: The names of the skills :func:`compose_manifests` folded into this
    #: one, in the order they were listed, primary first.  Empty for a
    #: manifest that came off one file, which is what keeps the
    #: single-skill path byte-identical to what it was before composition
    #: existed.  It is here so a caller can SAY which skills a run is
    #: under — the composed :attr:`name` is the primary's and names only
    #: one of them — rather than leave it to be worked out of the prompt.
    composed: Tuple[str, ...] = ()

    # ── loading ─────────────────────────────────────────────────────────

    @classmethod
    def load(cls, arg) -> "SkillManifest":
        """A path, **or the name of a mission pack this install ships**.

        ``Skill.load("analyst")`` — the call ``ROADMAP.md`` §2.6b names,
        and the one a platform embedding the library writes.  It is
        :func:`resolve_skill` under the name the façade exports the class
        as, so there is one resolver and not two; see that function for
        the order (a path that exists wins) and
        :func:`core.skills.library.packs` for what there is.

        :meth:`from_file` is the narrower door and stays exactly what it
        was: *this file, parsed*, with no library consulted.
        """
        return resolve_skill(arg)

    @classmethod
    def from_file(cls, path) -> "SkillManifest":
        """Load one manifest, or refuse naming every problem found."""
        p = Path(path).expanduser()
        if p.is_dir():
            p = _skill_file_in(p)
        if not p.is_file():
            raise SkillManifestError(f"No skill manifest at {p}")

        front, body = cls._split(p, p.read_text(encoding="utf-8"))
        return cls._build(p, front, body)

    @staticmethod
    def _split(path: Path, text: str) -> Tuple[Dict[str, Any], str]:
        """Frontmatter mapping and Markdown body, or a refusal."""
        stripped = text.lstrip("﻿")
        fences = list(_FENCE.finditer(stripped))
        if len(fences) < 2 or stripped[:stripped.find("\n") + 1].strip() != "---":
            raise SkillManifestError(
                f"{path.name} has no YAML frontmatter. A skill manifest opens "
                f"with a line of exactly `---`, closes the frontmatter with "
                f"another, and everything after it is the Markdown body."
            )
        raw = stripped[fences[0].end():fences[1].start()]
        body = stripped[fences[1].end():].strip()

        yaml = _require_yaml(path)
        try:
            front = yaml.safe_load(raw)
        except Exception as exc:  # noqa: BLE001 — the parser's own message
            raise SkillManifestError(
                f"{path.name} has unreadable frontmatter: {exc}"
            ) from exc
        if front is None:
            front = {}
        if not isinstance(front, Mapping):
            raise SkillManifestError(
                f"{path.name} frontmatter is a {type(front).__name__}; it is a "
                f"mapping of fields."
            )
        return dict(front), body

    @classmethod
    def _build(cls, path: Path, front: Dict[str, Any], body: str) -> "SkillManifest":
        block = front.get("skill")
        if block is not None and not isinstance(block, Mapping):
            raise SkillManifestError(
                f"{path.name} has a `skill:` key holding a "
                f"{type(block).__name__}; it is a mapping of the operational "
                f"fields, or absent for a flat manifest."
            )
        fields: Dict[str, Any] = dict(block or {})
        for key, value in front.items():
            fields.setdefault(key, value)
        fields.pop("skill", None)

        problems: List[str] = []

        name = str(fields.get("skill_id") or fields.get("name") or "").strip()
        if not name:
            problems.append(
                "no `name` and no `skill_id`; every refusal and every prompt "
                "header has to say which skill is loaded"
            )

        tools, optional, tool_problems = cls._read_tools(fields.get("allowed_tools"))
        problems.extend(tool_problems)

        grounding = fields.get("grounding")
        if grounding is not None and not isinstance(grounding, Mapping):
            problems.append(
                f"`grounding:` holds a {type(grounding).__name__}; it is a "
                f"mapping (identifier_pattern, ignore, ...) or absent"
            )
            grounding = None

        # The rule pack, validated ALL THE WAY DOWN at the door and stored
        # raw. Shape is this module's (it is a mapping, or it is not a
        # block); everything else is the kernel's, and `RulePack
        # .from_mapping` answers it by dry-running the whole pack through a
        # throwaway `CognitiveState` — the same trick the grounding merge
        # plays with `GroundingConfig.from_mapping`, and for a sharper
        # reason. A grounding block that does not compile costs a repair
        # turn; a rule pack the kernel refuses would be found at the first
        # derive of a mission that has already started, in the one module
        # whose whole promise is that it cannot cost a mission anything. So
        # a mission cannot START on a pack the kernel would refuse.
        #
        # Imported inside the function because `core.runtime.cognition`
        # imports `core.runtime.grounding`, and a manifest loader has no
        # business dragging the kernel in at import time.
        cognition = fields.get("cognition")
        if cognition is not None and not isinstance(cognition, Mapping):
            problems.append(
                f"`cognition:` holds a {type(cognition).__name__}; it is a "
                f"mapping (cardinality, rules, goals, constraints) or absent"
            )
            cognition = None
        elif cognition is not None:
            from core.runtime.cognition import RulePack

            try:
                RulePack.from_mapping(cognition)
            except ValueError as exc:
                # No space before `{exc}`: the pack's own faults arrive as
                # their own indented lines (`RulePack.PROBLEM_SEP`), nested
                # under this one item of the manifest's list. A separator
                # that a message can also contain is a list a reader cannot
                # take apart, which is what "; " was.
                problems.append(f"`cognition:` is not a usable rule "
                                f"pack:{exc}")

        # The plane's declarations, validated ALL THE WAY DOWN at the door
        # and stored raw, on the rule the rule pack above follows: shape is
        # this module's (it is a mapping, or it is not a block) and
        # everything else belongs to the reader, which answers it by
        # building the block.
        #
        # The door is the only moment these faults can be found. A rule pack
        # that does not load costs a run its cognition and says so; a
        # malformed identifier declaration costs NOTHING visible — it simply
        # binds nothing, silently, for as long as the file exists — which
        # makes the load-time refusal the whole of this block's safety.
        #
        # Imported inside the function for the reason `RulePack` is: a
        # manifest loader has no business dragging the runtime's plane
        # resolver in at import time.
        # `plane` and not `tools`: the local name above is the CLOSED SET,
        # and this block is what the plane returns. Two different facts, and
        # a shared name here once cost the loader every manifest it had.
        plane = fields.get("tools")
        if plane is not None and not isinstance(plane, Mapping):
            problems.append(
                f"`tools:` holds a {type(plane).__name__}; it is a mapping "
                f"(defaults, entries) or absent"
            )
            plane = None
        elif plane is not None:
            from core.runtime.declarations import ToolsBlock

            try:
                ToolsBlock.from_mapping(plane)
            except ValueError as exc:
                # No space before `{exc}`, as with the pack above: the
                # block's own faults arrive as their own indented lines
                # under this one item of the manifest's list.
                problems.append(f"`tools:` is not a usable declaration "
                                f"block:{exc}")

        # Refused rather than coerced. `sdk_import: [acme]` would render as
        # "import ['acme']" in a sentence handed to a model, and the model
        # would write that line.
        raw_sdk = fields.get("sdk_import")
        sdk_import = ""
        if raw_sdk is not None:
            if isinstance(raw_sdk, str) and raw_sdk.strip():
                sdk_import = raw_sdk.strip()
            else:
                problems.append(
                    f"`sdk_import:` holds a {type(raw_sdk).__name__}; it is "
                    f"the module name a step would `import` to reach this "
                    f"platform from code (sdk_import: acme), or absent"
                )

        # An operational field and not content: what it says is checked
        # against the bus in `resolve`, so an unknown value cannot be
        # rendered into the prompt and left to mean something later.
        raw_sandbox = fields.get("sandbox")
        sandbox = ""
        if raw_sandbox is not None:
            text = (raw_sandbox.strip().lower()
                    if isinstance(raw_sandbox, str) else "")
            if text in SANDBOX_VALUES:
                sandbox = text
            else:
                problems.append(
                    f"`sandbox:` holds {raw_sandbox!r}; it is "
                    f"{' or '.join(f'`{v}`' for v in SANDBOX_VALUES)} — "
                    f"`bwrap` asks for isolation and refuses the run if the "
                    f"bus is not under bwrap, `none` states that none was "
                    f"asked for and is itself refused for a closed set that "
                    f"names a code-plane tool"
                )

        if not body.strip() and not any(
            fields.get(key) for key, _label in _PROMPT_FIELDS
        ):
            problems.append(
                "there is nothing to tell the model: no Markdown body and none "
                "of the operational frontmatter fields "
                f"({', '.join(key for key, _ in _PROMPT_FIELDS)})"
            )

        if problems:
            raise SkillManifestError(
                f"{path} is not a usable skill manifest:\n  - "
                + "\n  - ".join(problems)
            )

        output = _render_value(fields.get(_OUTPUT_FIELD))
        return cls(
            name=name,
            description=_render_value(fields.get("description")),
            version=str(fields.get("version") or ""),
            allowed_tools=tuple(tools),
            optional_tools=frozenset(optional),
            prompt=cls._render_prompt(name, fields, body, output),
            output_contract=output,
            grounding=dict(grounding) if grounding is not None else None,
            cognition=dict(cognition) if cognition is not None else None,
            tools=dict(plane) if plane is not None else None,
            sdk_import=sdk_import,
            sandbox=sandbox,
            source=path,
        )

    @staticmethod
    def _read_tools(raw: Any) -> Tuple[List[str], List[str], List[str]]:
        """``(names in file order, the optional ones, problems)``."""
        if raw is None:
            return [], [], [
                "no `allowed_tools`; the closed set is the point of a manifest, "
                "and a mission without one is handed the whole bus"
            ]
        if isinstance(raw, str) or not isinstance(raw, Sequence):
            return [], [], [
                f"`allowed_tools` is a {type(raw).__name__}; it is a list of "
                f"tool names"
            ]

        problems: List[str] = []
        names: List[str] = []
        optional: List[str] = []
        for entry in raw:
            text = str(entry or "").strip()
            if not text:
                problems.append("`allowed_tools` has an empty entry")
                continue
            is_optional = text.endswith(_OPTIONAL)
            bare = text[:-1].strip() if is_optional else text
            if not bare:
                problems.append(f"`allowed_tools` entry {text!r} names no tool")
                continue
            if bare in names:
                problems.append(f"`allowed_tools` names {bare!r} twice")
                continue
            names.append(bare)
            if is_optional:
                optional.append(bare)

        if not names and not problems:
            problems.append(
                "`allowed_tools` is empty; a closed set of nothing is a mission "
                "that can only answer from memory"
            )
        return names, optional, problems

    @staticmethod
    def _render_prompt(
        name: str, fields: Dict[str, Any], body: str, output: str,
    ) -> str:
        parts: List[str] = [f"Skill: {name}"]
        description = _render_value(fields.get("description"))
        if description:
            parts.append(description)

        rendered = set(_STRUCTURAL) | {_OUTPUT_FIELD}
        for key, label in _PROMPT_FIELDS:
            rendered.add(key)
            value = _render_value(fields.get(key))
            if value:
                parts.append(f"{label}:\n{value}" if "\n" in value
                             else f"{label}: {value}")

        # Anything the manifest carries that this loader has never heard
        # of. A skill is content; deciding that an unrecognised field is
        # noise would be the harness overruling the platform on its own
        # operational knowledge.
        for key, raw in fields.items():
            if key in rendered:
                continue
            value = _render_value(raw)
            if value:
                label = key.replace("_", " ").capitalize()
                parts.append(f"{label}:\n{value}" if "\n" in value
                             else f"{label}: {value}")

        if body.strip():
            parts.append(body.strip())
        if output:
            parts.append(f"{_OUTPUT_LABEL}:\n{output}")
        return "\n\n".join(parts)

    def describe(self) -> str:
        """How a refusal names this manifest — and everything it composes.

        ``'analyst'`` for a manifest off one file, byte for byte what
        every refusal said before composition existed.  ``'analyst'
        (composed with 'research')`` for several, and the reason is that
        the closed set a refusal is ABOUT is the union: a tool missing
        for the third skill, reported under the first skill's name, sends
        an operator to open the wrong file and find nothing wrong with
        it.
        """
        rest = ", ".join(repr(name) for name in self.composed[1:])
        return f"{self.name!r} (composed with {rest})" if rest else repr(self.name)

    # ── the closed set, against what was discovered ─────────────────────

    def code_plane_entries(self) -> List[Tuple[str, str, Tuple[str, ...]]]:
        """``(entry as written, tool it is, scopes)`` for the code plane
        **this host would run**.

        Matched on :func:`~core.tools.descriptors.tool_key` EQUALITY and not
        on :func:`~core.tools.descriptors.same_tool`, and the difference is
        the whole rule: ``run_shell_command`` is this process's own
        descriptor and is gated; ``mcp.run_shell_command`` is a tool on a
        server, reached through the bridge, and is not.

        **This reverses what 0.9.0's lane L decided**, which was that "a
        code plane reached through a bridge is still a code plane".  It
        sounds right and it is not, because of what the gate actually asks
        for.  The gate demands ``sandbox: bwrap``, and bwrap is a wrapper
        this bus puts around a subprocess *it* spawns.  A bridged tool
        spawns nothing here: the mission sends ``tools/call`` and a shell
        runs on the far end, inside whatever that server does or does not
        isolate it with.  Demanding bwrap on this host for that call
        isolates nothing about it — it makes a manifest declare an untruth
        about where the code runs, and it made the in-repo eval suite
        refuse to load on a host without bubblewrap for a mission whose
        shell was a stub server's Python function.  A rule that cannot be
        satisfied honestly is a rule people satisfy dishonestly.

        What replaces it is a boundary rather than a hole.  A bridged shell
        is governed where it executes: by the server, by the capability the
        bridge asks for (``mcp.call``), by the mission's closed set, and by
        ``--gate-tool`` if a deployment wants a person in front of it.  A
        platform that bridges a shell owns the isolation on the server side
        — ``PLATFORMS.md`` says so in as many words — and this harness must
        not claim to have provided it.

        **Optional entries count**, unchanged.  A ``run_shell_command?``
        this host does not offer today is still a manifest that permits
        running shell commands here, and whether the gate applies must not
        depend on what a server happened to advertise this morning.
        """
        catalogue = code_plane_tools()
        found: List[Tuple[str, str, Tuple[str, ...]]] = []
        for entry in self.allowed_tools:
            for tool, scopes in catalogue.items():
                if tool_key(entry) == tool_key(tool):
                    found.append((entry, tool, scopes))
                    break
        return found

    def bridged_code_plane_entries(self) -> List[Tuple[str, str]]:
        """``(entry, local tool it shares a name with)`` for the ones the
        gate deliberately lets past.

        Not used to refuse anything — it exists so a caller can SAY that a
        manifest bridges a shell rather than leave it to be discovered in a
        transcript, and so the fact has one owner rather than a ``.``-count
        written wherever somebody needed it.  See
        :meth:`code_plane_entries` for why these are not gated here.
        """
        catalogue = code_plane_tools()
        found: List[Tuple[str, str]] = []
        for entry in self.allowed_tools:
            for tool in catalogue:
                if (tool_key(entry) != tool_key(tool)
                        and same_tool(entry, tool)):
                    found.append((entry, tool))
                    break
        return found

    def _sandbox_problems(self, sandbox: Optional[str]) -> List[str]:
        """Both halves of the code-plane gate, as refusal lines.

        The declaration half is static — it reads the manifest and
        nothing else, so a manifest is safe or unsafe on its own terms.
        The isolation half needs the bus, and is skipped when the caller
        did not say which sandbox is running (``sandbox`` empty or
        ``None``): a library caller that holds no bus is told nothing
        rather than told the wrong thing.
        """
        problems: List[str] = []
        code_plane = self.code_plane_entries()
        if code_plane and self.sandbox != BWRAP:
            declared = (f"declares `sandbox: {self.sandbox}`" if self.sandbox
                        else "declares no `sandbox:`")
            for entry, tool, scopes in code_plane:
                problems.append(
                    f"{entry!r} runs code the model composed ON THIS HOST "
                    f"({tool}, {'/'.join(scopes)}) and this manifest "
                    f"{declared}; add `sandbox: bwrap` to the frontmatter, "
                    f"or take the tool out of `allowed_tools`. A governed "
                    f"mission that can run arbitrary code on the host "
                    f"without isolation is not a governed mission. If you "
                    f"meant a SERVER's tool of that name, write it with its "
                    f"namespace (`mcp.{tool}`): that one executes on the "
                    f"server, is governed there, and this host's sandbox "
                    f"would isolate nothing about it"
                )
        if self.sandbox == BWRAP and sandbox and sandbox != BWRAP:
            problems.append(
                f"this manifest declares `sandbox: bwrap` and the tool bus is "
                f"running {sandbox!r}; the isolation it asked for is not "
                f"there. Install bwrap, or stop opting out of the sandbox, "
                f"before running this skill — a manifest that asked for "
                f"isolation and did not get it must not be left to find that "
                f"out in the transcript"
            )
        return problems

    def resolve(
        self, available: Sequence[str], *, sandbox: Optional[str] = None,
    ) -> List[str]:
        """The closed set as *bus* names, or refuse naming every gap.

        ``sandbox`` is what the bus about to run this mission is
        isolating with — :func:`sandbox_name` off a ``ToolBus``.  It is a
        keyword and it defaults to unstated, so every existing caller
        keeps working and only the runtime half of the code-plane gate
        goes unchecked for them; the declaration half is read off the
        manifest and always runs.

        A manifest names a tool the way the server advertises it
        (``catalog_search_assets``); the bridge registers it namespaced
        (``mcp.catalog_search_assets``) so a discovered server cannot
        shadow ``fs``.  Matching therefore accepts an exact name or a
        namespaced one, and an entry that matches two namespaces is a
        problem rather than a coin flip.

        The comparison is :func:`~core.tools.descriptors.tool_key`, the
        harness's one answer to *"are these the same tool"* — the same one
        ``MissionRunner._near_miss`` and the grounding ignore rule use.  It
        reduces on separators rather than on a list of known prefixes, so
        a manifest written in **any** convention resolves, including one
        nobody has invented yet.  That is half the fix for the three
        spellings measured on 10 August 2026: an author writes one, and
        every other surface derives it.

        Returns names in manifest order — the order a skill author chose
        is the order the catalogue is read in.
        """
        offered = list(available)
        resolved: List[str] = []
        problems: List[str] = []
        # Gathered before the loop and raised with it, so that an
        # operator fixing a manifest sees the unsafe tool and the missing
        # tool in one message and edits the file once. A refusal that
        # arrives one problem at a time is fixed one problem at a time.
        unsafe = self._sandbox_problems(sandbox)

        for wanted in self.allowed_tools:
            matches = [name for name in offered if same_tool(name, wanted)]
            if len(matches) == 1:
                resolved.append(matches[0])
            elif len(matches) > 1:
                problems.append(
                    f"{wanted!r} matches {len(matches)} discovered tools "
                    f"({', '.join(sorted(matches))}); name it with its "
                    f"namespace so the mission calls the intended one"
                )
            elif wanted not in self.optional_tools:
                problems.append(
                    f"{wanted!r} is in the closed set and was not discovered"
                )

        if unsafe or problems:
            message = (
                f"skill {self.describe()} cannot run against this server:\n  - "
                + "\n  - ".join(unsafe + problems)
            )
            # The discovered list and the sentence about narrowing answer
            # a missing *tool*. Appended to a refusal that is only about
            # isolation they would answer a question nobody asked, and
            # point the reader at the closed set instead of at bwrap.
            if problems:
                message += (
                    "\n\nDiscovered: "
                    + (", ".join(offered) or "(nothing)")
                    + "\n\nThe closed set is not narrowed to whatever happens "
                      "to be present: a mission missing the tool that answers "
                      "its question will answer it from the model's memory "
                      "instead, and the transcript will look ordinary."
                )
            raise SkillToolsUnavailable(message)
        if not resolved:
            raise SkillToolsUnavailable(
                f"skill {self.describe()} resolved to no tools at all: every entry "
                f"in its closed set is optional and none was discovered. "
                f"Discovered: " + (", ".join(offered) or "(nothing)")
            )
        return resolved

    def admits(self, names: Sequence[str],
               offered: Sequence[str] = ()) -> List[str]:
        """Which of *names* this closed set lets a RUNNING mission add.

        The other half of :meth:`resolve`, and the half a mid-run change
        needs.  ``resolve`` answers "what may this mission start with",
        once, against what the server advertised at the door; this answers
        "the bus just grew these — may any of them join", every time the
        plane moves under a run.  :class:`~core.runtime.mission
        .MissionRunner` asks; it never decides, because the closed set is
        the manifest's and a loop that widened its own set would not be
        operating under one.

        *offered* is what the mission already has, and it is not merely a
        de-duplication.  An entry that has already bound a tool is SPENT:
        a manifest naming ``echo`` asked for the plane's ``echo``, and a
        server that later registers ``other.echo`` must not slide a second
        tool in through the same entry.  So an entry matched by something
        already offered admits nothing further.

        Optional (``?``) entries are the ordinary case here and need no
        special handling: the marker is stripped at load, and an entry the
        server had not advertised at the door is exactly the entry a late
        arrival fills.

        Matching is :func:`~core.tools.descriptors.same_tool`, as in
        ``resolve``: a manifest writes one spelling and every surface
        derives the rest.
        """
        spent = {entry for entry in self.allowed_tools
                 if any(same_tool(name, entry) for name in offered)}
        free = [entry for entry in self.allowed_tools if entry not in spent]
        return [str(name) for name in names
                if any(same_tool(name, entry) for entry in free)]


def _skill_file_in(directory: Path) -> Path:
    """``<dir>/SKILL.md``, or a refusal listing the skills underneath it."""
    direct = directory / "SKILL.md"
    if direct.is_file():
        return direct
    found = sorted(p.parent.name for p in directory.glob("*/SKILL.md"))
    if found:
        raise SkillManifestError(
            f"{directory} holds {len(found)} skills and no SKILL.md of its "
            f"own; name the one to load: "
            + ", ".join(f"{directory.name}/{n}" for n in found)
        )
    raise SkillManifestError(
        f"{directory} has no SKILL.md and no <name>/SKILL.md under it"
    )


def load_skill(path) -> SkillManifest:
    """Load one manifest from a file or a directory holding ``SKILL.md``."""
    return SkillManifest.from_file(path)


def resolve_skill(arg) -> SkillManifest:
    """A ``--skill`` argument as a manifest: **a path, or a pack's name**.

    The one entry point a command line should use, and the only thing in
    this module that knows first-party packs exist.  ``load_skill`` stays
    what it always was — *this file, parsed* — and
    :func:`core.skills.library.resolve` owns the other half: which packs
    are installed, and what a pack directory is made of.  Two questions,
    two owners, one door.

    A path that exists wins, so every command line that worked before
    packs existed works unchanged; only when nothing is at that path is
    the argument read as the name of a pack this install ships.  Neither
    is a :class:`SkillManifestError` — the same exception ``load_skill``
    already raises and every caller already refuses on — naming both roads
    out and listing the packs there are.

    Imported inside the function on purpose: :mod:`core.skills.library`
    imports this module, and the dependency has to point one way.
    """
    from core.skills.library import resolve as _resolve_pack

    return _resolve_pack(arg)


#: ``grounding:`` keys merged as a first-seen-order union of literals.
#: Both are lists of content a skill wrote down, and two skills that each
#: know a placeholder to ignore both still know it.
_GROUNDING_LISTS: Tuple[str, ...] = ("ignore", "figures_from")

#: ``grounding:`` keys merged with OR.  Checking asked for by ANY skill
#: binds the composed run: a skill that asked for a claim table asked
#: because its own answers are not worth much without one, and being
#: composed with a laxer skill is not a reason to stop asking.
_GROUNDING_FLAGS: Tuple[str, ...] = ("claim_table", "reading", "critic")

#: ``grounding:`` keys that are one value for the whole run.  Absent
#: yields to declared; declared twice has to AGREE, because there is no
#: honest way to choose between two identifier grammars — the merge
#: cannot know which of them the answer will be written in, and taking
#: the first would switch a check off for the other skill's identifiers
#: while the report went on saying the check ran.
_GROUNDING_SCALARS: Tuple[str, ...] = (
    "identifier_pattern", "number_pattern", "max_repairs",
)


def _canonical(value: Any) -> Any:
    """A ``grounding:`` value reduced to something two skills compare on.

    YAML hands back plain mappings, lists and scalars, and one plane
    written in two YAML styles is one declaration.  Only the container
    shapes are normalised — the content is left exactly as written,
    because deciding that two *different* tool lists were meant to be the
    same is not this function's call to make.
    """
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def _declared(manifests: Sequence["SkillManifest"], key: str) -> bool:
    """Whether ANY of *manifests* wrote *key* into its ``grounding:`` block.

    THE SHAPE RULE, and the one line that enforces it: **composition may
    change a value, never a declared key's presence.**  A key that one
    skill wrote is in the merged mapping, whatever the merge did to what
    it says.

    Presence is not decoration, and the reference deployment found out
    how: every skill in a family declared ``must_cite: {}`` — an empty
    floor, deliberately — and the merge dropped the key because the union
    of nothing is nothing.  One skill returned the manifest unchanged and
    ``"must_cite" in grounding`` was True; two skills composed and it was
    False.  A consumer that switches on key presence turns its check off
    the moment a second skill is added to the line, and nothing anywhere
    says so.

    ``key in m.grounding`` and not ``m.grounding.get(key)``: the whole
    point is to tell *declared and empty* from *never mentioned*, which
    is the distinction ``get`` throws away.
    """
    return _declares([m.grounding for m in manifests], key)


def _declares(blocks: Sequence[Mapping], key: str) -> bool:
    """:func:`_declared`'s rule, over the blocks themselves.

    One owner for *composition may change a value, never a declared key's
    presence*, because there are now two blocks it has to be true of —
    ``grounding:`` and ``cognition:`` — and a second spelling of it is the
    second place it silently stops being true.
    """
    return any(key in block for block in blocks)


def _same_plane(one: Any, other: Any) -> bool:
    """Whether two ``planes:`` bodies declare the SAME plane.

    Not equality of what was typed.  A skill family legitimately restates
    the plane its members share, and two authors — or one author on two
    days — write the tools in a different order and in a different
    naming convention.  Comparing the text would refuse a composition
    over a difference that is not one, and that refusal has no fix short
    of editing somebody else's manifest to match your typing.

    So membership is compared, on the identities the rest of the
    framework already uses: tools by
    :func:`~core.tools.descriptors.tool_key`, so ``catalog.search`` and
    ``mcp_catalog_search`` are the one tool they are everywhere else,
    **with the trailing ``*`` kept out of the reduction and carried as a
    flag of its own**, and claims by casefolded text, because
    :class:`~core.runtime.grounding.PlaneClaimCheck` matches them
    case-insensitively and two spellings it cannot tell apart are not two
    declarations.  Genuinely different membership is still the refusal it
    was: one plane name over two tool sets is two planes wearing one word.

    The ``*`` is why the reduction is not simply ``tool_key``.
    ``tool_key("catalog_*")`` and ``tool_key("catalog")`` are the same
    string, and to
    :func:`~core.runtime.grounding.plane_matches` they are nothing like
    the same thing: ``catalog_*`` is every catalogue tool a server
    advertises and ``catalog`` is one tool called ``catalog``.  Folding
    them together let ``{tools: [catalog_*]}`` and ``{tools: [catalog]}``
    compose without a word, and then LISTING ORDER decided whether
    ``catalog_search_assets`` was on the plane — the same
    order-dependence the code-plane gate had, one field over.  So a spec
    reduces to ``(key, is_family)`` and a family is not a single tool.

    The bodies are read through
    :meth:`~core.runtime.grounding.GroundingConfig._read_planes` rather
    than picked apart here, so the plane schema keeps one owner.  A body
    that reader cannot make a plane of falls back to comparing the raw
    text — it belongs to a skill that is being refused on its own terms
    anyway, and guessing about it here would only add a second reason.
    """
    from core.runtime.grounding import GroundingConfig

    def read(body: Any):
        planes, _problems = GroundingConfig._read_planes({"plane": body})
        return planes[0] if planes else None

    def spec(name: Any) -> Tuple[str, bool]:
        text = str(name).strip()
        return (tool_key(text.rstrip("*")), text.endswith("*"))

    left, right = read(one), read(other)
    if left is None or right is None:
        return _canonical(one) == _canonical(other)
    return (frozenset(spec(name) for name in left.tools)
            == frozenset(spec(name) for name in right.tools)
            and frozenset(claim.casefold() for claim in left.claims)
            == frozenset(claim.casefold() for claim in right.claims))


def _prompt_without_output_contract(manifest: "SkillManifest") -> str:
    """*manifest*'s prompt with its answer shape taken back off.

    A mission has ONE answer shape.  A supporting skill's operational
    knowledge is worth having and its ``output_format`` is not: two
    output contracts in one system message is a model choosing between
    them, and the one it chooses is not necessarily the one the primary
    skill's grounding block is written against.

    Removed by the exact suffix :meth:`SkillManifest._render_prompt`
    wrote, and a prompt that does not end in it is returned untouched: a
    manifest assembled by hand may carry a prompt this module never
    rendered, and truncating that one on a guess is worse than leaving a
    sentence in.

    Known edge, and left alone deliberately: a skill whose Markdown BODY
    writes out its own ``Output format:`` paragraph keeps that paragraph
    in the composition.  It is prose the author wrote into the body, the
    suffix this function removes is the one the renderer appended, and a
    function that went looking for the label anywhere in the text would
    start deleting a supporting skill's explanation of its own reporting
    conventions.  The way to have a stripped answer shape is to put it in
    ``output_format:``, which is what the field is.
    """
    contract = manifest.output_contract
    if not contract:
        return manifest.prompt
    tail = f"\n\n{_OUTPUT_LABEL}:\n{contract}"
    if manifest.prompt.endswith(tail):
        return manifest.prompt[:-len(tail)]
    return manifest.prompt


def _merge_grounding(
    manifests: Sequence["SkillManifest"], problems: List[str],
) -> Optional[Dict[str, Any]]:
    """One ``grounding:`` mapping out of several, appending every problem.

    Raw mappings in, a raw mapping out.  The merge deliberately does not
    build a :class:`~core.runtime.grounding.GroundingConfig` and take it
    apart again, because that class is the *reader* of this block and a
    merge going through it would be a second reader of the same fact.
    What the caller does with the result is hand it straight back to
    :meth:`~core.runtime.grounding.GroundingConfig.from_mapping`, so a
    merge that produced something unusable refuses at the door rather
    than at the end of an 11,000-second mission.

    Each skill's own block is validated first and one that does not stand
    up alone is left out with its own reason named.  Merging an
    unreadable block would produce a second, stranger complaint about a
    mapping nobody wrote.

    **Strictness only ever goes up.**  The bools OR.  A ``must_cite``
    wildcard is a floor and a named check may not dig under it *across
    skills*: ``must_cite: true`` in the primary composed with
    ``must_cite: {figures: 0}`` in a supporting skill comes out with
    ``figures`` at the wildcard's minimum, not at zero, because
    :meth:`~core.runtime.grounding.GroundingConfig.minimum_for` lets an
    explicit name beat the wildcard and nobody wrote both sentences.
    Inside ONE block that exemption is deliberate and is left alone.

    **Composition may change a value; it may never change a declared
    key's presence.**  Every key any input wrote is in the mapping that
    comes out, even when the merge left it empty — ``must_cite`` as
    ``{}``, ``ignore`` and ``figures_from`` as ``[]``, ``planes`` as
    ``{}``, a bool as ``false``, a scalar as the ``null`` somebody typed.
    See :func:`_declared` for what that costs when it is not true.  The
    keys are :data:`~core.runtime.grounding.GROUNDING_KEYS`, which this
    function owes a merge rule to every one of.
    """
    from core.runtime.grounding import ANY_CHECK, GroundingConfig

    declared = [m for m in manifests if m.grounding is not None]
    if not declared:
        return None

    usable: List["SkillManifest"] = []
    for manifest in declared:
        try:
            GroundingConfig.from_mapping(manifest.grounding)
        except ValueError as exc:
            problems.append(
                f"skill {manifest.name!r} has a `grounding:` block that is "
                f"not usable on its own, so there is nothing to merge: {exc}"
            )
            continue
        usable.append(manifest)
    if not usable:
        return None

    merged: Dict[str, Any] = {}

    for key in _GROUNDING_LISTS:
        union: List[str] = []
        for manifest in usable:
            for item in (manifest.grounding.get(key) or ()):
                text = str(item)
                if text not in union:
                    union.append(text)
        if _declared(usable, key):
            merged[key] = union

    for key in _GROUNDING_FLAGS:
        # Emitted whenever anybody DECLARED it, at the OR of what they
        # said — not only when the OR came out true. A skill whose whole
        # block is `claim_table: false` has declared a grounding block,
        # and dropping its one false key left the merged mapping empty,
        # which `merged or None` then turned into *no grounding grammar
        # at all*: the run lost its validator and the console line said
        # so, over a composition where nobody asked for anything to
        # change. A declaration that survives as `false` is the same
        # validator the single-skill path builds.
        if _declared(usable, key):
            merged[key] = any(bool(m.grounding.get(key, False))
                              for m in usable)

    for key in _GROUNDING_SCALARS:
        # An explicit `identifier_pattern: null` is a DECLARATION carrying
        # no opinion, and the two halves of that are handled separately:
        # it is not compared (a null cannot disagree with a grammar, and
        # refusing over one would refuse a composition over nothing), and
        # it is not dropped either, because it was written down.
        stated = [(m.name, m.grounding[key]) for m in usable
                  if m.grounding.get(key) is not None]
        if not stated:
            if _declared(usable, key):
                merged[key] = next(m.grounding[key] for m in usable
                                   if key in m.grounding)
            continue
        if any(value != stated[0][1] for _name, value in stated):
            problems.append(
                f"`grounding: {key}` is declared by more than one skill and "
                f"they disagree — "
                + "; ".join(f"{name!r} says {value!r}"
                            for name, value in stated)
                + f". A composed mission has one {key}, and choosing between "
                  f"two would switch the check off for whichever skill lost "
                  f"while the report went on saying it ran. Make them agree, "
                  f"or do not compose these skills"
            )
            continue
        merged[key] = stated[0][1]

    # `must_cite:` has three spellings and one meaning, and
    # `_read_must_cite` is the owner of that reduction — so the merge
    # compares what IT says rather than the spelling a skill happened to
    # use. Identity is the check NAME, the thing two skills can both
    # name; the content is the minimum count.
    minimums: Dict[str, Tuple[str, int]] = {}
    #: Every skill that declared each check, not merely the first — the
    #: exemption rule below is about WHO asked, and "the first namer" is
    #: an answer that changes when the arguments are swapped.
    declarers: Dict[str, set] = {}
    order: List[str] = []
    for manifest in usable:
        pairs, _problems = GroundingConfig._read_must_cite(
            manifest.grounding.get("must_cite"))
        for check, minimum in pairs:
            declarers.setdefault(check, set()).add(manifest.name)
            if check not in minimums:
                minimums[check] = (manifest.name, minimum)
                order.append(check)
            elif minimums[check][1] != minimum:
                owner, first = minimums[check]
                problems.append(
                    f"`grounding: must_cite` asks for {check!r} twice over "
                    f"with different counts: {owner!r} says {first} and "
                    f"{manifest.name!r} says {minimum}. One answer cannot "
                    f"have two different floors for one kind of thing"
                )
    if _declared(usable, "must_cite"):
        # The wildcard is a FLOOR, and composition must not let a named
        # check dig under it. `minimum_for` lets an explicit name beat
        # `must_cite: true` — which is right inside one skill, where the
        # author who wrote both sentences meant the exemption — and wrong
        # across two, where nobody wrote both: a primary asking for
        # citations generally, composed with a supporting skill that
        # exempts figures for its own reasons, would come out citing
        # fewer things than the primary asked for and nothing would say
        # so. Raised rather than refused, on the same principle as the
        # bools: strictness asked for by any skill binds the run.
        #
        # An exemption survives only when EVERY skill that set the floor
        # also wrote it. That is the whole rule and it is deliberately
        # about the declarer SET rather than about who happened to say a
        # thing first. Scoping it to the first namer looked equivalent
        # and was order-dependent: `{"*": 1, figures: 0}` composed with a
        # bare `must_cite: true` gave figures a floor of 0 or of 1
        # depending on which was typed first, and in the 0 direction the
        # skill that asked for citations generally lost its floor to an
        # exemption it had never written. A set is the same answer both
        # ways round.
        #
        # `{"*": 1, figures: 0}` alone keeps its 0 — one author saying
        # "cite generally, except this kind, which my answers legitimately
        # omit", which is a sentence somebody did write. So does the same
        # block composed with a skill that ALSO writes `figures: 0`: two
        # authors agreeing is agreement.
        #
        # `order` empty is the declared-but-empty case — `must_cite: {}`
        # or `must_cite: false`, both of which reduce to no pairs. It
        # comes out as `{}`: the key a skill wrote is still there, and
        # `_read_must_cite` reads `{}` back to the same no-floor it read
        # the original to. The value may change; the presence may not.
        floor = minimums.get(ANY_CHECK, ("", 0))[1]
        wildcard_declarers = declarers.get(ANY_CHECK, set())
        merged["must_cite"] = {
            check: (minimums[check][1]
                    if check == ANY_CHECK
                    or wildcard_declarers <= declarers[check]
                    else max(minimums[check][1], floor))
            for check in order
        }

    # A plane NAME is what a report says and what a claim phrase is
    # recognised under, so two skills declaring one name over different
    # tools have declared two planes and given them one word. Refused
    # naming both, rather than one of them quietly winning.
    planes: Dict[str, Any] = {}
    plane_owner: Dict[str, str] = {}
    for manifest in usable:
        for name, body in (manifest.grounding.get("planes") or {}).items():
            key = str(name).strip()
            if key not in planes:
                planes[key] = body
                plane_owner[key] = manifest.name
            elif not _same_plane(planes[key], body):
                problems.append(
                    f"`grounding: planes: {key}` is declared by both "
                    f"{plane_owner[key]!r} and {manifest.name!r}, over "
                    f"different tools or claims. One plane name is one "
                    f"plane: rename one of them, or make the two "
                    f"declarations identical"
                )
    if _declared(usable, "planes"):
        merged["planes"] = planes

    # `merged` and not `merged or None`. Reaching here means at least one
    # skill declared a usable block, and *a block was declared* is the
    # fact the return value carries: `from_mapping({})` builds a validator
    # with no opinion, exactly as it does for a manifest that wrote
    # `grounding: {}`, while `None` says nobody asked for checking. Those
    # are different answers and composition must not swap one for the
    # other. `None` is returned above, where it is true.
    return merged


def _merge_cognition(
    manifests: Sequence["SkillManifest"], problems: List[str],
) -> Optional[Dict[str, Any]]:
    """One ``cognition:`` mapping out of several, appending every problem.

    :func:`_merge_grounding`'s shape exactly — raw mappings in, a raw
    mapping out, each input validated on its own first, every key any input
    declared present in the result — and for its reason: the reader of this
    block is :class:`core.runtime.cognition.RulePack`, and a merge that went
    through it and took it apart again would be a second reader of one fact.

    The four keys, and the two disciplines they follow:

    * **``rules:``, ``goals:`` and ``constraints:`` union by name.**  A pack
      is a set of named clauses; two skills that each bring their own bring
      both.  A
      name declared twice with *different* content is refused naming both
      skills, for the reason one plane name over two tool sets is: a name
      is what a refusal, a log line and the next author's grep say, and
      letting the first (or the last) win makes which clause a mission runs
      under a fact about argument order.  An identical redeclaration is a
      family restating the clause it shares, and is deduplicated in
      silence — compared on :func:`_canonical`, so YAML style is not
      content.  A constraint's content is its whole declaration — what it
      quantifies over and the expression, in whichever of the two keys
      carries it — so the same arithmetic under one name composes, and
      ``require:`` in one skill against ``require_z3:`` in another under one
      name is the collision it looks like.
    * **``cardinality:`` agrees or refuses, per field.**  It is the scalar
      discipline (``identifier_pattern``'s), one field at a time: a field
      is single-valued or it is not, the kernel refuses to hold both
      answers about one field anyway, and choosing between two would switch
      collision detection off for whichever skill lost while the store went
      on reporting no disagreement.  Silence yields — a skill that never
      mentioned a field has no opinion about it.

    Strictness does not "only go up" here and could not: cognition gates
    nothing, so there is no strictness to raise.  What replaces it is
    *nobody's clause is dropped and nobody's clause is replaced*.
    """
    from core.runtime.cognition import RulePack

    declared = [m for m in manifests if m.cognition is not None]
    if not declared:
        return None

    usable: List["SkillManifest"] = []
    for manifest in declared:
        try:
            RulePack.from_mapping(manifest.cognition)
        except ValueError as exc:
            problems.append(
                f"skill {manifest.name!r} has a `cognition:` block that is "
                f"not usable on its own, so there is nothing to merge:{exc}"
            )
            continue
        usable.append(manifest)
    if not usable:
        return None

    blocks = [m.cognition for m in usable]
    merged: Dict[str, Any] = {}

    cardinality: Dict[str, Any] = {}
    owner: Dict[str, str] = {}
    for manifest in usable:
        for field, value in (manifest.cognition.get("cardinality") or {}).items():
            key = str(field).strip()
            if key not in cardinality:
                cardinality[key] = value
                owner[key] = manifest.name
            elif _canonical(cardinality[key]) != _canonical(value):
                problems.append(
                    f"`cognition: cardinality: {key}` is declared by both "
                    f"{owner[key]!r} ({cardinality[key]!r}) and "
                    f"{manifest.name!r} ({value!r}). A field carries one "
                    f"value or many for the whole store, and taking either "
                    f"answer would leave the other skill's rules measured "
                    f"against a collision check it did not ask for"
                )
    if _declares(blocks, "cardinality"):
        merged["cardinality"] = cardinality

    for key, identity, noun in (("rules", ("head", "body"), "clause"),
                                ("goals", ("pattern",), "target"),
                                ("constraints",
                                 ("over", "require", "require_z3"),
                                 "constraint")):
        entries: Dict[str, Any] = {}
        wrote: Dict[str, str] = {}
        for manifest in usable:
            for entry in (manifest.cognition.get(key) or ()):
                if not isinstance(entry, Mapping):
                    continue    # its own block refused it; do not say so twice
                name = str(entry.get("name") or "").strip()
                if not name:
                    continue
                content = tuple(_canonical(entry.get(part))
                                for part in identity)
                if name not in entries:
                    entries[name] = (dict(entry), content)
                    wrote[name] = manifest.name
                elif entries[name][1] != content:
                    problems.append(
                        f"`cognition: {key}` declares {name!r} twice over "
                        f"with different content: {wrote[name]!r} and "
                        f"{manifest.name!r} do not agree. One name is one "
                        f"{noun}: rename "
                        f"one of them, or make the two declarations identical"
                    )
        if _declares(blocks, key):
            merged[key] = [entry for entry, _content in entries.values()]

    # Validated HERE, for `_merge_grounding`'s reason: the merged mapping is
    # a block no skill wrote, and the door is where a mission finds out that
    # it does not stand up. What it can find is what the reader and the dry
    # run find — a merged `rules` list the reader will not take, a clause or
    # a cardinality the kernel refuses — asked of the COMPOSITION rather
    # than of any one input.
    #
    # And what it finds today is nothing, which is worth writing down rather
    # than leaving to be discovered: every rule above either carries a value
    # out of a block that already stood up on its own, or records a problem
    # and keeps the first, so the merged mapping is made of validated parts.
    # The guard is kept because a merge rule added later could compose
    # content no skill wrote, and it costs one dry run over three lists.
    #
    # It must not be mistaken for a check on cross-skill DERIVATION. One
    # skill's rule concluding a value that collides with another skill's
    # `cardinality: one` composes cleanly here and should: nothing derives
    # at load — there are no propositions yet — so there is nothing to
    # collide with. That belongs to the run, and it is the owner's rule
    # that it does: a contradiction is a thing to SURFACE, so the store
    # records both sides, contests the claim and shows it in the view. A
    # door that refused the composition would be refusing it over an
    # argument the receipts may never make.
    try:
        RulePack.from_mapping(merged)
    except ValueError as exc:
        problems.append(
            f"the merged `cognition:` block is not one the kernel would "
            f"take:{exc}"
        )
    return merged


def _tool_groups(names: Sequence[str]) -> Dict[str, str]:
    """``{name as written: the one spelling that stands for all of them}``.

    Two skills naming one tool in two conventions declare it once, and the
    relation that says so is :func:`~core.tools.descriptors.same_tool` —
    which is deliberately **not** an equivalence: ``runs_get`` matches both
    ``mcp.runs_get`` and ``mcp2.runs_get`` and those two do not match each
    other.  A grouping built by scanning the entries in arrival order
    therefore partitions such a family differently depending on which skill
    was listed first, and the merged block would carry the order of a
    command line into a run's reasoning log.

    So the scan runs over the SET of declared names in one fixed order —
    by :func:`~core.tools.descriptors.tool_key`, then by the name — and the
    spelling that stands for a group is the first of its members in that
    same order.  The result is a function of which names were declared and
    of nothing else.

    **A group POOLS, and two of its members need not match each other.**
    The scan joins a name to the group of the first *seen* name it matches,
    so a family joined through a common member ends up in one group:
    ``alpha.runs_get``, ``runs_get`` and ``zeta.runs_get`` are one group
    named ``alpha.runs_get``, although the two namespaced spellings are
    different tools to :func:`~core.tools.descriptors.same_tool` and to
    every lookup built on it.  That is the transitive closure of a relation
    that is not transitive, and it is the honest reading of a *manifest*:
    somebody who declared the bare name meant it to cover what they also
    declared under a namespace, and a merge is the one moment all three
    spellings are in hand.

    What it costs is worth writing down, because it is not visible from the
    call site: **the kept spelling may be unreachable by some of its own
    members.**  A run offering ``zeta.runs_get`` and nothing else looks the
    merged block up by that name, and
    :meth:`core.runtime.declarations.ToolsBlock.entry_for` matches on
    ``same_tool`` against the kept ``alpha.runs_get``, which does not match
    — so declarations that were pooled into that entry bind nothing for it.
    The alternative (a group per matching pair) is not a partition at all,
    and the one after that (keep every spelling separately) puts argument
    order back into the record.  A platform that hits it has declared one
    tool under two namespaces plus its bare name, and the answer is to name
    the tool as the run offers it — which is what PLATFORMS.md says.
    """
    ordered = sorted({str(name) for name in names},
                     key=lambda name: (tool_key(name), name))
    groups: Dict[str, str] = {}
    for name in ordered:
        groups[name] = next((groups[seen] for seen in ordered
                             if seen in groups and same_tool(seen, name)),
                            name)
    return groups


def _merge_tools(
    manifests: Sequence["SkillManifest"], problems: List[str],
) -> Optional[Dict[str, Any]]:
    """One ``tools:`` block out of several, appending every problem.

    :func:`_merge_cognition`'s shape exactly — raw mappings in, a raw
    mapping out, each input validated on its own first, a key any input
    declared present in the result — and for its reason: the reader of this
    block is :class:`core.runtime.declarations.ToolsBlock`, and a merge that
    went through it and took it apart again would be a second reader of one
    fact.

    The disciplines, per verb, and they are the scalar one
    (``identifier_pattern``'s) wherever two skills can mean different
    things by one word:

    * **entries union by tool**, on
      :func:`~core.tools.descriptors.same_tool` — this framework's one
      answer to *are these the same tool* — so two skills naming one tool
      in two conventions declare it once.  The grouping and the kept
      spelling both come out of :func:`_tool_groups`, which sorts before it
      scans: nothing binds differently either way (every lookup matches on
      ``same_tool`` too), but this block is written into a run's reasoning
      log, and a partition or a name that depended on which skill was typed
      first would put argument order into a record;
    * **``identifiers`` agree or refuse, per key.**  Two kinds for one key
      is a refusal naming both skills: a key identifies a job or it
      identifies an asset, the resolver would link the same value into two
      different subjects, and choosing between them would be a fact about
      argument order;
    * **``establishes`` unions.**  A list of what a call can answer cannot
      disagree with another list of what it can answer;
    * **``produces`` unions by ``(kind, field)``**, and two declarations of
      one product arriving through different calls is a refusal — that is
      the scalar discipline again, one product at a time;
    * **``output_schema`` agrees or refuses.**  It is a fallback shape for a
      server that publishes none, and two of them is two answers to a
      question the wire is meant to answer anyway;
    * **``defaults`` merge exactly as ``identifiers`` do.**

    The result is **order-independent**: the kept spellings, the entry
    order, the keys, the fields and the products are all chosen by sorting
    rather than by arrival, so composing the same skills in the other order
    is the same block, to the byte.  Not decoration — a plane's declarations are written
    into ``reasoning.jsonl`` and read back by a resumed run, and a block
    that depended on the order a command line listed two skills in would
    make that record a fact about typing.
    """
    from core.runtime.declarations import (ESTABLISHES, IDENTIFIERS, PRODUCES,
                                           SHAPE, ToolsBlock, thawed)

    declared = [m for m in manifests if m.tools is not None]
    if not declared:
        return None

    usable: List["SkillManifest"] = []
    blocks: Dict[str, Any] = {}
    for manifest in declared:
        try:
            blocks[manifest.name] = ToolsBlock.from_mapping(manifest.tools)
        except ValueError as exc:
            problems.append(
                f"skill {manifest.name!r} has a `tools:` block that is not "
                f"usable on its own, so there is nothing to merge:{exc}")
            continue
        usable.append(manifest)
    if not usable:
        return None

    raw_blocks = [m.tools for m in usable]
    merged: Dict[str, Any] = {}

    defaults: Dict[str, str] = {}
    default_owner: Dict[str, str] = {}
    for manifest in usable:
        for key, kind in blocks[manifest.name].defaults.items():
            if key not in defaults:
                defaults[key] = kind
                default_owner[key] = manifest.name
            elif defaults[key] != kind:
                problems.append(
                    f"`tools: defaults` declares {key!r} as two kinds of "
                    f"subject: {default_owner[key]!r} says "
                    f"{defaults[key]!r} and {manifest.name!r} says {kind!r}. "
                    f"One key is one identity, and taking either answer "
                    f"would link the other skill's receipts into a subject "
                    f"it never named")
    if _declares(raw_blocks, "defaults"):
        body: Dict[str, Any] = {}
        if any(IDENTIFIERS in (raw.get("defaults") or {})
               for raw in raw_blocks
               if isinstance(raw.get("defaults"), Mapping)):
            body[IDENTIFIERS] = {key: {"kind": defaults[key]}
                                 for key in sorted(defaults)}
        merged["defaults"] = body

    # The accumulators, keyed by `tool_key` — the identity, not a spelling —
    # with every spelling that was declared kept beside it so the emitted
    # name can be chosen by sorting rather than by arrival. `wrote` is the
    # key-presence half — composition may change a value and may never
    # change a declared key's presence, `_declared`'s lesson one block over
    # — and it is read off the RAW entries, because a parsed entry cannot
    # tell `establishes: []` from a skill that never mentioned it.
    entries: Dict[str, Dict[str, Any]] = {}
    spellings: Dict[str, List[str]] = {}
    wrote: Dict[str, set] = {}
    entry_owner: Dict[str, str] = {}
    ident_owner: Dict[Tuple[str, str], str] = {}
    shape_owner: Dict[str, str] = {}
    grouped = _tool_groups([entry.name for manifest in usable
                            for entry in blocks[manifest.name].entries])
    for manifest in usable:
        raw_entries = {
            str((item or {}).get("name") or "").strip(): item
            for item in (manifest.tools.get("entries") or ())
            if isinstance(item, Mapping)
        }
        for entry in blocks[manifest.name].entries:
            kept = grouped[entry.name]
            if kept not in entries:
                entries[kept] = {IDENTIFIERS: {}, ESTABLISHES: [],
                                 PRODUCES: [], SHAPE: None}
                spellings[kept] = []
                wrote[kept] = set()
                entry_owner[kept] = manifest.name
            if entry.name not in spellings[kept]:
                spellings[kept].append(entry.name)
            acc = entries[kept]
            # Refusals name the tool as the skill being merged SPELLED it —
            # `kept` is an identity and not a word in anybody's file, and a
            # message quoting it would send an author looking for a name
            # they never typed.
            shown = entry.name
            for key, kind in entry.identifiers.items():
                if key not in acc[IDENTIFIERS]:
                    acc[IDENTIFIERS][key] = kind
                    ident_owner[(kept, key)] = manifest.name
                elif acc[IDENTIFIERS][key] != kind:
                    problems.append(
                        f"`tools: {shown}` declares the identifier {key!r} as "
                        f"two kinds of subject: "
                        f"{ident_owner[(kept, key)]!r} says "
                        f"{acc[IDENTIFIERS][key]!r} and {manifest.name!r} "
                        f"says {kind!r}. One key is one identity")
            for name in entry.establishes:
                if name not in acc[ESTABLISHES]:
                    acc[ESTABLISHES].append(name)
            for produced in entry.produces:
                twin = next((item for item in acc[PRODUCES]
                             if (item.kind, item.field)
                             == (produced.kind, produced.field)), None)
                if twin is None:
                    acc[PRODUCES].append(produced)
                elif twin != produced:
                    problems.append(
                        f"`tools: {shown}` declares the product "
                        f"{produced.kind}/{produced.field} twice over with "
                        f"different chains: {twin.sentence()} and "
                        f"{produced.sentence()}. One product arrives through "
                        f"one call, and a hint pointing at two is a hint "
                        f"nobody can follow")
            if entry.shape is not None:
                if acc[SHAPE] is None:
                    acc[SHAPE] = entry.shape
                    shape_owner[kept] = manifest.name
                elif _canonical(acc[SHAPE]) != _canonical(entry.shape):
                    problems.append(
                        f"`tools: {shown}` is given two different "
                        f"`{SHAPE}` fallbacks, by {shape_owner[kept]!r} and "
                        f"{manifest.name!r}. A fallback shape is what a "
                        f"server that publishes none is read as, and two of "
                        f"them is two planes")
            wrote[kept] |= {key for key in (IDENTIFIERS, ESTABLISHES,
                                            PRODUCES, SHAPE)
                            if key in (raw_entries.get(entry.name) or {})}

    if _declares(raw_blocks, "entries"):
        # Ordered by identity and named by the spelling `_tool_groups`
        # chose: both halves come out of sorting, so the block two skills
        # compose to does not depend on which of them was typed first.
        merged["entries"] = [
            _tools_entry(name, entries[name], wrote[name])
            for name in sorted(entries, key=lambda name: (tool_key(name),
                                                          name))
        ]

    # Validated HERE, for `_merge_cognition`'s reason: the merged mapping is
    # a block no skill wrote, and the door is where a mission finds out that
    # it does not stand up. It can find something the inputs could not — a
    # `produces` keyed on an identifier the composition dropped is the shape
    # of it — and the cost is one read over a small mapping.
    try:
        ToolsBlock.from_mapping(merged)
    except ValueError as exc:
        problems.append(
            f"the merged `tools:` block is not one the plane resolver would "
            f"take:{exc}")
    return merged


def _tools_entry(name: str, accumulated: Dict[str, Any],
                 wrote: set) -> Dict[str, Any]:
    """One merged entry as the mapping a reader takes, in a fixed order.

    Sorted throughout, and a verb appears only where some skill wrote it:
    the presence rule is the same one ``grounding:`` keeps, and the sorting
    is what makes composing two skills the other way round the same block.
    """
    from core.runtime.declarations import (ESTABLISHES, IDENTIFIERS, PRODUCES,
                                           SHAPE, thawed)

    entry: Dict[str, Any] = {"name": name}
    if IDENTIFIERS in wrote:
        entry[IDENTIFIERS] = {
            key: {"kind": accumulated[IDENTIFIERS][key]}
            for key in sorted(accumulated[IDENTIFIERS])
        }
    if ESTABLISHES in wrote:
        entry[ESTABLISHES] = sorted(accumulated[ESTABLISHES])
    if PRODUCES in wrote:
        entry[PRODUCES] = [item.as_record() for item in
                           sorted(accumulated[PRODUCES],
                                  key=lambda item: (item.kind, item.field,
                                                    item.via, item.on))]
    if SHAPE in wrote and accumulated[SHAPE] is not None:
        # `thawed`, because what comes out of a `ToolEntry` is frozen all
        # the way down and what goes out of here is DATA — a raw block a
        # reader, a dump or a JSON line may meet next, and a read-only proxy
        # in one of those is a string nobody can read back.
        entry[SHAPE] = thawed(accumulated[SHAPE])
    return entry


def compose_manifests(manifests: Sequence["SkillManifest"]) -> "SkillManifest":
    """Several manifests as the ONE a mission runs under, or a refusal.

    ``--skill`` repeats, and this is the only place in the framework that
    knows what repeating it means.  One owner, for the reason the loader
    is one: a second implementation of *what does it mean to run two
    skills at once* would union the tools one way in the CLI and another
    way in a platform embedding the library, and both transcripts would
    look ordinary.

    **One manifest is returned unchanged** — the same object, not a copy
    — so the single-skill path is byte-identical to what it was before
    composition existed, which the replay corpus is what proves.

    Several, and the FIRST is the primary.  It owns everything a mission
    has exactly one of: the :attr:`~SkillManifest.name` every refusal and
    every memory bank is filed under, the version, the ``source``, and
    **the answer shape** — a supporting skill's ``output_format`` is
    stripped back out of its prompt, because two output contracts in one
    system message is a model picking one, and the one the primary's
    grounding block checks is the one it may not pick.  The primary's own
    contract is moved to the END of the composition, after every
    supporting body, because :meth:`SkillManifest._render_prompt` puts it
    last for a reason that composition would otherwise undo: it is the
    instruction a model is acting on when it stops.

    What the supporting skills bring is what a mission can have more than
    one of:

    * the **closed set**, as a union in first-seen order.  Identity is
      :func:`~core.tools.descriptors.same_tool`, this framework's one
      answer to *are these the same tool*, so two skills naming one tool
      in two conventions name it once.  A tool optional (``?``) in one
      skill and required in another is **required**: the skill that needs
      it needs it, and being composed with a skill that merely likes it
      is not news about the plane;
    * the **prompt**, in listed order, primary first;
    * the **grounding block**, merged key by key (see
      :func:`_merge_grounding`) and then handed to
      :meth:`~core.runtime.grounding.GroundingConfig.from_mapping`, so a
      merge that produced something unusable is a refusal at the door.
      Checking is unioned and never intersected: strictness asked for by
      any skill binds the run;
    * the **rule pack**, merged by :func:`_merge_cognition`: ``rules`` and
      ``goals`` union by name, ``cardinality`` agrees per field or refuses.
      Nobody's clause is dropped and nobody's clause is replaced, because a
      pack is a set of named things and a name is what everything
      downstream says;
    * the **plane declarations**, merged by :func:`_merge_tools`: entries
      union by tool, ``establishes`` and ``produces`` union, and every
      place two skills could mean different things by one word —
      an identifier's kind, a product's chain, a fallback shape — agrees
      or refuses naming both.  The result is order-independent, because it
      is written into a run's reasoning log and read back;
    * the ``sdk_import``, if exactly one distinct one was named, and the
      ``sandbox``, at the strictest thing anybody asked for.  The
      code-plane gate then runs over **each input manifest** under that
      composed sandbox, and over the composed set as well: the union
      deduplicates on ``same_tool``, so gating only the composed set
      would let the bridged spelling of a tool swallow this host's own
      and make the refusal depend on which skill was typed first.

    Everything that cannot be merged honestly is a **refusal listing
    every problem at once**, in this module's idiom: a disagreement about
    the identifier grammar, two SDKs, one plane name meaning two things,
    the same skill listed twice.  Composing skills is something an
    operator does at a command line and gets wrong at a command line, and
    a refusal arriving one line at a time is fixed one line at a time.

    Known and deliberate, and it cuts BOTH ways: two skills naming one
    tool in two conventions keep the FIRST spelling, so the composed
    entry's *namespace* is decided by listing order.  ``thing`` first and
    ``mcp.thing`` second composes to ``thing`` — the entry stops saying a
    server owns it, and :func:`core.cli._local_plane_or_refuse`, which
    reads a ``mcp.``-prefixed entry as *this must come from a server*,
    stops asking for one.  The other way round composes to ``mcp.thing``,
    and the entry now claims a server owns a tool that may be built in:
    on a host with no transport that composition is **refused** while the
    first order runs.  Resolution itself matches on ``same_tool`` either
    way and binds the same tool, so nothing is mis-dispatched; what moves
    is which questions get asked about the entry, and the direction it
    moves in is fail-closed — a refusal naming the composition, not a
    quiet run.  The gate that must never move with order is the
    code-plane one, and that is why it is asked of each input manifest
    rather than of the deduplicated set.
    """
    loaded = list(manifests)
    if not loaded:
        raise SkillManifestError(
            "no skill manifests to compose. A mission runs under one skill "
            "or several; composing none is not a way to run under none"
        )
    if len(loaded) == 1:
        return loaded[0]

    problems: List[str] = []
    primary = loaded[0]

    # The same skill twice is a typo, and a silent de-duplication is what
    # would make it a typo nobody ever finds: the second copy contributes
    # no tool, no sentence and no grounding rule the first did not, so the
    # run would be exactly the single-skill run the operator believed they
    # had just left behind.
    seen_source: Dict[str, str] = {}
    seen_name: Dict[str, str] = {}
    for manifest in loaded:
        source = (str(Path(manifest.source).expanduser().resolve())
                  if manifest.source is not None else "")
        if source and source in seen_source:
            problems.append(
                f"{manifest.source} is listed twice. A skill composed with "
                f"itself adds nothing to itself"
            )
            continue
        if manifest.name in seen_name:
            problems.append(
                f"two of these skills are both called {manifest.name!r} "
                f"({seen_name[manifest.name]}). Every refusal, every memory "
                f"bank and every report names a skill by that one word, so "
                f"two of them is one being talked about and the other one "
                f"silently not"
            )
            continue
        if source:
            seen_source[source] = manifest.name
        seen_name[manifest.name] = source or f"pack {manifest.name!r}"

    entries: List[str] = []
    still_optional: Dict[str, bool] = {}
    for manifest in loaded:
        for entry in manifest.allowed_tools:
            optional_here = entry in manifest.optional_tools
            already = next((seen for seen in entries
                            if same_tool(seen, entry)), None)
            if already is None:
                entries.append(entry)
                still_optional[entry] = optional_here
            elif not optional_here:
                still_optional[already] = False

    stated_sdk = [(m.name, m.sdk_import) for m in loaded if m.sdk_import]
    sdk_import = ""
    if len({value for _name, value in stated_sdk}) > 1:
        problems.append(
            "these skills name different SDKs — "
            + "; ".join(f"{name!r} says `import {value}`"
                        for name, value in stated_sdk)
            + ". The sentence that offers a step the platform's own module "
              "names one module, and a sentence naming two is a sentence the "
              "model writes wrong"
        )
    elif stated_sdk:
        sdk_import = stated_sdk[0][1]

    asked = [manifest.sandbox for manifest in loaded]
    sandbox = BWRAP if BWRAP in asked else ("none" if "none" in asked else "")

    # The primary's answer shape comes off the front of the composition and
    # goes back on the END, after every supporting body. `_render_prompt`
    # puts `output_format` last for a reason — it is the instruction a model
    # is acting on when it stops — and appending three more skills' prose
    # after it would bury the reason under exactly the recency effect the
    # reference deployment measured when moving the conduct after the
    # catalogue was what finally made the conduct bind.
    prompt = "\n\n".join(
        part for part in
        [_prompt_without_output_contract(m) for m in loaded]
        + [f"{_OUTPUT_LABEL}:\n{primary.output_contract}"
           if primary.output_contract else ""]
        if part and part.strip()
    )

    grounding = _merge_grounding(loaded, problems)
    if grounding is not None:
        # Validated HERE rather than left to the caller, because a merge
        # can produce a block no skill wrote: two skills each scoping
        # `figures_from` to their own `number_pattern`, the patterns
        # disagreeing so neither survives, and the surviving scope able to
        # bind nothing. Run even when the merge already found problems —
        # that IS the case, and an operator fixing a composition wants the
        # consequence named beside the cause rather than on the next run.
        from core.runtime.grounding import GroundingConfig

        try:
            GroundingConfig.from_mapping(grounding)
        except ValueError as exc:
            problems.append(
                f"the merged `grounding:` block is not one a validator can "
                f"be built from: {exc}"
            )

    cognition = _merge_cognition(loaded, problems)
    tools = _merge_tools(loaded, problems)

    composed = SkillManifest(
        name=primary.name,
        description=primary.description,
        version=primary.version,
        allowed_tools=tuple(entries),
        optional_tools=frozenset(entry for entry, optional
                                 in still_optional.items() if optional),
        prompt=prompt,
        output_contract=primary.output_contract,
        grounding=grounding,
        cognition=cognition,
        tools=tools,
        sdk_import=sdk_import,
        sandbox=sandbox,
        source=primary.source,
        composed=tuple(manifest.name for manifest in loaded),
    )

    # The code-plane gate, run over EACH INPUT manifest under the sandbox
    # the composition arrived at — and then over the composed set as well.
    #
    # Per-input is not belt and braces, it is the only correct half, and
    # the reviewer found out why: the union deduplicates on `same_tool`,
    # so a skill naming the bridged `mcp.run_shell_command` and a skill
    # naming this host's own `run_shell_command` collapse to ONE entry —
    # whichever was listed first. Gating the composed set alone therefore
    # made the refusal depend on the order two skills were typed in: the
    # bridged spelling first swallowed the local one and the local code
    # plane went ungated, the other way round it refused. A gate that
    # depends on argument order is not a gate.
    #
    # `replace(m, sandbox=sandbox)` asks each manifest its own question —
    # *do YOUR tools run code on this host* — against the isolation the
    # COMPOSITION will actually run under, which is the honest pairing: a
    # skill that declared `none` is not unsafe when it is composed with
    # one that brought bwrap, and a skill that declared bwrap is not safe
    # because somebody else's entry is the one that survived dedup.
    #
    # The composed check stays too, for the entries that are only a
    # problem together. Identical lines are folded: one entry gated twice
    # is one thing to fix, and a refusal that says it twice reads like two.
    from dataclasses import replace

    unsafe: List[str] = []
    for manifest in loaded + [composed]:
        for line in replace(manifest, sandbox=sandbox)._sandbox_problems(None):
            if line not in unsafe:
                unsafe.append(line)
    problems.extend(unsafe)

    if problems:
        raise SkillManifestError(
            f"these {len(loaded)} skills do not compose into one mission:\n"
            f"  - " + "\n  - ".join(problems)
        )
    return composed


def available_skills(directory) -> List[Path]:
    """Every ``<dir>/*/SKILL.md``, sorted.  For listing, not loading."""
    return sorted(Path(directory).expanduser().glob("*/SKILL.md"))
