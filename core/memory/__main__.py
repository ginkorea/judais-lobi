# core/memory/__main__.py — the operator's half of the memory bank

"""``python -m core.memory`` — look at the bank, and edit it by hand.

Core memory is *self-edited*: the model writes it through ``memory_write``
and that is the point of the tier.  But a tier that only a model can edit is
a tier an operator cannot correct, and the first thing anyone wants after a
model pins something wrong is to unpin it without starting a mission.  So
there are two writers and they go through **one** implementation:
:class:`~core.memory.bank.MemoryBank` — this module parses arguments and
prints, and decides nothing.  A cap refused here is refused in the same
words a model is refused in, because it is the same refusal.

::

    python -m core.memory stats
    python -m core.memory blocks
    python -m core.memory add --label house-style --kind preference \\
        --body "Answers are short; no preamble." --reason "asked twice" \\
        --source operator
    python -m core.memory delete --label house-style --reason "no longer true"
    python -m core.memory notes --limit 20
    python -m core.memory purge --notes

Every command takes ``--memory DIR`` (default: ``JUDAIS_LOBI_MEMORY``),
``--principal`` (default: ``JUDAIS_LOBI_MEMORY_PRINCIPAL``, then
``default``) and ``--skill``.  The exit status is the bank's: ``0`` for a
write that happened, ``1`` for one that was refused, so a script can tell.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from core.memory.bank import (
    BLOCK_KINDS, MEMORY_ENV, PRINCIPAL_ENV, MemoryBank, bank_root,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m core.memory",
        description="Inspect and edit a judais-lobi memory bank.")
    parser.add_argument("--memory", default=None,
                        help=f"the bank directory (default: ${MEMORY_ENV})")
    parser.add_argument("--principal", default=None,
                        help=f"which partition (default: ${PRINCIPAL_ENV}, "
                             f"then 'default')")
    parser.add_argument("--skill", default="",
                        help="the skill partition (default: the unnamed one)")

    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("stats", help="what this bank holds")
    commands.add_parser("blocks", help="list core memory blocks")

    notes = commands.add_parser("notes", help="list distilled notes")
    notes.add_argument("--limit", type=int, default=20)

    for verb in ("add", "replace"):
        write = commands.add_parser(verb, help=f"{verb} a core memory block")
        write.add_argument("--label", required=True)
        write.add_argument("--kind", default="fact", choices=BLOCK_KINDS)
        write.add_argument("--body", required=True)
        write.add_argument("--reason", required=True)
        write.add_argument("--source", default="operator")

    delete = commands.add_parser("delete", help="delete a core memory block")
    delete.add_argument("--label", required=True)
    delete.add_argument("--reason", required=True)

    purge = commands.add_parser("purge", help="delete notes (and blocks)")
    purge.add_argument("--notes", action="store_true", default=False)
    purge.add_argument("--blocks", action="store_true", default=False)

    recall = commands.add_parser("recall", help="run a recall by hand")
    recall.add_argument("query")
    recall.add_argument("--k", type=int, default=5)

    return parser


def _bank(args: argparse.Namespace) -> Optional[MemoryBank]:
    """The bank the flags name, or ``None`` with the reason already printed.

    ``--memory`` beats the environment, the environment beats nothing at
    all: there is no default directory, because a bank that appeared on
    disk because somebody typed ``python -m core.memory stats`` is a bank
    nobody chose.
    """
    root = bank_root(args.memory) if args.memory else bank_root()
    if root is None:
        print(f"no memory bank: pass --memory DIR or set {MEMORY_ENV}.",
              file=sys.stderr)
        return None
    return MemoryBank(root, principal=args.principal, skill=args.skill)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    bank = _bank(args)
    if bank is None:
        return 2

    if args.command == "stats":
        facts = bank.stats()
        for key in ("path", "principal", "skill", "blocks", "notes"):
            print(f"{key}: {facts[key] if facts[key] != '' else '(unnamed)'}")
        print(f"core memory: {facts['core_tokens']}/{facts['core_cap']} "
              f"tokens")
        for principal, skill in facts["partitions"]:
            print(f"partition: {principal} / {skill or '(unnamed skill)'}")
        return 0

    if args.command == "blocks":
        found = bank.blocks()
        if not found:
            print("(no core memory blocks in this partition)")
            return 0
        for block in found:
            print(block.render())
            print(f"    why: {block.reason}  source: {block.source or '?'}"
                  + (f"  run: {block.run_id}" if block.run_id else ""))
        print(f"{len(found)} block(s), "
              f"{bank.core_tokens_used()}/{bank.core_tokens} tokens")
        return 0

    if args.command == "notes":
        found = bank.notes()[:max(1, args.limit)]
        if not found:
            print("(no notes in this partition)")
            return 0
        for note in found:
            print(note.render())
        return 0

    if args.command in ("add", "replace"):
        return _report(bank.write(
            args.command, label=args.label, kind=args.kind, body=args.body,
            reason=args.reason, source=args.source))

    if args.command == "delete":
        return _report(bank.write("delete", label=args.label,
                                  reason=args.reason))

    if args.command == "purge":
        # Neither flag means notes, which is the harmless half: blocks were
        # pinned deliberately and are not what somebody clearing accumulated
        # noise is after.
        notes = args.notes or not args.blocks
        gone = bank.purge(notes=notes, blocks=args.blocks)
        print(f"deleted {gone} row(s)")
        return 0

    if args.command == "recall":
        return _report(bank.recall(query=args.query, k=args.k))

    return 2                                    # pragma: no cover - argparse


def _report(result) -> int:
    """Print a bank result in the executor's own ``(rc, out, err)`` shape."""
    code, out, err = result
    if out:
        print(out)
    if err:
        print(err, file=sys.stderr)
    return int(code)


if __name__ == "__main__":                      # pragma: no cover
    raise SystemExit(main())
