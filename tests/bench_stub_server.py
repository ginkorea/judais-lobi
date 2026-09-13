#!/usr/bin/env python3
"""The benchmark pack's tool plane: a small governed world, over stdio.

Run as ``python tests/bench_stub_server.py``.  Not a test module — pytest
must not collect it, which is why the name does not start with ``test_``.

``tests/mcp_stub_server.py`` exists to exercise the MCP *client*: a normal
call, typed arguments, a failing tool, a mid-run registration.  This server
exists to exercise the **harness**, and it is built around the six shapes
:data:`core.eval.benchmark_suite.MISSIONS` measures:

* a **ledger** whose entries have to be listed before any of them can be
  read, so a question about "every shipment" is three receipts deep before
  it is one answer;
* an entry that is **missing a field** the other entries have — the asked
  fact is genuinely absent, and the only correct answer says so;
* an **audit** that disagrees with the ledger on two entries, so a figure
  has two sources and they do not match;
* a **release** that refuses any token but the one the entry's own record
  carries, so the right next call depends on a prior receipt's content;
* two **enum vocabularies a caller cannot guess** — the ledger's kind words
  and the calculator's operation names — whose refusals name the fix in as
  many words, so a run that reads its own error finishes and a run that
  reports it does not.  An enum is the right shape for this and an id is
  not: ids get a listing (``window_index``, ``ledger_index``) and a run
  that wants one looks it up, so a mission built on an id refusal would be
  measuring a run that failed to check a catalogue.  Nothing here lists the
  kinds or the operations, and nothing should — they are an argument's
  vocabulary rather than the plane's data;
* a **rollup** carrying a plausible-but-wrong figure beside the right one:
  ``elapsed_s`` is seconds and sits next to a unit count, which is the
  exact misreading a 20B model made of a real platform's ``total_s``
  (ROADMAP §2.9.2) and the reason that class is in the pack.

Nothing here is a platform's data.  The world is invented, it is four
entries and two windows wide, and every figure in it was chosen so that no
two of them are the same number.
"""

from typing import Any, Dict, List

from mcp.server.fastmcp import FastMCP

app = FastMCP("judais-lobi-bench")


#: The ledger.  ``kind`` is ``out`` (a shipment) or ``back`` (a return), and
#: those words are the point: a person asks about "shipments" and "returns",
#: the plane says ``out`` and ``back``, and nothing but a refusal tells the
#: caller which.  ``led.b07`` carries no ``owner`` — the one genuinely
#: absent fact in the world.
ENTRIES: Dict[str, Dict[str, Any]] = {
    "led.a41": {"entry_id": "led.a41", "kind": "out", "units": 120,
                "route": "north", "owner": "team-blue",
                "release_token": "tok-a41-9"},
    "led.b07": {"entry_id": "led.b07", "kind": "out", "units": 86,
                "route": "north", "release_token": "tok-b07-4"},
    "led.c19": {"entry_id": "led.c19", "kind": "back", "units": 31,
                "route": "south", "owner": "team-green",
                "release_token": "tok-c19-2"},
    "led.d55": {"entry_id": "led.d55", "kind": "out", "units": 112,
                "route": "south", "owner": "team-blue",
                "release_token": "tok-d55-7"},
}

#: The second source.  It agrees with the ledger on two entries and does not
#: on the other two, and the disagreement is the mission: an answer that
#: quotes one of these numbers alone has hidden the other.
AUDIT: Dict[str, int] = {
    "led.a41": 120, "led.b07": 86, "led.c19": 47, "led.d55": 98,
}

#: The windows, by an id nobody guesses from "window 2" — and which nobody
#: has to, because ``window_index`` lists them.  ``settled_units`` is the
#: figure a person asking about a window wants; ``elapsed_s`` is seconds of
#: wall clock and ``pending_units`` is what has NOT settled, and both sit
#: beside it looking exactly as quotable.
#:
#: ``win-0002``'s 291 is deliberately **not** the ledger's shipment total
#: (318).  It was, and that was a confound: a run that answered 318 from
#: the entries would have passed the window mission without reading a
#: window at all, and the misleading-field mission would have been scoring
#: two different routes to one number.
WINDOWS: Dict[str, Dict[str, Any]] = {
    "win-0002": {"window": "win-0002", "settled_units": 291,
                 "pending_units": 24, "elapsed_s": 154.024, "blocks": 7},
    "win-0003": {"window": "win-0003", "settled_units": 204,
                 "pending_units": 631, "elapsed_s": 88.5, "blocks": 4},
}

#: What a person calls each window, so the index can be looked up by the
#: words in a question rather than by a guess at the id.
WINDOW_LABELS: Dict[str, str] = {"win-0002": "window 2",
                                 "win-0003": "window 3"}

#: The kinds the ledger listing accepts.  Three words, none of them the
#: word a person uses, and **nothing lists them** — see the module
#: docstring on why an enum and not an id.
KINDS = ("out", "back", "all")

#: The operations the calculator accepts.  Named so that neither
#: "subtract" nor "difference" is one of them: a derived figure has to come
#: off the plane, and the first attempt at one here is refused for every
#: run, by a refusal that names all three.
OPERATIONS = ("total", "gap", "scale")


@app.tool()
def ledger_index(kind: str = "all") -> Dict[str, Any]:
    """List the ledger's entries, by kind.

    The refusal names the fix, which is this plane's contract with a run
    that guessed: an error a caller can act on is an instruction, and a
    capability is absent only when the catalogue or a refusal says so.
    """
    if kind not in KINDS:
        raise ValueError(
            f"no such kind {kind!r}; this ledger knows 'out' (a shipment), "
            f"'back' (a return) and 'all'. Call again with one of those.")
    return {"kind": kind, "entries": [
        {"entry_id": entry["entry_id"], "kind": entry["kind"],
         "route": entry["route"]}
        for entry in ENTRIES.values()
        if kind == "all" or entry["kind"] == kind]}


@app.tool()
def ledger_entry(entry_id: str) -> Dict[str, Any]:
    """One entry's record, exactly as the ledger holds it."""
    if entry_id not in ENTRIES:
        raise ValueError(
            f"no entry {entry_id!r} in this ledger; the entries are "
            f"{sorted(ENTRIES)}")
    return dict(ENTRIES[entry_id])


@app.tool()
def audit_count(entry_id: str) -> Dict[str, Any]:
    """An independent count of one entry, from the audit rather than the
    ledger.  It is a different source and it is allowed to disagree."""
    if entry_id not in AUDIT:
        raise ValueError(
            f"the audit holds nothing for {entry_id!r}; it covers "
            f"{sorted(AUDIT)}")
    return {"entry_id": entry_id, "units": AUDIT[entry_id],
            "source": "audit"}


@app.tool()
def window_index() -> Dict[str, Any]:
    """List the windows: each id, and what a person calls it.

    Here so that finding a window's id is a **lookup** and not a guess
    corrected by a refusal.  The refusal below still exists, because a
    plane should name the fix when it is handed a name it does not know;
    what it no longer is, is the only route in.
    """
    return {"windows": [{"window": window, "label": WINDOW_LABELS[window]}
                        for window in sorted(WINDOWS)]}


@app.tool()
def window_rollup(window: str) -> Dict[str, Any]:
    """A window's summary block: what settled, what did not, how long it
    took.  Three figures and only one of them answers "how much"."""
    if window not in WINDOWS:
        raise ValueError(
            f"no window {window!r}; the windows here are "
            f"{sorted(WINDOWS)}. Call again with one of those ids.")
    return dict(WINDOWS[window])


@app.tool()
def arithmetic(numbers: List[float], op: str = "total") -> str:
    """Combine a list of numbers on the plane.

    A derived figure belongs to a computation this plane performed and not
    to prose a model wrote, which is the whole of the ``chaining`` flag.
    Typed arguments rather than an expression: a calculator that parsed a
    string would be a second language in a test fixture.

    The operations are ``total``, ``gap`` and ``scale`` — see
    :data:`OPERATIONS` — and the names are the point: neither "subtract"
    nor "difference" is among them, so a run asked for a difference is
    refused once, by a refusal that names all three.
    """
    if not numbers:
        raise ValueError("nothing to compute; `numbers` is empty")
    if op == "total":
        outcome: float = sum(numbers)
    elif op == "gap":
        outcome = numbers[0]
        for value in numbers[1:]:
            outcome -= value
    elif op == "scale":
        outcome = 1.0
        for value in numbers:
            outcome *= value
    else:
        raise ValueError(
            f"no such operation {op!r}; this plane computes 'total' (adds "
            f"them), 'gap' (takes the rest from the first) and 'scale' "
            f"(multiplies them). Call again with one of those.")
    return str(int(outcome) if float(outcome).is_integer()
               else round(outcome, 4))


@app.tool()
def release_entry(entry_id: str, token: str) -> str:
    """Put an entry through as released.

    The state-changing act, and it refuses every token but the one the
    entry's own record carries — so the right call cannot be composed out
    of the question alone, and the refusal says where the right one is.
    """
    entry = ENTRIES.get(entry_id)
    if entry is None:
        raise ValueError(
            f"no entry {entry_id!r} in this ledger; the entries are "
            f"{sorted(ENTRIES)}")
    if token != entry["release_token"]:
        raise ValueError(
            f"refused: {token!r} is not the release token for {entry_id}. "
            f"Read that entry's own record and pass the `release_token` it "
            f"carries, then call again.")
    return f"released {entry_id} with {token}"


if __name__ == "__main__":                   # pragma: no cover - a subprocess
    app.run()
