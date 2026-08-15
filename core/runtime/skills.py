# core/runtime/skills.py — a skill manifest: what the model is told, and what it may call

"""Load a ``SKILL.md`` — YAML frontmatter plus a Markdown body — into the
three things a mission needs from it.

A mission agent has two halves.  The loop lives here
(:mod:`core.runtime.mission`); the *operational knowledge* — which facet
to query first, which tool answers which question, what an identifier
looks like, what must never be invented — belongs to whoever operates the
platform being driven.  A manifest is how that half arrives, and this
module is deliberately the only place that reads one.

Three things come out of a manifest, and nothing else does:

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
* an optional **SDK import name** (``sdk_import``): what a platform calls
  itself to Python.  A planner that can propose *code which fetches
  platform data itself* has to name the module that does the fetching,
  and the harness cannot know it — the framework drives whatever platform
  it is pointed at.  Declared here, it composes the sentence
  :mod:`core.runtime.swarm` shows the executor; undeclared, that whole
  rung is withheld rather than offered with a blank where the name goes.

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

from core.tools.descriptors import same_tool

#: Frontmatter fence.  A line that is exactly three dashes.
_FENCE = re.compile(r"^---[ \t]*$", re.MULTILINE)

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
_STRUCTURAL = frozenset({
    "name", "skill_id", "version", "description",
    "allowed_tools", "grounding", "sdk_import",
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


class SkillManifestError(ValueError):
    """A file is not a usable skill manifest, with every reason at once."""


class SkillToolsUnavailable(RuntimeError):
    """A skill's closed set names tools that were not discovered.

    Raised instead of narrowing the set, and it carries the whole list —
    the missing names *and* what was actually on offer.  A mission that
    starts with a silently reduced toolset is a mission that answers from
    the model's memory of the platform, and the transcript looks fine.
    """


def _require_yaml(path: Path):
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - optional extra
        raise SkillManifestError(
            f"{path.name} has YAML frontmatter, which needs pyyaml: "
            f"pip install 'judais-lobi[critic]'"
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
    #: What the platform's SDK is called to ``import``, or ``""``.  Read
    #: by :mod:`core.runtime.swarm` to compose the ``code+sdk`` rung, and
    #: the reason that rung is offered at all.  Empty is not a defect: a
    #: platform reached only through its tools has no SDK to name.
    sdk_import: str = ""
    source: Optional[Path] = None

    # ── loading ─────────────────────────────────────────────────────────

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
            sdk_import=sdk_import,
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
            parts.append(f"Output format:\n{output}")
        return "\n\n".join(parts)

    # ── the closed set, against what was discovered ─────────────────────

    def resolve(self, available: Sequence[str]) -> List[str]:
        """The closed set as *bus* names, or refuse naming every gap.

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

        if problems:
            raise SkillToolsUnavailable(
                f"skill {self.name!r} cannot run against this server:\n  - "
                + "\n  - ".join(problems)
                + "\n\nDiscovered: "
                + (", ".join(offered) or "(nothing)")
                + "\n\nThe closed set is not narrowed to whatever happens to "
                  "be present: a mission missing the tool that answers its "
                  "question will answer it from the model's memory instead, "
                  "and the transcript will look ordinary."
            )
        if not resolved:
            raise SkillToolsUnavailable(
                f"skill {self.name!r} resolved to no tools at all: every entry "
                f"in its closed set is optional and none was discovered. "
                f"Discovered: " + (", ".join(offered) or "(nothing)")
            )
        return resolved


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


def available_skills(directory) -> List[Path]:
    """Every ``<dir>/*/SKILL.md``, sorted.  For listing, not loading."""
    return sorted(Path(directory).expanduser().glob("*/SKILL.md"))
