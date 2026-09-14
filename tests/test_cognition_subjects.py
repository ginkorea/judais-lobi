# tests/test_cognition_subjects.py — the receipts are about something

"""What a declared identifier buys: a link, a join, and one line to read.

Two merged halves meet in this file.  ``core/runtime/declarations.py`` holds
what a plane says its tools return — *this key is a job's identity* — and
``core/cognition/state.py`` holds the link and the projection it licenses.
Between them sits the attachment: :meth:`core.runtime.cognition
.ShadowCognition._identify`, which reads the one string the harvest is
otherwise forbidden to read and turns a receipt into a claim about a
**subject**.

Four claims, each with its own section, and each of them a thing that was
impossible one commit ago:

* **the declared exception is narrow.**  A key a platform declared is
  harvested as a fact even though it is a string; every other string is
  dropped exactly as before; and the path is walked from the root, so
  ``data.job_id`` never reads ``meta.job_id``.  A wrong link is the one
  mistake in this design that manufactures contradictions, so the tests
  here are mostly about what does *not* link;
* **the link is a claim with two premises.**  The receipt it was read from
  and the declaration that said the key was an identity, at ``SOURCE`` —
  the weaker of the two, because a link is worth its weakest premise and
  rounding up would launder a platform's word into a measurement;
* **the view folds.**  One figure, one line, at the subject, with the
  receipt handle on it — and a contest at a subject names the call behind
  each side, which is the two-status-tools-one-job pair a pane could never
  show before;
* **the frontier says what would answer it**, from ``establishes`` and
  ``produces``, in the same line the supervisor's stall sentence quotes.

The ablation half is not here and needs no second home: cognition-off is
byte-identical because nothing on that path exists at all, and
``tests/test_cognition_shadow.py`` replays the committed corpus both ways
to prove it.  A run whose plane declares nothing takes exactly that path —
:meth:`_identify` returns before it reads anything — which is the first
test below.
"""

import json

import pytest

from core.cognition import (CognitiveState, EvidenceAuthority, EvidenceRef,
                            RuleAuthority, compile_view)
from core.cognition.compile import (CONFLICTS_HEADING, DERIVED, DISPUTED,
                                    FACTS_HEADING, MORE, OWED_HEADING,
                                    RESOLVABLE, VIA, VIA_CAP, owed_line)
from core.durable import RunStore
from core.runtime.cognition import (DECLARATION_KIND, RECEIPT_KIND, Identity,
                                    identities_of, observations_of,
                                    open_shadow, resolvers_of)
from core.runtime.declarations import PlaneDeclarations
from tests.test_cli_mission_skill import elf                        # noqa: F401
from tests.test_cognition_compile import (_brute_force, observe, receipt,
                                          section)

#: The design's own motivating pair: a discovery call that returns a handle
#: and nothing else, and a status call that returns the same handle with the
#: figures under it.  The first is the receipt that could not be linked at
#: all before this lane — its whole payload is a string.
HANDLE = json.dumps({"data": {"job_id": "jl-731"}})
STATUS = json.dumps({"data": {"job_id": "jl-731", "records": 12481},
                     "handling_summary": "governed"})

#: What a platform says about those two tools.  Paths, because the envelope
#: puts the real fields under `data`.
PLANE = {"entries": [
    {"name": "narrative_discovery",
     "identifiers": {"data.job_id": {"kind": "job"}},
     "produces": [{"kind": "asset", "field": "label_set",
                   "via": "job_status", "on": "data.job_id"}]},
    {"name": "job_status",
     "identifiers": {"data.job_id": {"kind": "job"}},
     "establishes": ["state", "records"]},
]}


def plane(manifest=PLANE, wire=None, offered=("narrative_discovery",
                                              "job_status")):
    return PlaneDeclarations.build(wire=wire, manifest=manifest,
                                   offered=list(offered))


@pytest.fixture
def shadow(tmp_path):
    """A shadow over a real store, with :data:`PLANE` declared."""
    store = RunStore(tmp_path / "store")
    run = store.create()
    made = open_shadow(store, run.run_id)
    made.declare_plane(plane())
    return made


# ── what a declared identifier is worth ──────────────────────────────────────


class TestTheDeclaredStringIsTheOnlyStringRead:
    """The narrow exception, tested mostly by what it refuses.

    :func:`identities_of` is the whole of *what a receipt is worth as
    identity*, in one pure function, so these say what a payload is worth
    without running a mission — the same shape
    :func:`~core.runtime.cognition.observations_of` is tested in.
    """

    def test_a_declared_key_is_read_even_though_it_is_a_string(self):
        found, ambiguous = identities_of(HANDLE, {"data.job_id": "job"})
        assert found == (Identity(path="data.job_id", field="job_id",
                                  kind="job", value="jl-731"),)
        assert ambiguous == 0

    def test_an_undeclared_string_is_still_dropped(self):
        """The bound this exception is carved out of, restated where it
        can go red: nothing about strings changed except for keys a
        platform declared.  The undeclared one is spelled like a number
        on purpose — ``"8"`` is the string the harvest must not quietly
        make an ``8``, and a payload of plain words would pass this test
        under a harvest that had stopped dropping strings at all."""
        payload = json.dumps({"data": {"job_id": "jl-731"}, "count": "8"})
        assert identities_of(payload, {}) == ((), 0)
        assert observations_of(payload) == ()
        found, _ = identities_of(payload, {"data.job_id": "job"})
        assert [item.field for item in found] == ["job_id"]

    def test_the_path_is_walked_from_the_root(self):
        """`data.job_id` is not "a key called job_id somewhere". A flat
        name match would link on a same-named key elsewhere in a governed
        envelope, which is a wrong link, which manufactures
        contradictions."""
        payload = json.dumps({"meta": {"job_id": "jl-999"},
                              "data": {"job_id": "jl-731"}})
        found, _ = identities_of(payload, {"data.job_id": "job"})
        assert [item.value for item in found] == ["jl-731"]

    def test_a_declared_key_the_payload_does_not_carry_binds_nothing(self):
        assert identities_of(json.dumps({"data": {}}),
                             {"data.job_id": "job"}) == ((), 0)

    def test_two_values_under_one_key_identify_nothing_and_are_counted(self):
        """The one-figure discipline, applied to identities: which of them
        is the subject is a question the receipt does not answer."""
        payload = json.dumps({"rows": [{"job_id": "a"}, {"job_id": "b"}]})
        assert identities_of(payload, {"rows[].job_id": "job"}) == ((), 1)

    def test_one_value_repeated_is_still_one_identity(self):
        payload = json.dumps({"rows": [{"job_id": "a"}, {"job_id": "a"}]})
        found, ambiguous = identities_of(payload, {"rows[].job_id": "job"})
        assert [item.value for item in found] == ["a"]
        assert ambiguous == 0

    def test_a_number_under_a_declared_key_is_not_an_identity(self):
        """And is not ambiguity either — the harvest already asserts it as
        a figure, and `job:5` beside the figure 5 is two facts nobody can
        tell apart later."""
        assert identities_of(json.dumps({"job_id": 5}),
                             {"job_id": "job"}) == ((), 0)

    def test_an_empty_string_is_not_an_identity(self):
        assert identities_of(json.dumps({"job_id": "   "}),
                             {"job_id": "job"}) == ((), 0)

    def test_the_field_is_the_last_segment_of_the_path(self):
        """One naming rule for the store: a pack declaring `cardinality:
        {job_id: one}` binds the identifier fact, and a rule joining on
        `job_id` joins figures and identifiers alike."""
        found, _ = identities_of(HANDLE, {"data.job_id": "job"})
        assert found[0].field == "job_id"

    def test_a_receipt_with_no_json_is_worth_no_identity(self):
        assert identities_of("job jl-731 is done", {"job_id": "job"}) \
            == ((), 0)

    def test_the_order_is_the_declarations_sorted(self):
        """Deterministic, because two links in the other order are two
        different reasoning logs for one receipt."""
        payload = json.dumps({"b": "second", "a": "first"})
        found, _ = identities_of(payload, {"b": "job", "a": "asset"})
        assert [item.path for item in found] == ["a", "b"]


# ── the link ─────────────────────────────────────────────────────────────────


class TestTheReceiptIsLinkedToWhatItIsAbout:
    """The attachment: two writes per identifier, in the order the kernel
    requires — the fact, then the link that rests on it."""

    def test_a_handle_only_receipt_holds_a_fact_and_is_linked(self, shadow):
        """The refusal `link` documents, closed. Before this lane the
        whole payload was a string, the store held nothing about the
        receipt, and the door refused it."""
        shadow.receipt("narrative_discovery", "r1", HANDLE)
        shadow.close_step()
        claim = shadow.state.claim(
            ("narrative_discovery#r1", "job_id", "jl-731"))
        assert claim is not None
        assert [link.subject for link
                in shadow.state.links_for("narrative_discovery#r1")] \
            == ["job:jl-731"]

    def test_the_counters_say_what_was_bought(self, shadow):
        shadow.receipt("narrative_discovery", "r1", HANDLE)
        shadow.receipt("job_status", "r5", STATUS)
        shadow.close_step()
        assert (shadow.identifiers, shadow.links, shadow.ambiguous) == (2, 2, 0)
        assert shadow.observations == 1            # `records`, the one figure

    def test_the_link_is_source_and_not_deterministic(self, shadow):
        """The weakest premise under a declared link is the platform's
        word. Grading it DETERMINISTIC would launder a declaration into a
        measurement — and would let a projection outrank the receipt it
        disagrees with."""
        shadow.receipt("job_status", "r5", STATUS)
        shadow.close_step()
        link = shadow.state.links()[0]
        assert link.authority is EvidenceAuthority.SOURCE

    def test_the_link_carries_both_premises(self, shadow):
        """The receipt the value was read from, and the declaration that
        said the key was an identity. A link with one of them is a claim
        whose other half nobody can find."""
        shadow.receipt("job_status", "r5", STATUS)
        shadow.close_step()
        link = shadow.state.links()[0]
        assert [ref.kind for ref in link.evidence] == [RECEIPT_KIND,
                                                       DECLARATION_KIND]
        receipt_ref, declared = link.evidence
        assert receipt_ref.locator.endswith("/r5/job_status")
        assert declared.locator == "manifest/job_status/data.job_id"
        assert "job" in declared.note

    def test_two_receipts_naming_one_job_are_one_subject(self, shadow):
        """The join an entity-per-receipt store could never do."""
        shadow.receipt("narrative_discovery", "r1", HANDLE)
        shadow.receipt("job_status", "r5", STATUS)
        shadow.close_step()
        assert {link.subject for link in shadow.state.links()} == {"job:jl-731"}
        assert shadow.state.claim(("job:jl-731", "records", 12481)) is not None

    def two_kinds(self, tmp_path, pack=None):
        """A shadow over a plane whose tool names a job AND an asset.

        The shape the cross-kind guard is about, and the one a real plane
        has: `narrative_discovery` in the design's own example returns a
        job handle and a corpus asset id in one payload.
        """
        store = RunStore(tmp_path / "kinds")
        run = store.create()
        made = open_shadow(store, run.run_id, cognition_block=pack)
        made.declare_plane(PlaneDeclarations.build(manifest={"entries": [
            {"name": "t", "identifiers": {"job_id": {"kind": "job"},
                                          "asset_id": {"kind": "asset"}}},
            {"name": "u", "identifiers": {"job_id": {"kind": "job"},
                                          "asset_id": {"kind": "asset"}}},
            {"name": "job_status",
             "identifiers": {"data.job_id": {"kind": "job"}}}]},
            offered=["t", "u", "job_status"]))
        return made

    def test_a_receipt_naming_two_kinds_writes_no_identifier_fact(self,
                                                                  tmp_path):
        """THE CROSS-KIND GUARD. The kernel projects every live triple of a
        linked entity onto every subject it is linked to — right for a
        figure, wrong for an identity. So a receipt naming a job *and* an
        asset writes neither id as a fact and still links both: the figure
        reaches both subjects, and neither subject is told the other's
        identity."""
        made = self.two_kinds(tmp_path)
        made.receipt("t", "r1", json.dumps(
            {"job_id": "j1", "asset_id": "a1", "records": 5}))
        made.close_step()
        assert made.identifiers == 0
        assert {link.subject for link in made.state.links()} \
            == {"job:j1", "asset:a1"}
        assert made.state.claim(("job:j1", "records", 5)) is not None
        assert made.state.claim(("asset:a1", "records", 5)) is not None
        assert made.state.claim(("asset:a1", "job_id", "j1")) is None
        assert made.state.claim(("job:j1", "asset_id", "a1")) is None

    def test_two_jobs_sharing_an_asset_do_not_contest(self, tmp_path):
        """The reviewer's shape, and the design's own red line: `t` and `u`
        never disagreed about anything. Without the guard the shared asset
        held two `job_id` values, and a pack declaring that field `one`
        turned two true receipts into a contradiction."""
        made = self.two_kinds(tmp_path,
                              pack={"cardinality": {"job_id": "one"}})
        made.receipt("t", "r1", json.dumps(
            {"job_id": "j1", "asset_id": "a1", "records": 5}))
        made.receipt("u", "r2", json.dumps(
            {"job_id": "j2", "asset_id": "a1", "records": 5}))
        made.close_step()
        assert [clash for clash in made.state.contradictions()
                if not clash.settled] == []
        assert made.state.query(("asset:a1", "job_id", "?v")) == ()

    def test_a_handle_only_receipt_of_two_kinds_links_nothing_and_counts(
            self, tmp_path):
        """The guard's stated price. Nothing on the receipt for a link to
        be a claim about, and the alternative was the contest above — so it
        is counted, never forced, and the mission is not told."""
        made = self.two_kinds(tmp_path)
        made.receipt("t", "r1", json.dumps({"job_id": "j1",
                                            "asset_id": "a1"}))
        made.close_step()
        assert (made.links, made.identifiers, made.unlinked) == (0, 0, 2)
        assert made.on is True

    def test_and_the_subject_arrives_through_the_call_that_settles_it(
            self, tmp_path):
        """Why that price is payable: the two-phase flow never depended on
        the handle-only call linking. The call that establishes something
        names one kind, links, and projects."""
        made = self.two_kinds(tmp_path)
        made.receipt("t", "r1", json.dumps({"job_id": "j1",
                                            "asset_id": "a1"}))
        made.receipt("job_status", "r2", json.dumps(
            {"data": {"job_id": "j1", "records": 12481}}))
        made.close_step()
        assert made.state.claim(("job:j1", "records", 12481)) is not None

    def test_a_tool_nobody_declared_links_nothing(self, shadow):
        shadow.receipt("mcp.other", "r9", STATUS)
        shadow.close_step()
        assert shadow.state.links() == ()
        assert shadow.links == 0

    def test_a_run_with_no_declarations_is_the_shadow_it_was(self, tmp_path):
        """The floor: a plane that declared nothing takes the path every
        run took before this feature existed."""
        store = RunStore(tmp_path / "bare")
        run = store.create()
        bare = open_shadow(store, run.run_id)
        bare.receipt("job_status", "r5", STATUS)
        bare.close_step()
        assert bare.state.links() == ()
        assert (bare.identifiers, bare.links) == (0, 0)

    def test_an_ambiguous_key_links_nothing_and_is_counted(self, tmp_path):
        store = RunStore(tmp_path / "two")
        run = store.create()
        made = open_shadow(store, run.run_id)
        made.declare_plane(plane(manifest={"entries": [
            {"name": "runs_get",
             "identifiers": {"rows[].run_id": {"kind": "run"}}}]},
            offered=["runs_get"]))
        made.receipt("runs_get", "r1", json.dumps(
            {"rows": [{"run_id": "a"}, {"run_id": "b"}]}))
        made.close_step()
        assert (made.ambiguous, made.links, made.identifiers) == (1, 0, 0)

    def test_a_value_no_subject_can_be_spelled_from_is_counted(self,
                                                               tmp_path):
        """A subject is `kind:value` and the kernel refuses whitespace in
        either half. The fact still lands — the receipt did say it — and
        the link does not, which is counted and not fatal."""
        store = RunStore(tmp_path / "spaces")
        run = store.create()
        made = open_shadow(store, run.run_id)
        made.declare_plane(plane(manifest={"entries": [
            {"name": "runs_get", "identifiers": {"run_id": {"kind": "run"}}}]},
            offered=["runs_get"]))
        made.receipt("runs_get", "r1", json.dumps({"run_id": "two words"}))
        made.close_step()
        assert made.identifiers == 1
        assert (made.links, made.refused) == (0, 1)
        assert made.on is True

    def test_the_same_receipt_twice_is_one_link(self, shadow):
        """Idempotent on the pair — the kernel owns that, and the shadow
        does not deduplicate behind its back."""
        shadow.receipt("job_status", "r5", STATUS)
        shadow.receipt("job_status", "r5", STATUS)
        shadow.close_step()
        assert len(shadow.state.links()) == 1

    def test_the_log_holds_the_link_and_a_replay_rebuilds_it(self, shadow):
        """The link is a kernel event like any other write, so a resumed
        run believes what the first one did — subjects included."""
        from core.runtime.cognition import replay_reasoning

        shadow.receipt("job_status", "r5", STATUS)
        shadow.close_step()
        rebuilt = replay_reasoning(shadow.path)
        assert [link.subject for link in rebuilt.links()] == ["job:jl-731"]
        assert rebuilt.claim(("job:jl-731", "records", 12481)) is not None


# ── the view ─────────────────────────────────────────────────────────────────


#: The link's other premise, as the shadow makes it: the declaration that
#: said the key was an identity.  In these fixtures because it is what the
#: header must **not** count as a receipt.
DECLARED = EvidenceRef(kind=DECLARATION_KIND,
                       locator="manifest/job_status/data.job_id")


def linked(count: int = 1, *, field: str = "records",
           value: int = 1) -> CognitiveState:
    """*count* receipts, each about its own job, each holding one figure.

    One fact per receipt and one receipt per subject, which is what makes
    the block's header count the same number of receipts as it shows
    facts — the shape :func:`tests.test_cognition_compile._brute_force`
    is written against.
    """
    state = CognitiveState()
    for index in range(count):
        entity, subject = f"mcp.job_status#r{index}", f"job:jl-{index}"
        observe(state, entity, field, value + index)
        state.link(entity, subject,
                   evidence=(receipt(f"r{index}"), DECLARED),
                   authority=EvidenceAuthority.SOURCE)
    return state


def concluded(head: str = "fast") -> CognitiveState:
    """A pack rule firing at the RECEIPT level, and its conclusion linked.

    `job_status#r5` returned `elapsed`; a rule concludes `fast` **about the
    receipt**; the link projects that conclusion onto the subject like any
    other live triple.  The payload never held a `fast` key — which is the
    whole point of the shape.
    """
    state = CognitiveState()
    entity = "mcp.job_status#r5"
    observe(state, entity, "elapsed", 4)
    rid = state.add_rule("fast", ("?e", head, True), (("?e", "elapsed", 4),))
    state.promote_rule(rid, RuleAuthority.SKILL)
    state.link(entity, "job:jl-731", evidence=(receipt("r5"), DECLARED),
               authority=EvidenceAuthority.SOURCE)
    return state


class TestAConclusionNeverBorrowsAReceiptHandle:
    """The line between a citation and a fabrication.

    A projection's premise can itself be a *conclusion* — a pack rule
    firing at the receipt level — and naming the receipt on the subject's
    line would say a call returned a field it never returned.  That is the
    framework writing, in its own voice, exactly the attribution the
    grounding checks exist to catch in the model's.
    """

    def test_the_subject_line_says_derived_and_names_no_call(self):
        lines = section(compile_view(concluded()), FACTS_HEADING)
        subject, = [line for line in lines
                    if line.startswith("job:jl-731 · fast")]
        assert subject == 'job:jl-731 · fast = true  [sourced · derived]'
        assert VIA not in subject

    def test_the_conclusion_keeps_its_own_line_one_level_down(self):
        """It is not folded away: the subject's line is not saying what
        that premise says, so suppressing it would leave nothing at all to
        say the figure was concluded."""
        lines = section(compile_view(concluded()), FACTS_HEADING)
        assert any(line.startswith("mcp.job_status#r5 · fast") and DERIVED
                   in line for line in lines)

    def test_a_read_figure_on_the_same_receipt_still_folds(self):
        """The guard is about the premise, not about the receipt: what the
        call did return is still named at the subject."""
        lines = section(compile_view(concluded()), FACTS_HEADING)
        assert any(line.startswith("job:jl-731 · elapsed")
                   and f"{VIA}mcp.job_status#r5" in line for line in lines)

    def test_the_header_still_counts_the_receipt_under_the_conclusion(self):
        """Counting through the premise — whose own leaves are the
        receipts under its proof — and not through the projection's leaves,
        which carry the link's declaration."""
        assert compile_view(concluded()).receipts == 1

    def test_a_concluded_side_of_a_conflict_names_no_call_either(self):
        state = concluded()
        state.declare_field("fast", "one")
        other = "mcp.audit#r9"
        observe(state, other, "fast", False)
        state.link(other, "job:jl-731", evidence=(receipt("r9"), DECLARED),
                   authority=EvidenceAuthority.SOURCE)
        line, = section(compile_view(state), CONFLICTS_HEADING)
        assert f"{VIA}mcp.audit#r9" in line
        assert f"{VIA}mcp.job_status#r5" not in line


class TestTheViewFoldsTheSubject:
    """One figure, one line — at the subject, with the receipt on it."""

    def test_the_handles_are_sorted_and_not_in_proof_order(self):
        """A line whose word order depends on which of two receipts was
        recorded first renders two ways for one belief. Sorting costs
        nothing and makes the line a function of the claim."""
        def built(first: str, second: str) -> str:
            state = CognitiveState()
            for handle in (first, second):
                entity = f"mcp.{handle}#r1"
                observe(state, entity, "state", "done")
                state.link(entity, "job:jl-731",
                           evidence=(receipt(handle), DECLARED),
                           authority=EvidenceAuthority.SOURCE)
            line, = section(compile_view(state), FACTS_HEADING)
            return line

        assert built("alpha", "beta") == built("beta", "alpha")

    def test_the_figure_renders_once_at_the_subject(self):
        view = compile_view(linked())
        assert section(view, FACTS_HEADING) == [
            'job:jl-0 · records = 1  [sourced · via mcp.job_status#r0]']

    def test_the_line_is_not_marked_derived(self):
        """`derived` exists to say there is no receipt behind this line.
        There is one, and it is on the line."""
        line, = section(compile_view(linked()), FACTS_HEADING)
        assert DERIVED not in line

    def test_the_band_is_the_link_s_own_grade(self):
        """A subject fact is worth the weaker of the receipt and the link,
        and the link is a platform's word — so a folded line reads
        `sourced` where the receipt line read `verified`. The kernel caps
        it; the view says what the kernel decided."""
        view = compile_view(linked())
        assert "[sourced" in view.text and "verified" not in view.text

    def test_the_header_counts_receipts_and_not_declarations(self):
        """A link's declaration is a leaf of the proof and is emphatically
        not a receipt. Counting the leaves would show a plane's manifest
        as a call the mission made."""
        assert compile_view(linked(2)).receipts == 2

    def test_two_receipts_agreeing_are_one_line_naming_both(self):
        state = CognitiveState()
        for handle in ("r1", "r2"):
            entity = f"mcp.job_status#{handle}"
            observe(state, entity, "state", "done")
            state.link(entity, "job:jl-731",
                       evidence=(receipt(handle), DECLARED),
                       authority=EvidenceAuthority.SOURCE)
        line, = section(compile_view(state), FACTS_HEADING)
        assert line.endswith("[sourced · via mcp.job_status#r1, "
                             "mcp.job_status#r2]")

    def test_an_unlinked_receipt_still_renders_as_itself(self):
        state = linked()
        observe(state, "mcp.audit#r9", "checked", 1)
        assert any(line.startswith("mcp.audit#r9")
                   for line in section(compile_view(state), FACTS_HEADING))

    def test_more_receipts_than_the_line_can_name_are_not_folded(self):
        """A fold is honest only while the line that replaces those lines
        can still name every one of them."""
        state = CognitiveState()
        for index in range(VIA_CAP + 2):
            entity = f"mcp.job_status#r{index}"
            observe(state, entity, "state", "done")
            state.link(entity, "job:jl-731", evidence=(receipt(f"r{index}"),),
                       authority=EvidenceAuthority.SOURCE)
        lines = section(compile_view(state), FACTS_HEADING)
        assert MORE.format(count=2) in lines[0]
        assert len([line for line in lines
                    if line.startswith("mcp.job_status#")]) == VIA_CAP + 2

    def test_a_disputed_receipt_fact_keeps_its_own_line(self):
        """Its line carries DISPUTED because something contradicts *it*,
        and the subject copy need not be contested at all — a model's
        claim about one receipt does not reach the projection."""
        state = linked()
        state.declare_field("records", "one")
        state.assert_hypothesis(
            ("mcp.job_status#r0", "records", 99),
            evidence=(EvidenceRef(kind="model", locator="step-2"),),
            authority=EvidenceAuthority.MODEL_HYPOTHESIS)
        lines = section(compile_view(state), FACTS_HEADING)
        assert [line for line in lines
                if line.startswith("mcp.job_status#r0") and DISPUTED in line]

    def test_a_contest_at_the_subject_names_the_call_behind_each_side(self):
        """The finding-D pair: two status tools, one job, two answers. Both
        sides are the same entity, so a reader without the handles is
        looking at `x ⇄ x`."""
        state = CognitiveState()
        state.declare_field("state", "one")
        for handle, value in (("r1", "running"), ("r2", "done")):
            entity = f"mcp.{handle}_tool#{handle}"
            observe(state, entity, "state", value)
            state.link(entity, "job:jl-731", evidence=(receipt(handle),),
                       authority=EvidenceAuthority.SOURCE)
        line, = section(compile_view(state), CONFLICTS_HEADING)
        assert f"[{VIA}mcp.r1_tool#r1]" in line
        assert f"[{VIA}mcp.r2_tool#r2]" in line

    def test_a_confusable_subject_does_not_render_as_its_twin(self):
        """Two subjects whose values differ by a Cyrillic `а` render as
        two different lines. No store can own a table of confusables; a
        view that showed them identically would have a reader deciding
        about identity on a rendering that cannot show the difference."""
        state = CognitiveState()
        for value in ("jl-a", "jl-а"):
            entity = f"mcp.job_status#{value}"
            observe(state, entity, "records", 1)
            state.link(entity, f"job:{value}", evidence=(receipt(value),),
                       authority=EvidenceAuthority.SOURCE)
        lines = section(compile_view(state), FACTS_HEADING)
        assert len(set(lines)) == 2
        assert any("\\u0430" in line for line in lines)

    @pytest.mark.parametrize("budget", [120, 200, 260, 400, 900])
    def test_the_folded_block_is_still_what_brute_force_would_choose(
            self, budget):
        """The oracle, over a folded state: every cut in the documented
        drop order, rendered, and the first that fits. Folding changes
        which lines exist and must not change which of them survive."""
        state = linked(6)
        assert compile_view(state, budget_chars=budget).text \
            == _brute_force(state, budget)

    @pytest.mark.parametrize("budget", [60, 130, 205, 333, 1000])
    def test_and_the_cap_is_never_exceeded(self, budget):
        assert len(compile_view(linked(6), budget_chars=budget).text) <= budget

    def test_the_same_state_folds_to_the_same_bytes(self):
        assert compile_view(linked(3)).digest() \
            == compile_view(linked(3)).digest()


# ── what would answer an owed line ───────────────────────────────────────────


def goal(state: CognitiveState, field: str) -> None:
    """One goal nothing satisfies, so the frontier has a line about it."""
    state.add_goal(("?j", field, "?v"), note=f"{field}_known")


class TestWhatThePlaneSaysWouldAnswerIt:
    """`establishes` and `produces`, in the one place they are read."""

    def test_establishes_names_the_tool(self):
        assert resolvers_of(plane())["state"] == ("job_status",)

    def test_a_product_names_the_call_that_carries_it(self):
        """Not the call that returned the handle: the product arrives
        through `via`, and that is the tool a reader wants named."""
        assert resolvers_of(plane())["label_set"] == ("job_status",)

    def test_a_field_nobody_declared_has_no_resolver(self):
        assert "colour" not in resolvers_of(plane())

    def test_no_declarations_resolve_nothing(self):
        assert resolvers_of(None) == {}

    def test_the_owed_line_carries_the_clause(self):
        state = CognitiveState()
        goal(state, "state")
        line, = section(compile_view(state, resolvers=resolvers_of(plane())),
                        OWED_HEADING)
        assert line.endswith(f"{RESOLVABLE}job_status")

    def test_and_without_resolvers_it_is_the_line_it_was(self):
        state = CognitiveState()
        goal(state, "state")
        line, = section(compile_view(state), OWED_HEADING)
        assert RESOLVABLE not in line

    def test_a_goal_with_a_variable_field_names_nothing(self):
        """A hole a declaration cannot name: nothing says which field is
        missing, so nothing can say what would establish it."""
        state = CognitiveState()
        state.add_goal(("?j", "?f", "?v"), note="anything")
        assert RESOLVABLE not in compile_view(
            state, resolvers=resolvers_of(plane())).text

    def test_the_list_is_capped(self):
        resolvers = {"state": tuple(f"tool_{index}" for index in range(5))}
        state = CognitiveState()
        goal(state, "state")
        line, = section(compile_view(state, resolvers=resolvers), OWED_HEADING)
        assert line.endswith(f"{RESOLVABLE}tool_0, tool_1, tool_2, "
                             f"{MORE.format(count=2)}")

    def test_the_supervisor_quotes_the_line_the_model_read(self, tmp_path):
        """One owner of the spelling, hint included: a review saying what
        has not moved says it in the words the block showed."""
        store = RunStore(tmp_path / "watch")
        run = store.create()
        made = open_shadow(store, run.run_id, compiling=True,
                           cognition_block={"goals": [
                               {"name": "state_known",
                                "pattern": ["?j", "state", "?v"]}]})
        made.declare_plane(plane())
        made.close_step()
        assert made.progress().owed.endswith(f"{RESOLVABLE}job_status")
        assert made.progress().owed in made.compiled_block()

    def test_a_second_plane_replaces_the_first_s_hints(self, tmp_path):
        """A resumed run resolves its plane again. What it steers under is
        what it last resolved — the record keeps both."""
        store = RunStore(tmp_path / "again")
        run = store.create()
        made = open_shadow(store, run.run_id)
        made.declare_plane(plane())
        assert made.resolvers()["state"] == ("job_status",)
        made.declare_plane(plane(manifest={"entries": [
            {"name": "job_status", "identifiers": {"job_id": {"kind": "job"}},
             "establishes": ["state", "colour"]}]}, offered=["job_status"]))
        assert made.resolvers()["colour"] == ("job_status",)


# ── a mission, end to end ────────────────────────────────────────────────────


#: The path is ``result.run_id`` and not ``run_id`` because that is where
#: the field actually is: this server wraps a plain return under ``result``,
#: which is the envelope case the whole path grammar exists for (one real
#: deployment's is ``data.*``).  Declared as the flat name it would bind
#: nothing, the server's published ``outputSchema`` would say so, and the
#: run would start with a discrepancy on the console — which is the feature
#: working, and is why the fixture is written the honest way round.
SKILL = """\
---
name: subjects
when_to_use: A plane that says what its tools are about.
allowed_tools:
  - governed_view
tools:
  entries:
    - name: governed_view
      identifiers:
        result.run_id: {kind: run}
      establishes: [records]
---

# Subjects

Read the governed view.
"""

VIEW = json.dumps({"tool": "mcp.governed_view",
                   "arguments": {"run_id": "asset.5f21", "section": "totals"}})
ANSWER = json.dumps({"answer": "The view holds 12481 records, asset.5f21."})


class TestAMissionSeesWhatItsReceiptsAreAbout:
    """The whole path, once: a manifest declares, a server answers, the
    block the model reads names the subject and the call behind it.

    One test with several assertions rather than five runs of a real
    subprocess MCP server, which is the idiom
    ``tests/test_cognition_compiled_context.py`` keeps for the same
    reason.
    """

    def test_two_calls_to_one_run_id_become_one_subject_in_the_block(
            self, elf, tmp_path):
        from tests.test_cli_mission_skill import run_cli as mission_run_cli
        from tests.test_cognition_compiled_context import (blocks_in,
                                                           model_calls)
        from core.runtime.cognition import REASONING_LOG, replay_reasoning

        MockClass, agent = elf
        path = tmp_path / "SKILL.md"
        path.write_text(SKILL, encoding="utf-8")
        queue = [VIEW, VIEW, ANSWER]
        agent.client.chat.side_effect = lambda **kw: queue.pop(0)
        mission_run_cli(MockClass, "--skill", str(path),
                        "--compiled-context")

        store = RunStore(tmp_path / "runs")
        listed = store.list()
        assert len(listed) == 1
        state = replay_reasoning(store.directory(listed[0].run_id)
                                 / REASONING_LOG)
        assert {link.subject for link in state.links()} == {"run:asset.5f21"}
        # The join: one subject, one figure, both receipts behind it.
        assert state.claim(("run:asset.5f21", "records", 12481)) is not None

        block = blocks_in(model_calls(tmp_path)[-1])[-1]
        text = str(block["content"])
        assert "run:asset.5f21 · records = 12481" in text
        assert f"{VIA}mcp.governed_view#r1, mcp.governed_view#r2" in text
        # The receipt's own line is gone: one figure, one line.
        assert "mcp.governed_view#r1 · records" not in text
