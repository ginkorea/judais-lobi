# core/bounding.py — how much of one tool result reaches a model, decided once

"""The single owner of "a tool result is bounded before a model sees it".

The rule had four implementations before this module existed, all of them
at ``32_768`` and none of them agreeing on what bounding *means*:

* :mod:`core.runtime.mission` cut head and tail and said so in a marker
  that named the store handle the rest could be read from;
* :class:`core.kernel.roles.RoleContext` cut the head only and appended a
  bare ``[...truncated at N bytes]``;
* :func:`core.tools.tool_output.build_tool_output_record` spilled the
  whole output to a log file and showed the model **none** of it;
* and the number itself was declared four times — twice as a literal in a
  dataclass field, twice as a module constant — so raising the budget in
  one place raised it nowhere else.

Four behaviours is three too many, and the difference is not cosmetic.  A
head-only cut throws away the totals, which is where a governed view puts
the counts a model is usually asked for.  A cut with no marker is worse
than no cut at all: the model cannot see that anything is missing, so it
answers from the part it can see or from memory, and no rule about
restating figures can bite because nothing told it a figure was gone.

So there is one function, and its behaviour is the mission's — the
best-behaved of the four — with the marker text preserved verbatim
because tests, ``README.md`` and ``PLATFORMS.md`` all quote it.

**Why here and not in a package.**  The three callers live in
:mod:`core.runtime`, :mod:`core.kernel` and :mod:`core.tools`.  The
mission path deliberately does not import the kernel (the review's
conclusion was not to route missions through it, and importing a budget
object for one integer is the first step of doing it anyway), and
``core.runtime.__init__`` pulls in every backend, which is not a thing a
role or a tool should have to load to learn an integer.  This module
imports nothing, from this package or outside it, so every direction is
open and none of them is a cycle.
"""

from __future__ import annotations

from typing import Tuple

#: How much of one tool result reaches the transcript, in UTF-8 bytes.
#:
#: Uncapped, one large governed view evicts the earlier steps that told
#: the model what its numbers mean, or exceeds ``max_model_len``
#: outright, and neither leaves a trace in the answer.
#:
#: This is the number the kernel's ``BudgetConfig`` and the chat path's
#: ``ContextConfig`` default their ``max_tool_output_bytes_in_context``
#: to.  Those stay dataclass fields because they are configuration — a
#: deployment may lower them — but the default is this one integer.
MAX_RESULT_BYTES = 32_768

#: How the bounded portion is split. Head carries the shape of the
#: result — the schema, the first rows, the field names — and the tail
#: carries totals and trailing summaries, which is where a governed view
#: puts the counts.
HEAD_FRACTION = 0.6


def bound_result(
    text: str,
    limit: int = MAX_RESULT_BYTES,
    *,
    where: str = "",
    head_fraction: float = HEAD_FRACTION,
) -> Tuple[str, bool]:
    """Head and tail of *text* within *limit* bytes, with a marker saying so.

    Returns ``(bounded_text, was_truncated)``.  *text* is returned
    unchanged, with ``False``, when it already fits or when *limit* is
    zero or negative — a caller that wants no bound says so with a zero
    and does not get a marker for its trouble.

    The marker is not decoration.  It states how many bytes went from
    each end and how many there were, and it says outright that the
    middle must not be guessed at, because the failure this guards
    against is a model narrating a figure it can no longer see.

    *where* is the one clause the caller owns: a sentence saying where
    the rest of the result still lives — a mission store handle, a log
    file on disk — appended inside the marker's brackets.  It should
    begin with a space and end with a full stop.  Empty means the rest is
    gone, and the marker simply does not promise otherwise.

    Byte-oriented on purpose.  The budget it enforces is a context
    budget, and a multi-byte character costs what it costs; the two
    decodes use ``errors="ignore"`` so a cut through the middle of one
    drops that character rather than raising.
    """
    data = text.encode("utf-8")
    if limit <= 0 or len(data) <= limit:
        return text, False

    head_n = max(1, int(limit * head_fraction))
    tail_n = max(1, limit - head_n)
    head = data[:head_n].decode("utf-8", "ignore")
    tail = data[-tail_n:].decode("utf-8", "ignore")
    marker = (
        f"\n… [truncated: {head_n} head + {tail_n} tail bytes of "
        f"{len(data)}. The middle is NOT shown and must not be guessed at."
        f"{where}]\n"
    )
    return head + marker + tail, True
