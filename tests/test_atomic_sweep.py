# tests/test_atomic_sweep.py — no second way to write a store down

"""``core`` writes its stores through one function, and this is the sweep.

:mod:`core.durable` arrived with five callers converted and the rest of the
tree still on ``path.write_text``: the campaign's plan and its synthesis, two
caches, the patch worktree's crash-recovery record, the spilled tool log.
Every one of them is read back — by a later phase, by a later run, or by the
agent that was handed the path — and every one of them was a truncate that
could stop halfway and leave a file that parses as nothing.

The sweep is only worth doing once. What keeps it done is this file: it walks
``core`` for a bare ``write_text``/``write_bytes`` and fails naming the
file and the line, so the next one is a red test rather than a review finding
somebody has to notice.

The exceptions are listed, not inferred. :data:`ALLOWED` is the whole set of
places in ``core`` that write a file the plain way on purpose, each with the
reason, and :class:`TestTheAllowListIsHonest` fails when one of them stops
being true — an exemption for a line that no longer exists is how an
allow-list quietly becomes a blanket.
"""

from __future__ import annotations

import ast
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent / "core"

#: The one module allowed to write a file without going through itself.
OWNER = "core/durable.py"

#: The names that are a whole-file write.
WRITERS = frozenset({"write_text", "write_bytes"})

#: ``(path, source line) -> why this one is not a store.``
#:
#: A file this harness *reads back* is a store and belongs in
#: :func:`core.durable.atomic_write_text`. These three write somebody else's
#: file — the subject of the operation rather than the record of it — and
#: replacing a subject is not the same as replacing a record.
ALLOWED = {
    ("core/patch/applicator.py",
     'file_path.write_text(new_content, encoding="utf-8")'):
        "the file under patch is the caller's, and os.replace would give it a "
        "new inode: the mode bits the next line restores, the hard links to it "
        "and the symlink pointing at it would not survive the swap",
    ("core/patch/applicator.py",
     'file_path.write_text(content, encoding="utf-8")'):
        "apply_create refuses a path that exists, so there is no older version "
        "for an interrupted write to destroy",
    ("core/tools/fs_tools.py",
     'p.write_text(content, encoding="utf-8")'):
        "the fs write tool writes the caller's file at the path the caller "
        "named, with the mode and the identity the caller's filesystem gave it",
}


def _bare_writes():
    """``(relative path, line number, source line)`` for every bare write.

    Read with :mod:`ast` and not with a regular expression, because the two
    modules with the most to say about this write ``path.write_text(...)`` in
    their docstrings to explain what they stopped doing.
    """
    found = []
    for path in sorted(CORE.rglob("*.py")):
        rel = path.relative_to(CORE.parent).as_posix()
        if rel == OWNER:
            continue
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        for node in ast.walk(ast.parse(source, filename=rel)):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in WRITERS):
                found.append((rel, node.lineno, lines[node.lineno - 1].strip()))
    return found


class TestEveryStoreWriteGoesThroughTheOwner:
    def test_no_module_writes_a_store_the_plain_way(self):
        """`path.write_text` truncates and then fills. A store written that
        way is a store that can be found empty."""
        stragglers = [f"{rel}:{line}  {text}"
                      for rel, line, text in _bare_writes()
                      if (rel, text) not in ALLOWED]
        assert not stragglers, (
            "these write a file without core.durable.atomic_write_text; if one "
            "is genuinely not a store, add it to ALLOWED with the reason:\n  "
            + "\n  ".join(stragglers))

    def test_the_owner_is_imported_where_it_is_used(self):
        """Nothing in `core` may grow a private copy of the tempfile dance."""
        offenders = []
        for path in sorted(CORE.rglob("*.py")):
            rel = path.relative_to(CORE.parent).as_posix()
            if rel == OWNER:
                continue
            source = path.read_text(encoding="utf-8")
            if "os.replace(" in source or "NamedTemporaryFile(" in source:
                offenders.append(rel)
        assert offenders == [], (
            "a second implementation of the atomic replace: " + str(offenders))


class TestTheAllowListIsHonest:
    def test_every_exemption_still_names_a_line_that_is_there(self):
        """An exemption outliving its line is how a list of three exceptions
        becomes a licence."""
        present = {(rel, text) for rel, _line, text in _bare_writes()}
        stale = sorted(f"{rel}  {text}" for rel, text in ALLOWED if
                       (rel, text) not in present)
        assert stale == [], "ALLOWED exempts lines that no longer exist:\n  " \
                            + "\n  ".join(stale)

    def test_every_exemption_says_why(self):
        assert all(len(reason.split()) >= 5 for reason in ALLOWED.values())
