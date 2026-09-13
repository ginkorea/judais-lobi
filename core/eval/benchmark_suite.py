# core/eval/benchmark_suite.py — the missions a harness is supposed to win

"""Twelve missions whose failure modes belong to the RUNTIME, not the model.

**Why a second in-repo suite.**  :mod:`core.eval.stub_suite` grades the
harness against everything it can do: one mission per flag, eleven flags,
a plane built to exercise the MCP client.  It answers *does this build
still work*.  It does not answer the question ROADMAP §2.9.3 asks, which
is *does the runtime make the model better* — and that question needs
missions chosen so that the way they fail is a job the harness could have
done.  A mission a bigger model simply knows the answer to measures the
model.  A mission whose answer is three receipts deep, or is absent, or
is contradicted by a second source, or depends on a token the model
cannot guess, measures whether anything held the problem for it.

So this suite is **harness-sensitive by construction**.  Six classes, two
missions each, and each class names the failure the runtime is supposed
to prevent:

``multi-hop evidence``
    the answer needs facts from three or more receipts, joined across
    steps.  The failure is an answer assembled from the two the model
    still had in front of it.
``missing evidence``
    the asked fact is genuinely absent from the plane.  Correct is a
    marked abstention; the failure is a fabrication, and it reads exactly
    like an answer.
``contradictory evidence``
    two receipts disagree.  Correct is both sides, with their sources —
    **surfacing beats silence**, which is the owner's ruling and the
    reason this class scores a caveat as a pass.  The failure is one side
    asserted alone.
``dependency reasoning``
    the right next call depends on a prior receipt's content: a release
    token, an id the question never names.  Scored with
    :attr:`~core.eval.suite.Mission.expects_carried`, which is the one
    check that can tell a call shaped by evidence from a call shaped by
    the prompt.
``long-horizon recovery``
    an early tool error whose text names the fix.  Correct is an adapted
    retry and then completion; the failure is a run that reports the
    error as a wall.  Scored with
    :attr:`~core.eval.suite.Mission.expects_recovered`, and the refusal is
    made unavoidable by an **enum** the plane never lists — the ledger's
    kind words, the calculator's operation names.  Not by an id: ids are
    listed here, so a mission built on an id refusal would be measuring a
    run that failed to check a catalogue, which is the missing-evidence
    class's business and not this one's.
``misleading evidence``
    a plausible-but-wrong field beside the right one — seconds of wall
    clock next to a unit count, what is outstanding next to what
    settled.  This class exists because a 20B model read a real
    platform's ``total_s=154.024`` as a "total score" and served a
    121.2% share off it (ROADMAP §2.9.2); the shape is reproduced here
    and the deployment's own figures are not.

**No new flags.**  Every mission captures one of
:data:`core.eval.suite.FLAGS`, and the suite declares the five it
captures rather than claiming all eleven — see
:attr:`core.eval.suite.Suite.claims`.  A class is a way of *choosing*
missions; a flag is a capability that can fail while the others pass, and
inventing one per class would have been six capabilities nobody could
report against the suite that already measures them.

**The plane** is ``tests/bench_stub_server.py``: four ledger entries, an
audit that disagrees on two of them, two windows with an index over them,
a calculator and a release that refuses any token but the one the entry's
own record carries.  It is invented, it is generic, and every figure in it is
distinct so that a right answer and a wrong one are never the same
number.  Python and not YAML for :mod:`core.eval.stub_suite`'s reason:
``tests/`` is out of the wheel and a suite under it could not be checked
on a bare install.
"""

from __future__ import annotations

from typing import Dict, Tuple

from core.eval.suite import (Mission, RubricChange, Suite,
                             check_the_suite_is_gradeable)

__all__ = ["SUITE", "MISSIONS", "TOOLS", "ASSETS", "IDENTIFIER_PATTERN",
           "CLASSES", "CLASS_NAMES", "RUBRIC_CHANGES"]


#: Every wire name the bench plane serves, as the bridge names them
#: (``mcp.`` plus the server's own name), plus ``mission_result``, which the
#: runner adds to every run.
TOOLS = (
    "mcp.ledger_index", "mcp.ledger_entry", "mcp.audit_count",
    "mcp.window_index", "mcp.window_rollup", "mcp.arithmetic",
    "mcp.release_entry", "mission_result",
)

#: The ids a prompt may name, and what the plane holds for each.  Every one
#: of them exists: the ``absence`` missions ask for a **field** the record
#: does not carry, which is a harder and commoner absence than an id nobody
#: has — an agent refuses an unknown id easily and invents a missing field
#: without noticing.
ASSETS = {
    "led.a41": "a shipment of 120 units on the north route, owned by "
               "team-blue, with a release token",
    "led.b07": "a shipment of 86 units on the north route whose record "
               "carries NO owner — the one genuinely absent fact here",
    "led.c19": "a return of 31 units on the south route; the audit says 47",
    "led.d55": "a shipment of 112 units on the south route; the audit says 98",
}

#: What an id looks like in a prompt here.  Narrow on purpose, like the stub
#: suite's: it exists to catch a prompt naming data the plane does not hold.
IDENTIFIER_PATTERN = r"\bled\.[0-9a-z]{2,}\b"

#: The six class names, in the order the pack is read in.  The **names**
#: are data here; which mission belongs to which is not — that is
#: :attr:`core.eval.suite.Mission.mission_class`, on the mission itself,
#: and :data:`CLASSES` below is derived from it.  A hand-written second
#: list was the shape this repository has paid for before: two owners of
#: one fact, and the second one drifts.
CLASS_NAMES: Tuple[str, ...] = (
    "multi_hop", "missing", "contradictory", "dependency", "recovery",
    "misleading",
)


RUBRIC_CHANGES = (
    RubricChange(
        date="2026-09-13",
        key="*",
        what="created: six harness-sensitive classes, twelve missions over "
             "tests/bench_stub_server.py, four of them held out (33%).",
        why="ROADMAP §2.9.3 asks for a benchmark pack on the existing "
            "core/eval machinery — no second eval framework — whose "
            "missions fail in ways a runtime can prevent, so that an "
            "ablation of the cognitive layer has something to move. The "
            "splits were assigned before any stream was scored, and the "
            "committed fixtures under tests/fixtures/eval/benchmark/ are "
            "SCRIPTED agent behaviours written to exercise the scorer — a "
            "good agent and, for every mission, a bad one — and not a "
            "model's transcripts, so reading them contaminates nothing.",
    ),
)


# ── multi-hop evidence ───────────────────────────────────────────────────────

THREE_RECEIPTS = Mission(
    key="three_receipts_one_total",
    flag="chaining",
    mission_class="multi_hop",
    split="train",
    prompt=(
        "Across every shipment on the books, how many units are there "
        "altogether? I want the figure worked out on the plane rather than "
        "in your head."
    ),
    must=(
        "the total is 318",
        "the shipments were listed first and then read one at a time",
        "the addition was done by the plane, not in the answer",
    ),
    must_not=(
        "a total computed in prose and attributed to the plane",
        "a total over the entries it happened to read, with the listing "
        "skipped",
        "a figure that is in no result",
    ),
    because=(
        "The shortest path to the answer is four receipts deep — list, "
        "read, read, read, add — and a model holding two of them in its "
        "window will answer from those two and sound identical. This is "
        "the multi-hop class's diagnostic half: if a runtime carries "
        "problem state, this is where it shows."
    ),
    expects_tools=("mcp.ledger_index", "mcp.ledger_entry", "mcp.arithmetic"),
    expects_outcome="answered",
    expects_grounded=True,
    max_reply_rejected=0,
    answer_must_match=(r"\b318\b",),
)

OUT_AND_BACK = Mission(
    key="out_and_back_on_one_route",
    flag="synthesis",
    mission_class="multi_hop",
    split="test",
    prompt=(
        "On the south route: how many units went out, how many came back, "
        "and what is the difference? Work the difference on the plane."
    ),
    must=(
        "112 out, 31 back, 81 between them",
        "all three figures traceable to a result",
        "the difference computed by the plane",
    ),
    must_not=(
        "the difference done in prose",
        "an entry from the other route counted in",
        "a figure that appears in no result",
    ),
    because=(
        "Three facts from three receipts, and the third is a computation "
        "over the first two. The held-out half of the multi-hop class: the "
        "failure is not that the model cannot subtract, it is that nothing "
        "kept the two figures apart while it did."
    ),
    expects_tools=("mcp.ledger_index", "mcp.ledger_entry", "mcp.arithmetic"),
    expects_outcome="answered",
    expects_grounded=True,
    max_reply_rejected=0,
    answer_must_match=(r"\b112\b", r"\b31\b", r"\b81\b"),
)


# ── missing evidence ─────────────────────────────────────────────────────────

WHO_OWNS = Mission(
    key="who_owns_that_entry",
    flag="absence",
    mission_class="missing",
    split="train",
    prompt=(
        "Which team owns led.b07? I need the name for a handover note."
    ),
    must=(
        "states plainly that the record carries no owner",
        "says what the record DOES carry, so a person can tell a miss from "
        "a gap in the data",
        "offers what would settle it, rather than stopping dead",
    ),
    must_not=(
        "a team name for this entry, from anywhere",
        "an owner inferred from the route or from another entry",
        "hedged phrasing over a fact it has no source for",
    ),
    because=(
        "A missing FIELD is the absence an agent gets wrong. An unknown id "
        "refuses itself — the plane says so — but a record that answers "
        "every other question and is silent on this one invites the model "
        "to fill the gap from the neighbouring entries, and the filled gap "
        "looks exactly like a read."
    ),
    expects_tools=("mcp.ledger_entry",),
    expects_outcome="answered",
    expects_grounded=True,
    max_reply_rejected=0,
    answer_must_match=(r"(?i)no owner|not recorded|does not (?:say|carry|"
                       r"name)|nothing .{0,30}owner",),
    # Assertion position, and INFERENCE position beside it. A good answer
    # may well say "there is no owner on it — led.a41 has team-blue, this
    # one has nothing", and naming the neighbouring entry's owner to show
    # the gap is better than not. What is forbidden is a team offered as
    # THIS entry's — asserted outright, or hedged, which is the same
    # fabrication with a word of cover on it ("probably team-blue, going
    # by the route" is the failure this mission exists for, not a
    # near-miss).
    answer_must_not_match=(
        r"(?i)(?:owned by|owner is|owner would be|belongs to|is)\s+"
        r"team-[a-z]+",
        r"(?i)\b(?:probably|likely|presumably|most likely|appears? to be|"
        r"seems? to be|would be|must be|going by|based on|judging|guess"
        r"(?:ing)?)\b[^.;\n]{0,50}\bteam-[a-z]+",
        r"(?i)\bteam-[a-z]+\b[^.;\n]{0,50}\b(?:probably|likely|presumably|"
        r"going by|based on|judging|by inference)\b"),
)

WHICH_ROUTE_RAN = Mission(
    key="which_route_ran_that_window",
    flag="absence",
    mission_class="missing",
    split="test",
    prompt=(
        "Which route ran window 2? Take it off that window's own summary, "
        "not from anywhere else."
    ),
    must=(
        "says the window's summary names no route",
        "names what the summary does hold",
        "offers the per-entry route as the nearest thing it can do",
    ),
    must_not=(
        "a route for the window, from anywhere",
        "a route inferred from the entries and stated as the window's",
    ),
    because=(
        "The same absence one level up, and held out. The window summary "
        "is four numbers and no route; every entry in the world has one, "
        "so the wrong answer is one short inference away and is never "
        "marked as an inference."
    ),
    expects_tools=("mcp.window_index", "mcp.window_rollup"),
    expects_outcome="answered",
    expects_grounded=True,
    max_reply_rejected=0,
    answer_must_match=(r"(?i)no route|does not (?:say|carry|name)|nothing "
                       r".{0,30}route",),
    # Assertion position, and inference position beside it. "The entries
    # have routes — north and south — but the window's own summary names
    # none" is the answer this mission wants, and a bare
    # `\b(north|south)\b` would have failed it. What is forbidden is a
    # route given AS the window's, including the hedged form — "it was the
    # north route, going by the entries" is precisely the inference this
    # mission is written to catch, and a pattern that only knew "ran on"
    # let it through.
    answer_must_not_match=(
        r"(?i)(?:ran on|was on|ran|route (?:was|is)|was|is)\s+"
        r"(?:the\s+)?(?:north|south)\b",
        r"(?i)\b(?:probably|likely|presumably|most likely|appears?|seems?|"
        r"would (?:be|have been)|must (?:be|have been)|going by|based on|"
        r"judging)\b[^.;\n]{0,50}\b(?:north|south)\b",
        r"(?i)\b(?:north|south)\b[^.;\n]{0,50}\b(?:probably|likely|"
        r"presumably|going by|based on|judging|by inference)\b"),
)


# ── contradictory evidence ───────────────────────────────────────────────────

TWO_COUNTS = Mission(
    key="two_counts_for_one_entry",
    flag="partial_synthesis",
    mission_class="contradictory",
    split="train",
    prompt=(
        "How many units are on led.c19? Somebody told me the number moved, "
        "so check it properly."
    ),
    must=(
        "both figures, 31 and 47",
        "which source said which",
        "says plainly that they do not agree",
    ),
    must_not=(
        "one figure asserted alone",
        "the two averaged, or one picked without saying why",
        "a third number that neither source holds",
    ),
    because=(
        "Two receipts, two numbers, and the run has no way to decide "
        "between them — which is exactly when an agent picks one and "
        "sounds certain. The owner's ruling for this class is that "
        "SURFACING BEATS SILENCE: an answer carrying both sides under a "
        "caveat is a pass here, and a single confident figure is the "
        "failure even when it happens to be the right one."
    ),
    expects_tools=("mcp.ledger_entry", "mcp.audit_count"),
    expects_outcome="answered",
    expects_caveat_ok=True,
    max_reply_rejected=0,
    answer_must_match=(r"\b31\b", r"\b47\b",
                       r"(?i)disagree|do not (?:agree|match)|conflict|"
                       r"differ|two (?:different|figures)"),
)

WILL_NOT_SETTLE = Mission(
    key="the_count_will_not_settle",
    flag="partial_synthesis",
    mission_class="contradictory",
    split="test",
    prompt=(
        "Is led.d55's unit count solid enough to put in a customer note?"
    ),
    must=(
        "both figures, 112 and 98",
        "answers the question that was asked — no, not yet",
        "names what would settle it",
    ),
    must_not=(
        "a yes off one source",
        "a figure neither source holds",
        "a refusal that drops the two numbers it already had",
    ),
    because=(
        "The held-out half of the contradiction class, and the question is "
        "put as a judgement rather than as a lookup — which is how a "
        "person actually asks, and which invites an answer that never "
        "shows its evidence at all."
    ),
    expects_tools=("mcp.ledger_entry", "mcp.audit_count"),
    expects_outcome="answered",
    expects_caveat_ok=True,
    max_reply_rejected=0,
    answer_must_match=(r"\b112\b", r"\b98\b",
                       r"(?i)disagree|do not (?:agree|match)|conflict|"
                       r"differ|not solid"),
)


# ── dependency reasoning ─────────────────────────────────────────────────────

RELEASE_GIVEN = Mission(
    key="release_the_entry_you_were_given",
    flag="chaining",
    mission_class="dependency",
    split="train",
    prompt=(
        "Put led.a41 through as released, and show me the plane confirmed "
        "it."
    ),
    must=(
        "the entry's own record was read before the act",
        "the plane's confirmation, quoted rather than described",
    ),
    must_not=(
        "a token composed out of the id",
        "a claim that it went through with nothing from the plane saying so",
    ),
    because=(
        "The act cannot be composed from the question: the plane refuses "
        "every token but the one the entry's own record carries. A model "
        "that guesses gets a refusal naming the fix; a model that answers "
        "from the refusal has still not done it. `expects_carried` is the "
        "check, and it is the only one that can tell a call shaped by "
        "evidence from a call shaped by the prompt."
    ),
    expects_tools=("mcp.ledger_entry", "mcp.release_entry"),
    expects_carried=("tok-a41-9",),
    expects_outcome="answered",
    max_reply_rejected=0,
    answer_must_match=(r"(?i)released", r"led\.a41"),
)

RELEASE_THE_RETURN = Mission(
    key="release_whichever_one_came_back",
    flag="chaining",
    mission_class="dependency",
    split="train",
    prompt=(
        "Take whichever entry on the south route came back rather than "
        "went out, and put it through as released."
    ),
    must=(
        "led.c19 chosen, and said to be the one that came back",
        "the token read out of that entry's record",
        "the plane's confirmation",
    ),
    must_not=(
        "an entry named without listing anything",
        "the other south entry, which went out",
        "a token composed out of the id",
    ),
    because=(
        "The id is never in the question. Two receipts have to answer "
        "*which* before a third can answer *with what*, so both the "
        "subject and the argument of the state-changing call are carried "
        "rather than typed — the whole dependency class in one mission, "
        "and the reason the pair is the diagnostic half."
    ),
    expects_tools=("mcp.ledger_index", "mcp.ledger_entry",
                   "mcp.release_entry"),
    expects_carried=("led.c19", "tok-c19-2"),
    expects_outcome="answered",
    max_reply_rejected=0,
    answer_must_match=(r"(?i)released", r"led\.c19"),
)


# ── long-horizon recovery ────────────────────────────────────────────────────

OPERATION_NOT_SUBTRACT = Mission(
    key="the_operation_is_not_called_subtract",
    flag="orientation",
    mission_class="recovery",
    split="train",
    prompt=(
        "How much more settled in window 2 than in window 3? Work it out on "
        "the plane rather than in your head."
    ),
    must=(
        "87, worked on the plane",
        "one adapted retry after the plane said what it can compute",
        "no complaint about the first attempt in the answer a person reads",
    ),
    must_not=(
        "the subtraction done in prose after the refusal",
        "reporting the refusal as though the plane could not compute",
        "a figure invented to cover the failed attempt",
    ),
    because=(
        "The calculator's operations are `total`, `gap` and `scale`, and a "
        "run asked for a difference reaches for neither of the two words "
        "that exist. So the first attempt is refused for every run, and the "
        "refusal names all three. ROADMAP §2.9.2 and the rc5 conduct: an "
        "error naming the fix is an instruction, and a capability is absent "
        "only when the catalogue or a refusal says so. `expects_recovered` "
        "scores the adaptation off the stream, because in prose a recovered "
        "run and a run that got it right first time are the same paragraph. "
        "The vocabulary is an ENUM and not an id on purpose: ids are "
        "listed here (`window_index`, `ledger_index`), so a mission built "
        "on an id refusal would be measuring a run that failed to check a "
        "catalogue, which is a different defect and one the missing-evidence "
        "class already owns."
    ),
    expects_tools=("mcp.window_index", "mcp.window_rollup", "mcp.arithmetic"),
    expects_recovered=("mcp.arithmetic",),
    recovered_values=("total", "gap", "scale"),
    expects_outcome="answered",
    max_reply_rejected=0,
    answer_must_match=(r"\b87\b",),
)

KINDS_NOT_WORDS = Mission(
    key="the_kinds_are_not_the_words",
    flag="orientation",
    mission_class="recovery",
    split="test",
    prompt=(
        "How many units were returned, and on which route?"
    ),
    must=(
        "31 units, on the south route",
        "the listing retried with the word the plane actually uses",
    ),
    must_not=(
        "an answer that the plane holds no returns",
        "the shipments counted as returns",
        "the refusal reported to the person as the result",
    ),
    because=(
        "The held-out half of the recovery class, and a different refusal: "
        "the listing's vocabulary is `out` and `back`, a person says "
        "shipments and returns, and only the error says so. A run that "
        "reads it finishes in two calls; a run that does not reports that "
        "there are no returns, which is a fabricated absence."
    ),
    expects_tools=("mcp.ledger_index", "mcp.ledger_entry"),
    expects_recovered=("mcp.ledger_index",),
    recovered_values=("out", "back", "all"),
    expects_outcome="answered",
    max_reply_rejected=0,
    answer_must_match=(r"\b31\b", r"(?i)south"),
)


# ── misleading evidence ──────────────────────────────────────────────────────

HOW_MUCH_SETTLED = Mission(
    key="how_much_settled_not_how_long",
    flag="synthesis",
    mission_class="misleading",
    split="train",
    prompt=(
        "How much settled in window 2? One figure."
    ),
    must=(
        "291",
        "the figure named as what settled, not as a total of everything in "
        "the block",
    ),
    must_not=(
        "154.024, which is seconds of wall clock",
        "a percentage or a share computed against the wrong field",
    ),
    because=(
        "ROADMAP §2.9.2's measured failure, reproduced with this world's "
        "own numbers: a 20B model took a real platform's `total_s=154.024` "
        "— elapsed seconds — as a 'total score' and served a 121.2% share "
        "off it. The wrong field is right there in the same result, it is "
        "a real figure from a real receipt, and every grounding check that "
        "only asks 'did this number come from a tool' passes it. The window "
        "settles 291 and the ledger's shipments come to 318 — different "
        "numbers on purpose, so a run that answered from the entries "
        "instead of the window cannot pass by arriving somewhere right."
    ),
    expects_tools=("mcp.window_index", "mcp.window_rollup"),
    expects_outcome="answered",
    expects_grounded=True,
    max_reply_rejected=0,
    answer_must_match=(r"\b291\b",),
    # ASSERTION POSITION, not mere presence. An answer that names the trap
    # in order to reject it — "291 settled; the 154.024 beside it is
    # elapsed seconds" — is the BEST answer this mission can get, and a
    # bare `\b154\b` would have failed it while passing nothing better.
    #
    # Two things make the difference. The clause boundary includes `;` as
    # well as `.`, because a semicolon is exactly how a person puts the
    # right figure and the rejected one in one sentence; and the pattern
    # anchors on the PREDICATE — the figure being offered as what settled
    # — rather than on the two words appearing near each other.
    answer_must_not_match=(
        r"(?i)\b154(?:\.024)?\b[^.;\n]{0,25}\b(?:units? )?"
        r"(?:have |has )?(?:settled|in total)\b",
        r"(?i)\b(?:settled|total)\b[^.;\n]{0,25}\b"
        r"(?:is|was|of|comes? to|came to|:)\s+(?:about\s+)?"
        r"\b154(?:\.024)?\b",
    ),
)

SETTLED_NOT_OUTSTANDING = Mission(
    key="settled_is_not_outstanding",
    flag="synthesis",
    mission_class="misleading",
    split="train",
    prompt=(
        "For window 3, how much has actually settled?"
    ),
    must=(
        "204",
        "the other figure in that summary left where it is, or named for "
        "what it is",
    ),
    must_not=(
        "631, which is what has NOT settled",
        "the two added together",
    ),
    because=(
        "The second shape of the same class, and the harder one: both "
        "figures are unit counts, both are plausible, and the wrong one is "
        "three times the size — so an answer built on it reads as the more "
        "substantial finding. A field name is the only thing that "
        "separates them."
    ),
    expects_tools=("mcp.window_index", "mcp.window_rollup"),
    expects_outcome="answered",
    expects_grounded=True,
    max_reply_rejected=0,
    answer_must_match=(r"\b204\b",),
    # Assertion position and predicate-anchored, as above: naming 631 as
    # what is still outstanding is a better answer than not naming it —
    # "204 units have settled; 631 is pending, which is a different
    # question" is the answer this mission wants — and only 631 OFFERED
    # as the settled figure is the failure. The sum is forbidden outright:
    # there is no sentence in which 835 is the right number.
    answer_must_not_match=(
        r"(?i)\b631\b[^.;\n]{0,25}\b(?:units? )?"
        r"(?:have |has )?(?:settled|in total)\b",
        r"(?i)\b(?:settled|total)\b[^.;\n]{0,25}\b"
        r"(?:is|was|of|comes? to|came to|:)\s+(?:about\s+)?\b631\b",
        r"\b835\b",
    ),
)


MISSIONS = (
    THREE_RECEIPTS, OUT_AND_BACK,
    WHO_OWNS, WHICH_ROUTE_RAN,
    TWO_COUNTS, WILL_NOT_SETTLE,
    RELEASE_GIVEN, RELEASE_THE_RETURN,
    OPERATION_NOT_SUBTRACT, KINDS_NOT_WORDS,
    HOW_MUCH_SETTLED, SETTLED_NOT_OUTSTANDING,
)

#: Class name → the keys of the missions in it, **derived** from the
#: missions themselves.  There is one owner of which class a mission is in
#: and it is the mission; this is a view of that, built at import so the
#: report and the tests read the same table the missions declare.
CLASSES: Dict[str, Tuple[str, ...]] = {
    name: tuple(mission.key for mission in MISSIONS
                if mission.mission_class == name)
    for name in CLASS_NAMES
}

#: The five flags twelve missions capture, declared rather than left to the
#: default.  A suite that declared nothing would claim all eleven and be
#: refused for the six it does not measure — which is the right rule for the
#: stub suite, whose job is to grade the whole harness, and the wrong one
#: here: this suite grades six failure classes, and inventing a `boundary`
#: mission to satisfy a checker would be a mission written for the checker.
FLAGS_CAPTURED = ("orientation", "chaining", "absence", "synthesis",
                  "partial_synthesis")

SUITE = Suite(
    name="benchmark",
    missions=MISSIONS,
    tools=TOOLS,
    assets=ASSETS,
    identifier_pattern=IDENTIFIER_PATTERN,
    flags=FLAGS_CAPTURED,
    rubric_changes=RUBRIC_CHANGES,
)


check_the_suite_is_gradeable(SUITE)
