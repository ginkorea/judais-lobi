# tests/test_cognition_kernel.py — the walls, the closure, and the frontier

"""What the epistemic kernel refuses, what it derives, and what it still owes.

Five things are checked here and they are not the same thing.

**That the authority walls hold in both directions.**  Model evidence cannot
become an ``OBSERVED`` proposition and a ``PROPOSED`` rule derives nothing —
but also, a receipt cannot be filed as a hypothesis and a held hypothesis *is*
promoted when an observation arrives.  A wall tested in one direction only is
a wall somebody routes around by spelling the call differently.

**That the derivation is a proof and not a claim about one.**
:meth:`~core.cognition.state.CognitiveState.prove` is asserted as a whole
tree, down to the evidence at the leaves.  A test that checked only "it
returned something with steps" would pass against an engine that had lost a
premise, and a lost premise is invisible in the conclusion.

**That nothing wins silently.**  Two propositions giving one field two values
leave *both* contested, and a conclusion whose every proof has died falls with
them.  The failure this guards is a store that quietly prefers the newer or
the better-authorised claim — which would be the one judgement it is least
equipped to make, made without saying so.

**That the frontier is computed.**  Nobody authors an obligation.  The store
reads a goal against its rules against what it holds, and the premise it
cannot satisfy is the answer to "what next" — the inversion the whole 2.0 arc
is built on.

**That a link carries facts to a subject without rewriting them.**  Two
receipts are about one job only because somebody declared a key to be an
identifier; the store then *projects*, so the subject's fact is derived, its
proof walks back to the call that showed it, and two receipts that really
disagree contest at the subject while both receipts stay live.  The property
the projection engine has to be held to is order-independence: a link arrives
before or after the facts it carries, and a store that answered differently
depending on which would be answering about its own loop.

Replay, the event log and the incrementality of closure are in
``tests/test_cognition_replay.py``.
"""

import pytest

from core.cognition import (AUTHORITY_RANK, CONTRADICTION_KINDS,
                            HYPOTHESIS_AUTHORITIES,
                            OBSERVATION_AUTHORITIES, PROJECTION_RULE,
                            PROJECTION_RULE_ID, RECEIPT_MARKER, SUBJECT_CAP,
                            SUBJECT_SEPARATOR, TRUSTED_RULE_AUTHORITIES,
                            AuthorityRefused, CognitionError, CognitiveState,
                            EvidenceAuthority, EvidenceRef, ObligationState,
                            PropositionStatus, RuleAuthority, RuleMalformed,
                            UnknownId, check_subject, subject_entity,
                            subject_parts, value_tag)

RECEIPT = EvidenceRef(kind="receipt", locator="seq:1", note="read_file")
OTHER = EvidenceRef(kind="receipt", locator="seq:2")
EXTRACTED = EvidenceRef(kind="extraction", locator="turn:3")
#: What a link's evidence actually is: the declaration that said a key was an
#: identifier. Kept distinct from a receipt ref so a proof's leaves can be
#: read for *which* of the two answers "why do we think this call was about
#: this job".
DECLARED = EvidenceRef(kind="declaration", locator="job_status.job_id")


def door(ref, authority=EvidenceAuthority.SOURCE):
    """A ref as the store holds it: stamped by the door that took it.

    Written out at every call site below rather than hidden in a comparison
    helper. What door a ref came through is the fact `EvidenceRef.authority`
    exists to keep, and a test that shrugged it off with a loose comparison
    would be the first place it went missing.
    """
    return ref.stamped(authority)


# The ancestry example from the roadmap's own thought experiment: two
# premises, two shared variables, one conclusion that neither premise states.
# `store_with_controls` builds it, and the classes that want a *different*
# shape — alternative proofs, cycles, mid-pass contestation — write their own.
CONTROLS_HEAD = ("?actor", "controls", "?c")
CONTROLS_BODY = [("?actor", "admin_access", "?c"),
                 ("?actor", "payment_link", "?c")]


def store_with_controls(authority=RuleAuthority.DOMAIN):
    state = CognitiveState()
    rid = state.add_rule("controls", CONTROLS_HEAD, CONTROLS_BODY, authority)
    return state, rid


# ---------------------------------------------------------------------------
# The authority walls
# ---------------------------------------------------------------------------

class TestTheObservationDoorIsClosedToTheModel:
    """A wrong proposition in a store is worse than a wrong sentence in a
    transcript: deterministic machinery then derives from it with confidence.
    So the door an observation comes through takes two authorities and the
    other three are a different door."""

    @pytest.mark.parametrize("authority", HYPOTHESIS_AUTHORITIES)
    def test_model_authority_cannot_assert_an_observation(self, authority):
        state = CognitiveState()
        with pytest.raises(AuthorityRefused):
            state.assert_observation(("alice", "role", "admin"),
                                     evidence=[EXTRACTED],
                                     authority=authority)
        assert state.propositions() == ()

    @pytest.mark.parametrize("authority", OBSERVATION_AUTHORITIES)
    def test_receipt_authority_is_what_an_observation_takes(self, authority):
        state = CognitiveState()
        pid = state.assert_observation(("alice", "role", "admin"),
                                       evidence=[RECEIPT],
                                       authority=authority)
        assert state.proposition(pid).status is PropositionStatus.OBSERVED
        assert state.proposition(pid).authority is authority

    @pytest.mark.parametrize("authority", OBSERVATION_AUTHORITIES)
    def test_a_receipt_cannot_be_filed_as_a_hypothesis(self, authority):
        """The wall's other face. A caller reaching for `assert_hypothesis`
        with deterministic evidence has confused the doors, and silently
        downgrading it would lose the one fact the store is for."""
        state = CognitiveState()
        with pytest.raises(AuthorityRefused):
            state.assert_hypothesis(("alice", "role", "admin"),
                                    evidence=[RECEIPT], authority=authority)

    def test_the_two_doors_share_no_authority(self):
        """Structural, not a spot check: the wall is the fact that the union
        of the two tuples is the whole enum and the intersection is empty."""
        observation = set(OBSERVATION_AUTHORITIES)
        hypothesis = set(HYPOTHESIS_AUTHORITIES)
        assert observation & hypothesis == set()
        assert observation | hypothesis == set(EvidenceAuthority)

    def test_a_hypothesis_lands_hypothesized(self):
        state = CognitiveState()
        pid = state.assert_hypothesis(("alice", "role", "admin"),
                                      evidence=[EXTRACTED])
        assert state.proposition(pid).status is PropositionStatus.HYPOTHESIZED

    def test_an_observation_promotes_a_held_hypothesis(self):
        """The wall is about authority, not about never changing our mind.
        Evidence good enough for the other door promotes what the model
        guessed — that direction is allowed and this pins it."""
        state = CognitiveState()
        guess = state.assert_hypothesis(("alice", "role", "admin"),
                                        evidence=[EXTRACTED])
        seen = state.assert_observation(("alice", "role", "admin"),
                                        evidence=[RECEIPT])
        assert seen == guess, "one claim, not two"
        prop = state.proposition(guess)
        assert prop.status is PropositionStatus.OBSERVED
        assert prop.authority is EvidenceAuthority.SOURCE
        assert set(prop.evidence) == {door(EXTRACTED,
                                            EvidenceAuthority.MODEL_HYPOTHESIS),
                                      door(RECEIPT)}, \
            "the union keeps both refs AND which door each came through" 

    def test_a_hypothesis_does_not_demote_a_held_observation(self):
        state = CognitiveState()
        seen = state.assert_observation(("alice", "role", "admin"),
                                        evidence=[RECEIPT])
        state.assert_hypothesis(("alice", "role", "admin"),
                                evidence=[EXTRACTED])
        prop = state.proposition(seen)
        assert prop.status is PropositionStatus.OBSERVED
        assert prop.authority is EvidenceAuthority.SOURCE


class TestEveryPropositionTracesToSomething:
    def test_a_proposition_with_no_evidence_is_refused(self):
        state = CognitiveState()
        with pytest.raises(CognitionError):
            state.assert_observation(("alice", "role", "admin"))

    def test_neither_a_triple_nor_text_is_not_a_proposition(self):
        state = CognitiveState()
        with pytest.raises(CognitionError):
            state.assert_observation(evidence=[RECEIPT])

    def test_text_carries_what_no_triple_can(self):
        state = CognitiveState()
        pid = state.assert_observation(
            text="the deployment declined, citing a policy with no field",
            evidence=[RECEIPT])
        assert state.proposition(pid).triple is None
        assert state.proposition(pid).text.startswith("the deployment")

    def test_a_triple_and_a_text_may_both_be_present(self):
        state = CognitiveState()
        pid = state.assert_observation(("job-7", "state", "failed"),
                                       text="OOM on the second shard",
                                       evidence=[RECEIPT])
        prop = state.proposition(pid)
        assert prop.triple == ("job-7", "state", "failed")
        assert prop.text == "OOM on the second shard"

    def test_a_variable_cannot_be_asserted(self):
        """`?name` is the variable spelling. A proposition is ground."""
        state = CognitiveState()
        with pytest.raises(CognitionError):
            state.assert_observation(("?who", "role", "admin"),
                                     evidence=[RECEIPT])

    def test_a_value_the_log_cannot_carry_is_refused(self):
        state = CognitiveState()
        with pytest.raises(CognitionError):
            state.assert_observation(("alice", "roles", ["admin"]),
                                     evidence=[RECEIPT])


class TestAProposedRuleDerivesNothing:
    """A model may propose a rule. Proposing one never makes it true.

    The refusal is structural — closure reads ``participates_in_closure`` and
    there is no second path — so these tests come at it from both ends: the
    rule is stored and visible, and nothing at all follows from it until a
    caller who is not the model names an authority.
    """

    def test_the_default_authority_is_proposed(self):
        state = CognitiveState()
        rid = state.add_rule("controls", CONTROLS_HEAD, CONTROLS_BODY)
        assert state.rule(rid).authority is RuleAuthority.PROPOSED
        assert not state.rule(rid).participates_in_closure

    def test_a_proposed_rule_is_stored_and_derives_nothing(self):
        state, _ = store_with_controls(RuleAuthority.PROPOSED)
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        state.assert_observation(("alice", "payment_link", "acct-9"),
                                 evidence=[RECEIPT])
        state.derive()
        assert len(state.rules()) == 1
        assert state.derivations() == ()
        assert [p.triple for p in state.propositions()] == [
            ("alice", "admin_access", "acct-9"),
            ("alice", "payment_link", "acct-9")]

    def test_promotion_derives_from_what_was_already_held(self):
        """The promotion is a delta of its own: the facts arrived first and
        the rule has to be run against all of them when it becomes true."""
        state, rid = store_with_controls(RuleAuthority.PROPOSED)
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        state.assert_observation(("alice", "payment_link", "acct-9"),
                                 evidence=[RECEIPT])
        state.derive()
        assert state.derivations() == ()
        state.promote_rule(rid, RuleAuthority.DOMAIN)
        state.derive()
        assert [d.rule for d in state.derivations()] == [rid]
        assert ("alice", "controls", "acct-9") in [
            p.triple for p in state.propositions()]

    def test_promoting_to_proposed_is_refused(self):
        state, rid = store_with_controls(RuleAuthority.PROPOSED)
        with pytest.raises(AuthorityRefused):
            state.promote_rule(rid, RuleAuthority.PROPOSED)
        assert state.rule(rid).authority is RuleAuthority.PROPOSED

    def test_promoting_a_rule_nobody_added_is_refused(self):
        state = CognitiveState()
        with pytest.raises(UnknownId):
            state.promote_rule("r9", RuleAuthority.SYSTEM)

    def test_proposed_is_exactly_the_authority_left_out(self):
        assert set(TRUSTED_RULE_AUTHORITIES) | {RuleAuthority.PROPOSED} == \
            set(RuleAuthority)
        assert RuleAuthority.PROPOSED not in TRUSTED_RULE_AUTHORITIES


class TestARuleHasToBeAbleToRun:
    def test_an_empty_body_is_refused(self):
        state = CognitiveState()
        with pytest.raises(RuleMalformed):
            state.add_rule("bare", ("a", "b", "c"), [],
                           RuleAuthority.SYSTEM)

    def test_a_head_variable_the_body_never_binds_is_refused(self):
        state = CognitiveState()
        with pytest.raises(RuleMalformed):
            state.add_rule("loose", ("?actor", "controls", "?mystery"),
                           [("?actor", "admin_access", "acct-9")],
                           RuleAuthority.SYSTEM)

    def test_a_pattern_is_three_terms(self):
        state = CognitiveState()
        with pytest.raises(RuleMalformed):
            state.add_rule("short", ("?a", "controls"),
                           [("?a", "admin_access", "x")],
                           RuleAuthority.SYSTEM)


# ---------------------------------------------------------------------------
# Closure
# ---------------------------------------------------------------------------

class TestDerivationAcrossTwoPremises:
    """The roadmap's own example: ``controls`` follows from ``admin_access``
    and ``payment_link`` over the same actor and the same account, and from
    neither of them alone."""

    def test_both_premises_derive_the_conclusion(self):
        state, rid = store_with_controls()
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        state.assert_observation(("alice", "payment_link", "acct-9"),
                                 evidence=[RECEIPT])
        derived = state.derive()
        assert len(derived) == 1
        prop = state.proposition(derived[0])
        assert prop.triple == ("alice", "controls", "acct-9")
        assert prop.status is PropositionStatus.DERIVED
        assert prop.derivation == state.derivations()[0].id

    def test_one_premise_derives_nothing(self):
        state, _ = store_with_controls()
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        assert state.derive() == ()
        assert state.derivations() == ()

    def test_the_shared_variables_have_to_agree(self):
        """Two premises about different actors, or different accounts, are
        not a match. This is the repeated-variable check, and without it the
        rule concludes about a pair nobody observed."""
        state, _ = store_with_controls()
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        state.assert_observation(("bob", "payment_link", "acct-9"),
                                 evidence=[RECEIPT])
        state.assert_observation(("alice", "payment_link", "acct-1"),
                                 evidence=[RECEIPT])
        assert state.derive() == ()

    def test_a_conclusion_carries_the_weakest_premise_authority(self):
        """A chain is worth its worst link. Rounding it up is how source
        evidence would come out looking deterministic."""
        state, _ = store_with_controls()
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT],
                                 authority=EvidenceAuthority.DETERMINISTIC)
        state.assert_observation(("alice", "payment_link", "acct-9"),
                                 evidence=[RECEIPT],
                                 authority=EvidenceAuthority.SOURCE)
        derived, = state.derive()
        assert state.proposition(derived).authority is EvidenceAuthority.SOURCE

    def test_two_deterministic_premises_stay_deterministic(self):
        state, _ = store_with_controls()
        for field in ("admin_access", "payment_link"):
            state.assert_observation(("alice", field, "acct-9"),
                                     evidence=[RECEIPT],
                                     authority=EvidenceAuthority.DETERMINISTIC)
        derived, = state.derive()
        assert state.proposition(derived).authority is \
            EvidenceAuthority.DETERMINISTIC

    def test_a_hypothesis_is_not_a_premise(self):
        """v1 bound, pinned so it is a decision and not an accident:
        ``HYPOTHESIZED`` propositions are stored and reported and do not
        derive. Hypothetical closure is a later phase with its own evidence."""
        state, _ = store_with_controls()
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        state.assert_hypothesis(("alice", "payment_link", "acct-9"),
                                evidence=[EXTRACTED])
        assert state.derive() == ()

    def test_closure_cascades_to_fixpoint(self):
        state, _ = store_with_controls()
        state.add_rule("risky", ("?a", "risky", "?c"),
                       [("?a", "controls", "?c"), ("?c", "flagged", True)],
                       RuleAuthority.SYSTEM)
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        state.assert_observation(("alice", "payment_link", "acct-9"),
                                 evidence=[RECEIPT])
        state.assert_observation(("acct-9", "flagged", True),
                                 evidence=[RECEIPT])
        state.derive()
        triples = [p.triple for p in state.propositions()]
        assert ("alice", "controls", "acct-9") in triples
        assert ("alice", "risky", "acct-9") in triples


class TestAlternativeProofs:
    """Two ways to the same conclusion are two derivations and one
    proposition. A duplicate proposition would be a second owner of a fact
    the store already holds — and the contradiction machinery would then find
    them agreeing with each other, forever."""

    def _two_ways(self):
        state = CognitiveState()
        state.add_rule("by_admin", ("?a", "controls", "?c"),
                       [("?a", "admin_access", "?c")], RuleAuthority.DOMAIN)
        state.add_rule("by_owner", ("?a", "controls", "?c"),
                       [("?a", "owns", "?c")], RuleAuthority.DOMAIN)
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        state.assert_observation(("alice", "owns", "acct-9"),
                                 evidence=[OTHER])
        state.derive()
        return state

    def test_one_proposition_two_derivations(self):
        state = self._two_ways()
        controls = [p for p in state.propositions()
                    if p.field == "controls"]
        assert len(controls) == 1, [p.render() for p in controls]
        assert len(state.derivations_for(controls[0].id)) == 2

    def test_the_proposition_of_record_keeps_the_first_proof(self):
        state = self._two_ways()
        controls, = [p for p in state.propositions() if p.field == "controls"]
        proofs = state.derivations_for(controls.id)
        assert controls.derivation == proofs[0].id
        assert state.rule(proofs[0].rule).name == "by_admin"

    def test_prove_shows_both_routes(self):
        state = self._two_ways()
        controls, = [p for p in state.propositions() if p.field == "controls"]
        proof = state.prove(controls.id)
        assert [step.rule_name for step in proof.steps] == ["by_admin",
                                                            "by_owner"]


class TestProveIsTheWholeTree:
    def test_the_dag_is_asserted_down_to_the_evidence(self):
        """Not "it returned something with steps". A lost premise does not
        show in the conclusion, so the whole tree is written out here."""
        state, controls_rule = store_with_controls()
        risky_rule = state.add_rule(
            "risky", ("?a", "risky", "?c"),
            [("?a", "controls", "?c"), ("?c", "flagged", True)],
            RuleAuthority.SYSTEM)
        admin = state.assert_observation(("alice", "admin_access", "acct-9"),
                                         evidence=[RECEIPT])
        pay = state.assert_observation(("alice", "payment_link", "acct-9"),
                                       evidence=[OTHER])
        flag = state.assert_observation(("acct-9", "flagged", True),
                                        evidence=[RECEIPT])
        state.derive()
        risky, = [p for p in state.propositions() if p.field == "risky"]
        controls, = [p for p in state.propositions() if p.field == "controls"]

        proof = state.prove(risky.id)
        assert proof.proposition == risky.id
        assert proof.status is PropositionStatus.DERIVED
        assert proof.evidence == (), "a derived proposition's evidence is at " \
                                     "its leaves, not on it"
        step, = proof.steps
        assert (step.rule, step.rule_name) == (risky_rule, "risky")

        controls_proof, flag_proof = step.premises
        assert flag_proof.proposition == flag
        assert flag_proof.steps == ()
        assert flag_proof.evidence == (door(RECEIPT),)

        assert controls_proof.proposition == controls.id
        inner, = controls_proof.steps
        assert (inner.rule, inner.rule_name) == (controls_rule, "controls")
        assert [leaf.proposition for leaf in inner.premises] == [admin, pay]
        assert [leaf.evidence for leaf in inner.premises] == [(door(RECEIPT),),
                                                              (door(OTHER),)]
        assert all(leaf.steps == () for leaf in inner.premises)

    def test_a_cycle_stops_rather_than_recursing(self):
        state = CognitiveState()
        state.add_rule("there", ("?a", "there", "?c"),
                       [("?a", "back", "?c")], RuleAuthority.SYSTEM)
        state.add_rule("back", ("?a", "back", "?c"),
                       [("?a", "there", "?c")], RuleAuthority.SYSTEM)
        state.assert_observation(("alice", "there", "acct-9"),
                                 evidence=[RECEIPT])
        state.derive()
        back, = [p for p in state.propositions() if p.field == "back"]

        def walk(proof, depth=0):
            assert depth < 10, "the walk did not terminate"
            yield proof
            for step in proof.steps:
                for premise in step.premises:
                    yield from walk(premise, depth + 1)

        assert any(node.cyclic for node in walk(state.prove(back.id)))

    def test_proving_something_nobody_asserted_is_refused(self):
        state = CognitiveState()
        with pytest.raises(UnknownId):
            state.prove("p1")


class TestAnObservationOutranksItsOwnDerivation:
    def test_a_derived_triple_later_observed_stays_observed(self):
        state, _ = store_with_controls()
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        state.assert_observation(("alice", "payment_link", "acct-9"),
                                 evidence=[RECEIPT])
        state.derive()
        seen = state.assert_observation(("alice", "controls", "acct-9"),
                                        evidence=[OTHER])
        prop = state.proposition(seen)
        assert prop.status is PropositionStatus.OBSERVED
        assert prop.evidence == (door(OTHER),)
        assert len(state.derivations_for(seen)) == 1, \
            "the proof is still on the record; only the status outranks it"


# ---------------------------------------------------------------------------
# Contradiction
# ---------------------------------------------------------------------------

class TestNothingWinsSilently:
    def _collision(self):
        state = CognitiveState()
        # A job has one elapsed time. Declared, because an undeclared field
        # is `many` and nothing about a triple says which a field is.
        state.declare_field("total_s", "one")
        first = state.assert_observation(("job-7", "total_s", 154.024),
                                         evidence=[RECEIPT])
        second = state.assert_observation(("job-7", "total_s", 186.7),
                                          evidence=[OTHER],
                                          authority=
                                          EvidenceAuthority.DETERMINISTIC)
        state.derive()
        return state, first, second

    def test_both_sides_are_contested(self):
        state, first, second = self._collision()
        assert state.proposition(first).status is PropositionStatus.CONTESTED
        assert state.proposition(second).status is PropositionStatus.CONTESTED

    def test_neither_side_stays_live(self):
        """The mutation this is here for: a store that left the newer, or the
        better-authorised, one live would pass every other test in this file
        and would be making the judgement it is least able to make."""
        state, first, second = self._collision()
        assert not state.proposition(first).live
        assert not state.proposition(second).live
        assert state.propositions(live=True) == ()

    def test_the_contradiction_names_both_sides(self):
        state, first, second = self._collision()
        clash, = state.contradictions()
        assert clash.kind == "value"
        assert {clash.left, clash.right} == {first, second}

    def test_the_same_value_twice_is_one_claim_and_no_clash(self):
        state = CognitiveState()
        state.declare_field("total_s", "one")
        first = state.assert_observation(("job-7", "total_s", 154.024),
                                         evidence=[RECEIPT])
        again = state.assert_observation(("job-7", "total_s", 154.024),
                                         evidence=[OTHER])
        assert again == first
        assert state.contradictions() == ()
        assert state.proposition(first).evidence == (door(RECEIPT),
                                                     door(OTHER))

    def test_a_refutation_is_a_contradiction_object(self):
        state = CognitiveState()
        pid = state.assert_observation(("job-7", "state", "running"),
                                       evidence=[RECEIPT])
        cid = state.refute(pid, evidence=[OTHER])
        clash, = state.contradictions()
        assert clash.id == cid
        assert clash.kind == "refutation"
        assert clash.left == pid
        assert clash.right is None
        assert clash.evidence == (OTHER,)
        assert state.proposition(pid).status is PropositionStatus.REFUTED

    def test_a_refutation_needs_evidence(self):
        state = CognitiveState()
        pid = state.assert_observation(("job-7", "state", "running"),
                                       evidence=[RECEIPT])
        with pytest.raises(CognitionError):
            state.refute(pid)

    def test_refuting_something_nobody_asserted_is_refused(self):
        state = CognitiveState()
        with pytest.raises(UnknownId):
            state.refute("p1", evidence=[OTHER])


class TestARetractedPremiseTakesItsConclusionWithIt:
    """v1's retraction rule, written down in
    :mod:`core.cognition.state`: a derived proposition whose *every*
    derivation now rests on something not live is retracted to ``CONTESTED``
    with a contradiction naming the dead premise. It cascades."""

    def test_the_only_proof_dying_retracts_the_conclusion(self):
        state, _ = store_with_controls()
        admin = state.assert_observation(("alice", "admin_access", "acct-9"),
                                         evidence=[RECEIPT])
        state.assert_observation(("alice", "payment_link", "acct-9"),
                                 evidence=[RECEIPT])
        derived, = state.derive()
        state.refute(admin, evidence=[OTHER])
        assert state.proposition(derived).status is PropositionStatus.CONTESTED
        dead, = [c for c in state.contradictions()
                 if c.kind == "dead_premise"]
        assert (dead.left, dead.right) == (derived, admin)

    def test_a_live_alternative_proof_keeps_the_conclusion_standing(self):
        state = CognitiveState()
        state.add_rule("by_admin", ("?a", "controls", "?c"),
                       [("?a", "admin_access", "?c")], RuleAuthority.DOMAIN)
        state.add_rule("by_owner", ("?a", "controls", "?c"),
                       [("?a", "owns", "?c")], RuleAuthority.DOMAIN)
        admin = state.assert_observation(("alice", "admin_access", "acct-9"),
                                         evidence=[RECEIPT])
        state.assert_observation(("alice", "owns", "acct-9"),
                                 evidence=[OTHER])
        state.derive()
        controls, = [p for p in state.propositions() if p.field == "controls"]
        state.refute(admin, evidence=[OTHER])
        assert state.proposition(controls.id).status is \
            PropositionStatus.DERIVED
        assert [c.kind for c in state.contradictions()] == ["refutation"]

    def test_the_cascade_reaches_the_second_level(self):
        state, _ = store_with_controls()
        state.add_rule("risky", ("?a", "risky", "?c"),
                       [("?a", "controls", "?c"), ("?c", "flagged", True)],
                       RuleAuthority.SYSTEM)
        admin = state.assert_observation(("alice", "admin_access", "acct-9"),
                                         evidence=[RECEIPT])
        state.assert_observation(("alice", "payment_link", "acct-9"),
                                 evidence=[RECEIPT])
        state.assert_observation(("acct-9", "flagged", True),
                                 evidence=[RECEIPT])
        state.derive()
        risky, = [p for p in state.propositions() if p.field == "risky"]
        state.refute(admin, evidence=[OTHER])
        assert state.proposition(risky.id).status is PropositionStatus.CONTESTED

    def test_a_premise_contested_mid_pass_derives_nothing_after_it(self):
        """The one this file did not cover, and the bug it did not catch.

        Closure builds the delta's pool of live propositions once, at the top
        of a pass, and then runs several rules against it. A conclusion drawn
        by the *first* rule can collide with something in that pool and leave
        both sides CONTESTED — so by the time the third rule reads the pool,
        one of its members is a proposition the store has already refused to
        believe. Handing it over anyway derived from a contested premise, and
        because the retraction cascade had already run when the collision
        happened, nothing came back for it: a live DERIVED proposition whose
        only proof rests on something contested, with no `dead_premise`
        contradiction anywhere on the record.

        Here, `owner=alice` is observed; a rule derives `owner=bob` from
        `lead=bob` in the same pass, contesting both; and a second rule over
        `owner` must find nothing left to work with.

        **The rules are flushed before the observations arrive**, and that is
        not tidiness. A rule that is itself part of the delta is run against
        the whole store with no pinned pool at all, so the path this test
        exists for is only reached once the rules have stopped being new —
        which is every pass after the first, i.e. the entire life of a
        mission. Written the other way round the test passes against the bug.
        """
        state = self._two_rules_over_owner()
        alice = state.assert_observation(("job-7", "owner", "alice"),
                                         evidence=[RECEIPT])
        state.assert_observation(("job-7", "lead", "bob"), evidence=[OTHER])
        state.derive()

        assert state.proposition(alice).status is PropositionStatus.CONTESTED
        escalated = [p for p in state.propositions() if p.field == "escalated"]
        assert escalated == [], (
            "a conclusion was drawn from a premise the store had already "
            f"contested: {[p.render() for p in escalated]}")

    @staticmethod
    def _two_rules_over_owner():
        state = CognitiveState()
        state.declare_field("owner", "one")
        state.add_rule("lead_owns", ("?j", "owner", "?p"),
                       [("?j", "lead", "?p")], RuleAuthority.DOMAIN)
        state.add_rule("owned_is_escalated", ("?j", "escalated", True),
                       [("?j", "owner", "?p")], RuleAuthority.DOMAIN)
        state.add_rule("escalated_is_urgent", ("?j", "urgent", True),
                       [("?j", "escalated", True)], RuleAuthority.DOMAIN)
        state.derive()
        return state

    def test_nothing_live_ever_rests_on_something_that_is_not(self):
        """The invariant the case above violates, stated as itself so the
        next engine change is measured against the property and not only
        against the one arrangement that exposed it."""
        state = self._two_rules_over_owner()
        state.assert_observation(("job-7", "owner", "alice"),
                                 evidence=[RECEIPT])
        state.assert_observation(("job-7", "lead", "bob"), evidence=[OTHER])
        state.derive()
        assert state.contradictions(), "nothing collided; this proves nothing"
        for prop in state.propositions(live=True):
            for proof in state.derivations_for(prop.id):
                assert all(state.proposition(premise).live
                           for premise in proof.premises), \
                    f"{prop.render()} stands on a premise that does not"

    def test_a_value_collision_retracts_what_rested_on_it(self):
        state, _ = store_with_controls()
        state.declare_field("admin_access", "one")
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        state.assert_observation(("alice", "payment_link", "acct-9"),
                                 evidence=[RECEIPT])
        derived, = state.derive()
        state.assert_observation(("alice", "admin_access", "acct-1"),
                                 evidence=[OTHER])
        state.derive()
        assert state.proposition(derived).status is PropositionStatus.CONTESTED


# ---------------------------------------------------------------------------
# Obligations
# ---------------------------------------------------------------------------

class TestTheFrontierIsComputed:
    """Nobody authors an obligation. The store reads a goal against its rules
    against what it holds, and every premise it cannot satisfy is one — which
    is the inversion the arc is built on: the runtime stops asking the model
    what to do next and starts telling it what is missing."""

    def test_the_unsatisfied_premise_is_the_obligation(self):
        """The roadmap's own example: one premise satisfied, one not."""
        state, rid = store_with_controls()
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        goal = state.add_goal(("?who", "controls", "acct-9"))
        frontier = state.frontier()
        assert len(frontier) == 1
        owed, = frontier
        assert owed.pattern == ("alice", "payment_link", "acct-9")
        assert owed.state is ObligationState.OPEN
        assert (owed.goal, owed.rule, owed.position) == (goal, rid, 1)

    def test_the_satisfied_premise_is_on_the_ledger_as_resolved(self):
        state, _ = store_with_controls()
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        state.add_goal(("?who", "controls", "acct-9"))
        states = [o.state for o in state.obligations()]
        assert states == [ObligationState.RESOLVED, ObligationState.OPEN]

    def test_an_obligation_is_as_concrete_as_the_store_allows(self):
        """``?actor`` is bound by the premise that *is* satisfied, so the
        obligation names alice rather than asking about anybody. That is the
        whole value of computing it rather than asking the model."""
        state, _ = store_with_controls()
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        state.add_goal(("?who", "controls", "acct-9"))
        owed, = state.frontier()
        assert owed.pattern[0] == "alice"

    def test_a_satisfied_goal_owes_nothing(self):
        state, _ = store_with_controls()
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        state.assert_observation(("alice", "payment_link", "acct-9"),
                                 evidence=[RECEIPT])
        state.add_goal(("?who", "controls", "acct-9"))
        assert state.frontier() == ()
        assert state.obligations() == ()
        assert state.next_obligation() is None

    def test_a_goal_no_rule_answers_is_its_own_obligation(self):
        state = CognitiveState()
        state.add_goal(("acct-9", "owner", "?who"))
        owed, = state.frontier()
        assert owed.rule is None
        assert owed.pattern == ("acct-9", "owner", "?who")
        assert owed.state is ObligationState.OPEN

    def test_a_proposed_rule_owes_nothing(self):
        """The wall again, from the planning side. An untrusted rule must not
        be able to put work on the frontier either — that would be a model
        setting the runtime's agenda by writing a clause."""
        state, _ = store_with_controls(RuleAuthority.PROPOSED)
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        state.add_goal(("?who", "controls", "acct-9"))
        owed, = state.frontier()
        assert owed.rule is None, "an untrusted rule contributed a premise"

    def test_a_premise_that_cannot_be_stated_yet_is_blocked(self):
        """The second premise's entity comes from the first premise's value.
        With the first unsatisfied there is nothing to name, so the second is
        BLOCKED and depends on it."""
        state = CognitiveState()
        rid = state.add_rule(
            "escalates", ("?a", "escalates", "?c"),
            [("?a", "delegate", "?b"), ("?b", "admin_access", "?c")],
            RuleAuthority.DOMAIN)
        state.add_goal(("alice", "escalates", "acct-9"))
        first, second = state.frontier()
        assert first.state is ObligationState.OPEN
        assert first.pattern == ("alice", "delegate", "?b")
        assert second.state is ObligationState.BLOCKED
        assert second.depends_on == (first.id,)
        assert second.rule == rid

    def test_next_obligation_takes_the_workable_one_first(self):
        state = CognitiveState()
        state.add_rule(
            "escalates", ("?a", "escalates", "?c"),
            [("?a", "delegate", "?b"), ("?b", "admin_access", "?c")],
            RuleAuthority.DOMAIN)
        state.add_goal(("alice", "escalates", "acct-9"))
        chosen = state.next_obligation()
        assert chosen.state is ObligationState.OPEN
        assert chosen.depends_on == ()
        assert chosen.id == state.frontier()[0].id

    def test_computation_order_breaks_the_tie(self):
        """Two obligations, neither blocked. The tie-break is the documented
        computation order — goal insertion, then rule, then body position —
        and not anything about how interesting either one looks."""
        state = CognitiveState()
        state.add_rule("controls", CONTROLS_HEAD, CONTROLS_BODY,
                       RuleAuthority.DOMAIN)
        first = state.add_goal(("alice", "controls", "acct-9"))
        state.add_goal(("bob", "controls", "acct-1"))
        chosen = state.next_obligation()
        assert chosen.goal == first
        assert chosen.position == 0

    # Two facts about a branching premise, deliberately: `?actor` is bound
    # twice, so the rule owes one `payment_link` per actor and the question
    # "in what order" has a real answer to pin.
    BRANCHING = [("alice", "admin_access", "acct-9"),
                 ("bob", "admin_access", "acct-9"),
                 ("bob", "payment_link", "acct-1")]

    def _owed(self, facts):
        state, _ = store_with_controls()
        for triple in facts:
            state.assert_observation(triple, evidence=[RECEIPT])
        state.add_goal(("?who", "controls", "acct-9"))
        return [o.id for o in state.frontier()]

    def test_what_is_owed_does_not_depend_on_observation_order(self):
        """Obligation ids are content-addressed — goal, rule, body position
        and the pattern as far as it resolves — so two stores holding the
        same facts owe the same things under the same names however those
        facts arrived."""
        forward = self._owed(self.BRANCHING)
        backward = self._owed(list(reversed(self.BRANCHING)))
        assert len(forward) == 2, forward
        assert set(forward) == set(backward)

    def test_the_order_they_are_offered_in_follows_the_store(self):
        """And here is what IS order-dependent, pinned rather than wished
        away. When one premise matches several propositions the branch order
        is the order those propositions were asserted in, so the frontier's
        *order* is a fact about this store's history and only its *content*
        is a fact about the world. A caller that needs a stable ordering
        across two differently-built stores sorts by id."""
        forward = self._owed(self.BRANCHING)
        backward = self._owed(list(reversed(self.BRANCHING)))
        assert "alice" in forward[0] and "bob" in forward[1]
        assert "bob" in backward[0] and "alice" in backward[1]

    def test_an_obligation_renders_itself(self):
        state, _ = store_with_controls()
        state.add_goal(("alice", "controls", "acct-9"))
        assert "payment_link" in " ".join(o.render() for o in state.frontier())


class TestTheFrontierPartitionsIntoIndependentGroups:
    """Which of the things still owed could be worked at the same time.

    ROADMAP §2.9.7's *derived swarm*, asked as a question of the store.
    Three things join two obligations and the class checks each on its own,
    because a partition that got independence right for the wrong reason is
    a partition that reports two groups on the day the right reason arrives:
    a dependency, a name they both hold, and a **link**.

    The link is the one that matters most, and it is the one this class
    would silently lose: `mcp.jobs#r3` and `job:jl-731` share no character,
    so a partition that did not go through `link()` would put two workers on
    one job and call them independent.
    """

    def _groups(self, state):
        return [[item.id for item in group]
                for group in state.independent_frontier()]

    def test_an_empty_frontier_has_no_groups(self):
        """`()` and not one empty group: nothing owed is not a group of
        work, and a consumer counting groups would read the one as work."""
        assert CognitiveState().independent_frontier() == ()

    def test_two_goals_about_different_things_are_two_groups(self):
        state = CognitiveState()
        state.add_goal(("job:one", "state", "?s"))
        state.add_goal(("job:two", "state", "?s"))
        assert len(self._groups(state)) == 2

    def test_a_blocked_obligation_is_grouped_with_what_blocks_it(self):
        """The second premise's entity comes from the first premise's value,
        so nobody can work the second until the first is answered — and two
        groups here would be the runtime telling a planner to run them at
        once."""
        state = CognitiveState()
        state.add_rule(
            "escalates", ("?a", "escalates", "?c"),
            [("?a", "delegate", "?b"), ("?b", "admin_access", "?c")],
            RuleAuthority.DOMAIN)
        state.add_goal(("alice", "escalates", "acct-9"))
        assert len(state.frontier()) == 2
        assert len(self._groups(state)) == 1

    def test_two_obligations_naming_one_entity_are_one_group(self):
        state = CognitiveState()
        state.add_goal(("job:one", "state", "?s"))
        state.add_goal(("job:one", "owner", "?o"))
        assert len(self._groups(state)) == 1

    def test_a_link_joins_a_receipt_and_the_subject_it_is_about(self):
        """THE assertion of this class. Two obligations about two names the
        store was *told* are one thing are one group — and the telling is a
        `link`, which is the kernel's only owner of that fact."""
        state = CognitiveState()
        state.assert_observation(("mcp.jobs#r3", "job_id", "jl-731"),
                                 evidence=[RECEIPT])
        state.link("mcp.jobs#r3", "job:jl-731", evidence=[DECLARED],
                   authority=EvidenceAuthority.SOURCE)
        state.add_goal(("mcp.jobs#r3", "runtime_s", "?t"))
        state.add_goal(("job:jl-731", "owner", "?o"))
        assert len(state.frontier()) == 2
        assert len(self._groups(state)) == 1, (
            "the partition did not join through the store's own link")

    def test_without_the_link_the_same_two_are_two_groups(self):
        """The paired negative, so the test above is about the link and not
        about the shape of the fixture."""
        state = CognitiveState()
        state.assert_observation(("mcp.jobs#r3", "job_id", "jl-731"),
                                 evidence=[RECEIPT])
        state.add_goal(("mcp.jobs#r3", "runtime_s", "?t"))
        state.add_goal(("job:jl-731", "owner", "?o"))
        assert len(self._groups(state)) == 2

    def test_a_shared_field_is_not_a_shared_subject(self):
        """Two jobs' `state` are two problems. The field position is never a
        join key, and a partition that used it would report one group for
        every store whose goals ask the same question twice."""
        state = CognitiveState()
        state.add_goal(("job:one", "state", "?s"))
        state.add_goal(("job:two", "state", "?s"))
        assert len(self._groups(state)) == 2

    def test_a_value_the_store_does_not_know_is_not_a_name(self):
        """Two obligations waiting for the literal `"ok"` are not about one
        thing. A join on any ground value would make every store whose goals
        share a word report one group."""
        state = CognitiveState()
        state.add_goal(("job:one", "state", "ok"))
        state.add_goal(("job:two", "state", "ok"))
        assert len(self._groups(state)) == 2

    def test_a_value_the_store_does_know_is_a_name(self):
        """And the other side of it: a value naming an entity this store
        holds facts about is a name, so the two are one group."""
        state = CognitiveState()
        state.assert_observation(("acct-9", "kind", "checking"),
                                 evidence=[RECEIPT])
        state.add_goal(("job:one", "touches", "acct-9"))
        state.add_goal(("acct-9", "owner", "?o"))
        assert len(self._groups(state)) == 1

    def test_the_groups_come_in_the_ranked_frontier_s_order(self):
        """Groups by their best member, members by their rank — so a reader
        taking the first group takes the one `next_obligation` would have
        started with."""
        state = CognitiveState()
        state.add_goal(("job:one", "state", "?s"))
        state.add_goal(("job:two", "state", "?s"))
        ranked = [item.id for item in state.ranked_frontier()]
        assert self._groups(state) == [[ranked[0]], [ranked[1]]]
        assert state.next_obligation().id == ranked[0]

    def test_every_obligation_lands_in_exactly_one_group(self):
        state = CognitiveState()
        state.add_goal(("job:one", "state", "?s"))
        state.add_goal(("job:one", "owner", "?o"))
        state.add_goal(("job:two", "state", "?s"))
        placed = [oid for group in self._groups(state) for oid in group]
        assert sorted(placed) == sorted(
            item.id for item in state.ranked_frontier())
        assert len(placed) == len(set(placed))

    def test_it_is_deterministic(self):
        def built():
            state = CognitiveState()
            state.add_goal(("job:one", "state", "?s"))
            state.add_goal(("job:two", "state", "?s"))
            state.add_goal(("job:one", "owner", "?o"))
            return self._groups(state)
        assert built() == built()

    def test_a_truncated_walk_says_so_on_every_group(self):
        """A group carries the whole WALK's flag and not one of its own,
        because the obligation the walk never reached could have been the
        one that joined two of these groups — so a cap puts the independence
        itself in doubt, not merely the count."""
        state = CognitiveState()
        state.add_rule("wide", ("?a", "wide", "?c"),
                       [("?a", "seen", "?b"), ("?b", "needs", "?c")],
                       RuleAuthority.DOMAIN)
        for index in range(300):
            state.assert_observation(("alice", "seen", f"n{index}"),
                                     evidence=[RECEIPT])
        state.add_goal(("alice", "wide", "acct-9"))
        assert state.ranked_frontier().truncated, "this fixture must cap"
        groups = state.independent_frontier()
        assert groups and all(group.truncated for group in groups)


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

class TestAPropositionNeverSilentlyMutates:
    def test_a_status_change_writes_a_new_revision(self):
        state = CognitiveState()
        pid = state.assert_observation(("job-7", "state", "running"),
                                       evidence=[RECEIPT])
        assert state.proposition(pid).revision == 1
        state.refute(pid, evidence=[OTHER])
        assert state.proposition(pid).revision == 2, \
            "one call, one revision — status and evidence moved together"

    def test_the_old_revision_is_reachable_and_linked(self):
        state = CognitiveState()
        pid = state.assert_observation(("job-7", "state", "running"),
                                       evidence=[RECEIPT])
        state.refute(pid, evidence=[OTHER])
        history = state.history(pid)
        assert [item.revision for item in history] == [1, 2]
        assert history[0].status is PropositionStatus.OBSERVED
        assert history[0].evidence == (door(RECEIPT),), \
            "the record before the change is intact, evidence and all"
        assert history[-1].status is PropositionStatus.REFUTED
        assert [item.previous for item in history] == [None, "p1@1"]
        assert history[-1] is state.proposition(pid)

    def test_the_id_is_the_claim_and_the_key_is_the_record(self):
        state = CognitiveState()
        pid = state.assert_observation(("job-7", "state", "running"),
                                       evidence=[RECEIPT])
        state.refute(pid, evidence=[OTHER])
        assert {item.id for item in state.history(pid)} == {pid}
        keys = [item.key for item in state.history(pid)]
        assert len(set(keys)) == len(keys)

    def test_history_of_something_nobody_asserted_is_refused(self):
        state = CognitiveState()
        with pytest.raises(UnknownId):
            state.history("p1")


class TestTheRanksAreTotalOrders:
    """Both merge rules read a rank table. A table missing a member would
    raise a `KeyError` somewhere deep in closure, at whatever moment that
    authority first appeared — which is the sort of thing found in
    production."""

    def test_every_evidence_authority_has_a_rank(self):
        assert set(AUTHORITY_RANK) == set(EvidenceAuthority)
        assert len(set(AUTHORITY_RANK.values())) == len(EvidenceAuthority)

    def test_the_ranks_order_receipts_above_model_output(self):
        worst_receipt = min(AUTHORITY_RANK[a] for a in OBSERVATION_AUTHORITIES)
        best_model = max(AUTHORITY_RANK[a] for a in HYPOTHESIS_AUTHORITIES)
        assert worst_receipt > best_model


# ---------------------------------------------------------------------------
# The door's stamp
# ---------------------------------------------------------------------------

class TestTheDoorStampsTheEvidence:
    """The wall has to survive the merge.

    One claim can arrive through both doors — the model extracts it and a
    receipt confirms it — and the store keeps one proposition holding the
    union of both sets of refs. Without a stamp, that union is where the wall
    goes: a single tuple of refs, no way to say which of them a model
    produced, and `prove()`'s leaves answering "how do we know this" with an
    undifferentiated pile. The stamp is written by the door and by nothing
    else, so the answer survives any number of merges.
    """

    def test_an_observations_refs_carry_the_authority_it_accepted(self):
        state = CognitiveState()
        pid = state.assert_observation(
            ("alice", "role", "admin"), evidence=[RECEIPT],
            authority=EvidenceAuthority.DETERMINISTIC)
        ref, = state.proposition(pid).evidence
        assert ref.authority is EvidenceAuthority.DETERMINISTIC
        assert (ref.kind, ref.locator) == (RECEIPT.kind, RECEIPT.locator)

    @pytest.mark.parametrize("authority", HYPOTHESIS_AUTHORITIES)
    def test_a_hypothesiss_refs_carry_which_model_step_made_it(self, authority):
        state = CognitiveState()
        pid = state.assert_hypothesis(("alice", "role", "admin"),
                                      evidence=[EXTRACTED],
                                      authority=authority)
        ref, = state.proposition(pid).evidence
        assert ref.authority is authority

    def test_a_caller_cannot_write_the_stamp(self):
        """Otherwise the wall is a method name rather than a rule: a caller
        could file model output under SOURCE by building the ref that way and
        still going through the honest door."""
        state = CognitiveState()
        forged = EvidenceRef(kind="receipt", locator="seq:1",
                             authority=EvidenceAuthority.DETERMINISTIC)
        pid = state.assert_hypothesis(("alice", "role", "admin"),
                                      evidence=[forged])
        ref, = state.proposition(pid).evidence
        assert ref.authority is EvidenceAuthority.MODEL_HYPOTHESIS

    def test_the_merge_does_not_erase_which_door(self):
        state = CognitiveState()
        pid = state.assert_hypothesis(
            ("alice", "role", "admin"), evidence=[EXTRACTED],
            authority=EvidenceAuthority.MODEL_EXTRACTION)
        state.assert_observation(("alice", "role", "admin"),
                                 evidence=[RECEIPT])
        by_door = {ref.authority for ref in state.proposition(pid).evidence}
        assert by_door == {EvidenceAuthority.MODEL_EXTRACTION,
                           EvidenceAuthority.SOURCE}

    def test_prove_shows_the_door_at_the_leaves(self):
        state, _ = store_with_controls()
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT],
                                 authority=EvidenceAuthority.DETERMINISTIC)
        state.assert_observation(("alice", "payment_link", "acct-9"),
                                 evidence=[OTHER])
        derived, = state.derive()
        step, = state.prove(derived).steps
        assert [ref.authority
                for leaf in step.premises for ref in leaf.evidence] == \
            [EvidenceAuthority.DETERMINISTIC, EvidenceAuthority.SOURCE]

    def test_a_refutations_evidence_is_unstamped(self):
        """A refutation is not one of the two doors, and guessing a door for
        it would be the kernel inventing provenance."""
        state = CognitiveState()
        pid = state.assert_observation(("job-7", "state", "running"),
                                       evidence=[RECEIPT])
        state.refute(pid, evidence=[OTHER])
        clash, = state.contradictions()
        assert [ref.authority for ref in clash.evidence] == [None]

    def test_an_unstamped_ref_is_not_guessed_at(self):
        """The migration case: a ref decoded from a log written before the
        stamp existed reads as absent, not as a plausible door."""
        assert EvidenceRef.from_dict({"kind": "receipt",
                                      "locator": "seq:1"}).authority is None


# ---------------------------------------------------------------------------
# A model's claim against a receipt
# ---------------------------------------------------------------------------

class TestAModelsClaimAgainstAReceipt:
    """The first signal the shadow layer wants, and the one it must not act
    on.

    A hypothesis disagreeing with an observation is exactly the event worth
    surfacing — the model said `total_s` was a score and the receipt says it
    is elapsed seconds — and exactly the event where doing anything about it
    would be wrong. Contest the observation and a bad extraction has unseated
    a receipt; promote the hypothesis and the wall is gone. So the store
    records the pair and moves nothing: confidence marking, not gating.
    """

    def _pair(self, order):
        state = CognitiveState()
        state.declare_field("total_s", "one")
        moves = {
            "observed": lambda: state.assert_observation(
                ("job-7", "total_s", 154.024), evidence=[RECEIPT]),
            "guessed": lambda: state.assert_hypothesis(
                ("job-7", "total_s", 186.7), evidence=[EXTRACTED],
                authority=EvidenceAuthority.MODEL_EXTRACTION),
        }
        ids = {name: moves[name]() for name in order}
        state.derive()
        return state, ids["observed"], ids["guessed"]

    @pytest.mark.parametrize("order", [("observed", "guessed"),
                                       ("guessed", "observed")])
    def test_the_disagreement_is_reported_whichever_arrives_first(self, order):
        state, seen, guessed = self._pair(order)
        clash, = state.contradictions()
        assert clash.kind == "hypothesis"
        assert (clash.left, clash.right) == (guessed, seen), \
            "left is always the hypothesis, so a consumer reads one shape"

    @pytest.mark.parametrize("order", [("observed", "guessed"),
                                       ("guessed", "observed")])
    def test_neither_side_moves(self, order):
        state, seen, guessed = self._pair(order)
        assert state.proposition(seen).status is PropositionStatus.OBSERVED
        assert state.proposition(seen).live
        assert state.proposition(guessed).status is \
            PropositionStatus.HYPOTHESIZED
        assert [state.proposition(seen).revision,
                state.proposition(guessed).revision] == [1, 1], \
            "a report is not a revision"

    def test_a_conclusion_drawn_from_the_observation_stands(self):
        """The whole point of not contesting: the receipt keeps deriving."""
        state = CognitiveState()
        state.declare_field("total_s", "one")
        state.add_rule("slow", ("?j", "slow", True),
                       [("?j", "total_s", 154.024)], RuleAuthority.SYSTEM)
        state.assert_observation(("job-7", "total_s", 154.024),
                                 evidence=[RECEIPT])
        state.assert_hypothesis(("job-7", "total_s", 186.7),
                                evidence=[EXTRACTED])
        state.derive()
        slow, = [p for p in state.propositions() if p.field == "slow"]
        assert slow.status is PropositionStatus.DERIVED
        assert [c.kind for c in state.contradictions()] == ["hypothesis"]

    def test_agreeing_with_the_receipt_is_not_a_disagreement(self):
        state = CognitiveState()
        seen = state.assert_observation(("job-7", "total_s", 154.024),
                                        evidence=[RECEIPT])
        guessed = state.assert_hypothesis(("job-7", "total_s", 154.024),
                                          evidence=[EXTRACTED])
        assert guessed == seen, "one claim, said twice"
        assert state.contradictions() == ()

    def test_the_report_is_recorded_once_however_often_it_repeats(self):
        state, _seen, _guessed = self._pair(("observed", "guessed"))
        for _ in range(3):
            state.assert_hypothesis(
                ("job-7", "total_s", 186.7), evidence=[EXTRACTED],
                authority=EvidenceAuthority.MODEL_EXTRACTION)
            state.assert_observation(("job-7", "total_s", 154.024),
                                     evidence=[RECEIPT])
        assert len(state.contradictions()) == 1, \
            "a ledger that grew per delivery would be counting retries"

    def test_two_hypotheses_disagreeing_with_each_other_are_reported(self):
        """This was once dismissed as "the model being uncertain, which is not
        news", and that was wrong about what a shadow layer is for.

        Two *extractors* disagreeing over one receipt is the cheapest
        available sign that the extraction step is where a mission is going
        wrong — and it is on the record before any receipt arrives to settle
        it. Recorded like every other disagreement and moving nothing:
        neither claim outranks the other and the store has no receipt to
        prefer either.
        """
        state = CognitiveState()
        state.declare_field("total_s", "one")
        first = state.assert_hypothesis(("job-7", "total_s", 186.7),
                                        evidence=[EXTRACTED])
        second = state.assert_hypothesis(("job-7", "total_s", 200.0),
                                         evidence=[EXTRACTED])
        state.derive()
        clash, = state.contradictions()
        assert clash.kind == "hypothesis"
        assert {clash.left, clash.right} == {first, second}
        assert state.proposition(first).status is \
            PropositionStatus.HYPOTHESIZED
        assert state.proposition(second).status is \
            PropositionStatus.HYPOTHESIZED
        assert [p.revision for p in (state.proposition(first),
                                     state.proposition(second))] == [1, 1]

    def test_extractors_agreeing_about_a_many_field_is_not_a_disagreement(self):
        """It honours the declaration like every other collision check."""
        state = CognitiveState()
        state.assert_hypothesis(("alice", "controls", "acct-1"),
                                evidence=[EXTRACTED])
        state.assert_hypothesis(("alice", "controls", "acct-9"),
                                evidence=[EXTRACTED])
        state.derive()
        assert state.contradictions() == ()

    def test_the_kinds_are_a_closed_set(self):
        state, _, _ = self._pair(("observed", "guessed"))
        assert all(c.kind in CONTRADICTION_KINDS
                   for c in state.contradictions())
        assert set(CONTRADICTION_KINDS) == {"value", "refutation",
                                            "dead_premise", "hypothesis"}


# ---------------------------------------------------------------------------
# What a value is
# ---------------------------------------------------------------------------

class TestABoolIsNotANumber:
    """`True == 1` and `hash(True) == hash(1)` in Python, so a store keying
    claims on the raw value files them as one — at whichever arrived first,
    reporting no disagreement. A silent first-wins on exactly the extraction
    confusion this kernel exists to surface."""

    def test_true_and_one_are_two_claims_that_contradict(self):
        state = CognitiveState()
        state.declare_field("retried", "one")
        flag = state.assert_observation(("job-7", "retried", True),
                                        evidence=[RECEIPT])
        count = state.assert_observation(("job-7", "retried", 1),
                                         evidence=[OTHER])
        assert count != flag
        clash, = state.contradictions()
        assert clash.kind == "value"
        assert {clash.left, clash.right} == {flag, count}
        assert not state.proposition(flag).live
        assert not state.proposition(count).live

    def test_one_and_one_point_zero_are_the_same_number_said_twice(self):
        state = CognitiveState()
        state.declare_field("retried", "one")
        first = state.assert_observation(("job-7", "retried", 1),
                                         evidence=[RECEIPT])
        again = state.assert_observation(("job-7", "retried", 1.0),
                                         evidence=[OTHER])
        assert again == first
        assert state.contradictions() == ()

    def test_the_bands_are_what_they_say(self):
        assert value_tag(True) == "bool"
        assert value_tag(1) == value_tag(1.0) == "num"
        assert value_tag("1") == "str"
        assert value_tag(None) == "null"


class TestANumberThatIsNotThereIsSaidByAbsence:
    """NaN and the infinities are refused at the door, for two reasons that
    arrive in the wrong order. In memory `nan != nan`, so a claim keyed on one
    never equals itself and asserting it twice mints two propositions for one
    claim. On the wire `json.dumps` writes bare `NaN`, which is not RFC 8259
    and which a non-Python reader of `reasoning.jsonl` either rejects or reads
    as something else. Together they are a store that does not replay to
    itself."""

    @pytest.mark.parametrize("value", [float("nan"), float("inf"),
                                       float("-inf")])
    def test_a_non_finite_value_is_refused(self, value):
        state = CognitiveState()
        with pytest.raises(CognitionError):
            state.assert_observation(("job-7", "total_s", value),
                                     evidence=[RECEIPT])
        assert state.propositions() == ()
        assert state.events == ()

    @pytest.mark.parametrize("value", [float("nan"), float("inf")])
    def test_a_rule_cannot_smuggle_one_in_as_a_literal(self, value):
        state = CognitiveState()
        with pytest.raises(CognitionError):
            state.add_rule("nonsense", ("?j", "odd", True),
                           [("?j", "total_s", value)], RuleAuthority.SYSTEM)

    def test_the_divergence_it_used_to_cause_is_now_unreachable(self):
        """The old shape run out to its end: one claim asserted twice becoming
        two propositions in memory and one after a JSON round trip — a store
        that does not equal its own replay. The refusal is what makes that
        unreachable, so this asserts the refusal *and* that nothing which does
        get in can behave that way."""
        import json
        import math

        state = CognitiveState()
        for attempt in (float("nan"), float("nan")):
            with pytest.raises(CognitionError):
                state.assert_observation(("job-7", "total_s", attempt),
                                         evidence=[RECEIPT])
        state.assert_observation(("job-7", "total_s", 154.024),
                                 evidence=[RECEIPT])
        digest = state.digest()
        numbers = [row["value"] for row in digest["propositions"]
                   if isinstance(row["value"], float)]
        assert numbers and all(math.isfinite(value) for value in numbers)
        assert all(value == value for value in numbers)
        assert json.loads(json.dumps(digest)) == digest


# ---------------------------------------------------------------------------
# Repeats
# ---------------------------------------------------------------------------

class TestARefutationIsIdempotent:
    def test_the_same_refutation_twice_changes_nothing_the_second_time(self):
        state = CognitiveState()
        pid = state.assert_observation(("job-7", "state", "running"),
                                       evidence=[RECEIPT])
        first = state.refute(pid, evidence=[OTHER])
        settled = state.proposition(pid).revision
        again = state.refute(pid, evidence=[OTHER])
        assert again == first, "one collision, not two"
        assert len(state.contradictions()) == 1
        assert state.proposition(pid).revision == settled

    def test_a_second_refutation_with_new_evidence_lands_on_the_claim(self):
        state = CognitiveState()
        pid = state.assert_observation(("job-7", "state", "running"),
                                       evidence=[RECEIPT])
        state.refute(pid, evidence=[OTHER])
        state.refute(pid, evidence=[EXTRACTED])
        assert len(state.contradictions()) == 1
        assert len(state.proposition(pid).evidence) == 3

    def test_refuting_a_hypothesis_is_legal_and_useful(self):
        """"The model said this and it is wrong" is exactly what a shadow
        layer wants on the record."""
        state = CognitiveState()
        pid = state.assert_hypothesis(("alice", "role", "admin"),
                                      evidence=[EXTRACTED])
        state.refute(pid, evidence=[RECEIPT])
        assert state.proposition(pid).status is PropositionStatus.REFUTED
        assert [c.kind for c in state.contradictions()] == ["refutation"]


class TestPromotionIsFromProposedAndNowhereElse:
    def test_a_lateral_re_promotion_is_refused(self):
        """SKILL to DOMAIN re-labels who stands behind a clause that is
        already deriving, and its existing derivations carry the old label.
        Left open, this method is how a caller restamps somebody else's rule
        as its own."""
        state, rid = store_with_controls(RuleAuthority.SKILL)
        with pytest.raises(AuthorityRefused):
            state.promote_rule(rid, RuleAuthority.DOMAIN)
        assert state.rule(rid).authority is RuleAuthority.SKILL

    def test_promoting_twice_is_refused_the_second_time(self):
        state, rid = store_with_controls(RuleAuthority.PROPOSED)
        state.promote_rule(rid, RuleAuthority.DOMAIN)
        with pytest.raises(AuthorityRefused):
            state.promote_rule(rid, RuleAuthority.DOMAIN)


# ---------------------------------------------------------------------------
# Cardinality
# ---------------------------------------------------------------------------

class TestCardinalityIsDeclaredNotAssumed:
    """Whether two values of one field can both be true is a claim about the
    *field*, and nothing in a triple says which kind it is. `total_s` has one
    value; `controls` has as many as it has. So somebody declares, and an
    undeclared field carries many.

    The default is the argument. Contesting is terminal: it takes both sides
    out of closure and everything derived from either of them, permanently.
    So a false contradiction on a multi-valued field does not merely report a
    disagreement that is not there — it can take an entity out of the store's
    reasoning altogether. A missed one costs a signal nobody got. Under the
    owner's ruling that this layer is shadow and additive, the destructive
    failure is the one to default away from.
    """

    def test_an_undeclared_field_carries_many_values(self):
        state = CognitiveState()
        first = state.assert_observation(("alice", "controls", "acct-1"),
                                         evidence=[RECEIPT])
        second = state.assert_observation(("alice", "controls", "acct-9"),
                                          evidence=[OTHER])
        assert state.contradictions() == ()
        assert state.proposition(first).live
        assert state.proposition(second).live
        assert state.cardinality("controls") == "many"

    def test_a_declared_single_valued_field_contests(self):
        state = CognitiveState()
        state.declare_field("total_s", "one")
        first = state.assert_observation(("job-7", "total_s", 154.024),
                                         evidence=[RECEIPT])
        second = state.assert_observation(("job-7", "total_s", 186.7),
                                          evidence=[OTHER])
        assert [c.kind for c in state.contradictions()] == ["value"]
        assert not state.proposition(first).live
        assert not state.proposition(second).live

    def test_a_many_field_does_not_poison_what_rests_on_it(self):
        """The compounding failure the default exists to avoid: a spurious
        collision does not merely report itself, it retracts every conclusion
        drawn from either side."""
        state, _ = store_with_controls()
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        state.assert_observation(("alice", "payment_link", "acct-9"),
                                 evidence=[RECEIPT])
        derived, = state.derive()
        state.assert_observation(("alice", "admin_access", "acct-1"),
                                 evidence=[OTHER])
        state.derive()
        assert state.proposition(derived).status is PropositionStatus.DERIVED

    def test_a_model_claim_about_a_many_field_is_not_a_disagreement(self):
        """The hypothesis report rests on the same "these cannot both be
        true", so it honours the same declaration."""
        state = CognitiveState()
        state.assert_observation(("alice", "controls", "acct-1"),
                                 evidence=[RECEIPT])
        state.assert_hypothesis(("alice", "controls", "acct-9"),
                                evidence=[EXTRACTED])
        state.derive()
        assert state.contradictions() == ()

    def test_declaring_the_same_thing_twice_is_a_no_op(self):
        state = CognitiveState()
        state.declare_field("total_s", "one")
        state.declare_field("total_s", "one")
        assert state.fields() == {"total_s": "one"}

    def test_changing_a_declaration_is_refused(self):
        """Propositions have already been measured against the old answer.
        Changing it quietly leaves a store whose ledger cannot be explained
        by its own rules."""
        state = CognitiveState()
        state.declare_field("total_s", "one")
        with pytest.raises(CognitionError):
            state.declare_field("total_s", "many")
        assert state.cardinality("total_s") == "one"

    def test_a_cardinality_nobody_defined_is_refused(self):
        state = CognitiveState()
        with pytest.raises(CognitionError):
            state.declare_field("total_s", "exactly_one")

    def test_declaring_one_measures_what_the_store_already_holds(self):
        """The reproducer, and the reason declaring over an occupied field
        is not refused.

        A resume replays the session's observations and the skill's rule pack
        loads *after* it, so the declaration almost always arrives second.
        A pack whose collision checks depended on having been loaded first
        would work in development and stop working on the first resume — the
        declaration has to apply to what is already there.
        """
        state = CognitiveState()
        first = state.assert_observation(("job-7", "total_s", 154.024),
                                         evidence=[RECEIPT])
        second = state.assert_observation(("job-7", "total_s", 186.7),
                                          evidence=[OTHER])
        assert state.contradictions() == (), "nothing is declared yet"

        state.declare_field("total_s", "one")
        clash, = state.contradictions()
        assert clash.kind == "value"
        assert {clash.left, clash.right} == {first, second}
        assert not state.proposition(first).live
        assert not state.proposition(second).live

    def test_a_late_declaration_retracts_what_was_derived_from_the_field(self):
        state, _ = store_with_controls()
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        state.assert_observation(("alice", "payment_link", "acct-9"),
                                 evidence=[RECEIPT])
        derived, = state.derive()
        state.assert_observation(("alice", "admin_access", "acct-1"),
                                 evidence=[OTHER])
        state.derive()
        assert state.proposition(derived).status is PropositionStatus.DERIVED

        state.declare_field("admin_access", "one")
        assert state.proposition(derived).status is PropositionStatus.CONTESTED

    def test_a_late_declaration_measures_in_insertion_order(self):
        """The order is the stability claim, so a test holds it.

        The walk goes oldest-first, which makes the earliest claim the one
        still standing when the later ones are measured against it — so the
        ledger reads as a history rather than as a fact about how a dict
        happened to iterate. Walk it in any other order — reversed, or sorted
        by the values themselves — and the same three claims produce a
        different ledger: different rows, naming different sides.

        The values are deliberately NOT ascending. With `1, 2, 3` the
        insertion order and the value order agree, so a walk that sorted by
        value would write the same ledger and this test would be holding an
        order it was not checking.
        """
        state = CognitiveState()
        first = state.assert_observation(("job-7", "total_s", 3.0),
                                         evidence=[RECEIPT])
        second = state.assert_observation(("job-7", "total_s", 1.0),
                                          evidence=[OTHER])
        third = state.assert_observation(("job-7", "total_s", 2.0),
                                         evidence=[EXTRACTED])
        state.declare_field("total_s", "one")
        assert [(c.kind, c.left, c.right) for c in state.contradictions()] == [
            ("value", first, second),
            ("value", first, third),
        ]

    def test_a_late_declaration_over_two_guesses_writes_one_row(self):
        """A hypothesis against a hypothesis has no side that fixes the
        orientation — no observation to put on the right — so `(H1, H2)` and
        `(H2, H1)` are two dedup keys for one fact. Nothing notices while
        each claim arrives once; the walk below meets the pair from both
        ends, which is exactly what a late declaration does."""
        state = CognitiveState()
        first = state.assert_hypothesis(("job-7", "total_s", 1.0),
                                        evidence=[EXTRACTED])
        second = state.assert_hypothesis(("job-7", "total_s", 2.0),
                                         evidence=[EXTRACTED])
        state.declare_field("total_s", "one")
        clash, = state.contradictions()
        assert (clash.kind, clash.left, clash.right) == \
            ("hypothesis", first, second)

    def test_the_orientation_does_not_depend_on_which_guess_arrived_first(self):
        """Canonicalised on insertion order, so the row is a fact about the
        store rather than about which end of the pair a walk reached first."""
        seen = []
        for values in ((1.0, 2.0), (2.0, 1.0)):
            state = CognitiveState()
            state.declare_field("total_s", "one")
            ids = [state.assert_hypothesis(("job-7", "total_s", value),
                                           evidence=[EXTRACTED])
                   for value in values]
            clash, = state.contradictions()
            assert clash.left == ids[0] and clash.right == ids[1]
            seen.append(len(state.contradictions()))
        assert seen == [1, 1]

    def test_a_late_declaration_is_one_event_and_replays(self):
        state = CognitiveState()
        state.assert_observation(("job-7", "total_s", 154.024),
                                 evidence=[RECEIPT])
        state.assert_observation(("job-7", "total_s", 186.7),
                                 evidence=[OTHER])
        before = len(state.events)
        state.declare_field("total_s", "one")
        assert len(state.events) == before + 1
        again = CognitiveState.replay(state.snapshot())
        assert again.digest_json() == state.digest_json()

    def test_declaring_many_measures_nothing(self):
        """`many` is what an undeclared field already is, so saying it out
        loud cannot change what the store holds."""
        state = CognitiveState()
        state.assert_observation(("alice", "controls", "acct-1"),
                                 evidence=[RECEIPT])
        state.assert_observation(("alice", "controls", "acct-9"),
                                 evidence=[OTHER])
        state.declare_field("controls", "many")
        assert state.contradictions() == ()
        assert len(state.propositions(live=True)) == 2

    def test_undeclared_fields_are_absent_rather_than_listed(self):
        """Absence is how this package says "nobody has said", everywhere
        else; `cardinality()` is what turns absence into the default."""
        state = CognitiveState()
        state.declare_field("total_s", "one")
        state.assert_observation(("alice", "controls", "acct-1"),
                                 evidence=[RECEIPT])
        assert "controls" not in state.fields()
        assert state.cardinality("controls") == "many"


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------

class TestSettlingAValueCollision:
    """The one deliberate exception to contesting being terminal, and the
    line it does not cross.

    The kernel *executes* a settlement — revive the kept side, refute the
    other, mark the contradiction — and never *decides* one. Which side
    stands is a judgement about the world, made by whatever is attached
    above. The moment this method took a policy argument, a store that
    refuses to pick between two receipts would be picking between them on a
    heuristic, in a place nobody would look.
    """

    def _contested(self):
        state = CognitiveState()
        state.declare_field("total_s", "one")
        state.add_rule("slow", ("?j", "slow", True),
                       [("?j", "total_s", 154.024)], RuleAuthority.SYSTEM)
        first = state.assert_observation(("job-7", "total_s", 154.024),
                                         evidence=[RECEIPT])
        state.derive()
        slow, = [p.id for p in state.propositions() if p.field == "slow"]
        second = state.assert_observation(("job-7", "total_s", 186.7),
                                          evidence=[OTHER])
        state.derive()
        clash, = [c for c in state.contradictions() if c.kind == "value"]
        return state, clash, first, second, slow

    def test_the_kept_side_comes_back_to_what_it_was(self):
        state, clash, first, second, _slow = self._contested()
        assert state.proposition(first).status is PropositionStatus.CONTESTED
        state.settle(clash.id, keep=first, evidence=[EXTRACTED])
        assert state.proposition(first).status is PropositionStatus.OBSERVED
        assert state.proposition(first).live

    def test_a_derived_side_comes_back_DERIVED_and_not_observed(self):
        """The status is read out of the revision history, not guessed.

        Every other case here settles in favour of an observation, so an
        engine that simply wrote OBSERVED back would pass all of them — and
        would quietly promote a conclusion into a receipt, which is the
        authority wall failing in the one place nobody would look for it. A
        conclusion contested by a collision has to return to DERIVED.
        """
        state = CognitiveState()
        state.declare_field("owner", "one")
        state.add_rule("lead_owns", ("?j", "owner", "?p"),
                       [("?j", "lead", "?p")], RuleAuthority.DOMAIN)
        state.derive()
        state.assert_observation(("job-7", "lead", "bob"), evidence=[RECEIPT])
        derived, = state.derive()
        assert state.proposition(derived).status is PropositionStatus.DERIVED
        state.assert_observation(("job-7", "owner", "alice"),
                                 evidence=[OTHER])
        state.derive()
        assert state.proposition(derived).status is PropositionStatus.CONTESTED

        clash, = [c for c in state.contradictions() if c.kind == "value"]
        state.settle(clash.id, keep=derived, evidence=[EXTRACTED])
        prop = state.proposition(derived)
        assert prop.status is PropositionStatus.DERIVED, \
            "a conclusion came back as an observation"
        assert prop.live
        assert prop.evidence == (), \
            "and it did not acquire receipts it never had"

    def test_the_other_side_is_refuted_rather_than_forgotten(self):
        state, clash, first, second, _slow = self._contested()
        state.settle(clash.id, keep=first, evidence=[EXTRACTED])
        assert state.proposition(second).status is PropositionStatus.REFUTED
        assert not state.proposition(second).live

    def test_the_contradiction_says_it_was_settled_and_which_way(self):
        state, clash, first, _second, _slow = self._contested()
        cid = state.settle(clash.id, keep=first, evidence=[EXTRACTED])
        settled, = [c for c in state.contradictions() if c.id == cid]
        assert settled.settled is True
        assert settled.kept == first
        assert EXTRACTED.kind in {ref.kind for ref in settled.evidence}

    def test_what_fell_with_the_kept_side_comes_back_with_it(self):
        """The conclusion was retracted only because its premise died. It has
        a live proof again the moment the premise does."""
        state, clash, first, _second, slow = self._contested()
        assert state.proposition(slow).status is PropositionStatus.CONTESTED
        state.settle(clash.id, keep=first, evidence=[EXTRACTED])
        assert state.proposition(slow).status is PropositionStatus.DERIVED
        dead = [c for c in state.contradictions() if c.kind == "dead_premise"]
        assert dead and all(c.settled for c in dead)

    def test_keeping_the_other_side_derives_what_that_side_licenses(self):
        state, clash, first, second, slow = self._contested()
        state.settle(clash.id, keep=second, evidence=[EXTRACTED])
        assert state.proposition(second).status is PropositionStatus.OBSERVED
        assert state.proposition(first).status is PropositionStatus.REFUTED
        assert state.proposition(slow).status is PropositionStatus.CONTESTED, \
            "the premise it rested on is the one that lost"

    def test_a_third_value_does_not_survive_the_settlement(self):
        """The reproducer, and it is not an edge case — it is what a field
        with three candidate values does.

        A and B collide and both go CONTESTED. C then arrives and collides
        with *nothing*, because by then there is nothing live on that field to
        disagree with, so C stands. Settling A/B in A's favour makes A live
        again — and the store now holds two live values on a field declared
        to hold one, which is precisely the state the whole collision
        machinery exists to prevent. A revival is an arrival, and has to be
        measured like one.
        """
        state = CognitiveState()
        state.declare_field("total_s", "one")
        a = state.assert_observation(("job-7", "total_s", 1.0),
                                     evidence=[RECEIPT])
        b = state.assert_observation(("job-7", "total_s", 2.0),
                                     evidence=[OTHER])
        c = state.assert_observation(("job-7", "total_s", 3.0),
                                     evidence=[EXTRACTED])
        state.derive()
        assert state.proposition(c).live, "C arrived with nothing to fight"

        clash, = [x for x in state.contradictions()
                  if {x.left, x.right} == {a, b}]
        state.settle(clash.id, keep=a, evidence=[RECEIPT])

        live = [p.value for p in state.propositions(live=True)]
        assert len(live) <= 1, (
            f"a field declared to hold one value holds {live}")

    def test_a_revived_CONCLUSION_is_measured_too_not_only_the_kept_side(self):
        """The other half of "a revival is an arrival", and the half a store
        built only around the kept side misses.

        `owner=bob` is DERIVED from `lead=bob`. A second lead contests the
        first, so the conclusion falls with it. A third owner value then
        arrives and stands, because by then there is nothing live on `owner`
        to disagree with. Settling the LEAD collision revives the lead — and
        with it the conclusion — and the conclusion is now a second live
        value on a field declared to hold one. It never passed through
        `keep`: it came back through `_revive_dependents`.
        """
        state = CognitiveState()
        state.declare_field("lead", "one")
        state.declare_field("owner", "one")
        state.add_rule("lead_owns", ("?j", "owner", "?p"),
                       [("?j", "lead", "?p")], RuleAuthority.DOMAIN)
        state.derive()
        bob = state.assert_observation(("job-7", "lead", "bob"),
                                       evidence=[RECEIPT])
        state.derive()
        conclusion, = [p.id for p in state.propositions() if p.field == "owner"]
        assert state.proposition(conclusion).status is PropositionStatus.DERIVED

        carol = state.assert_observation(("job-7", "lead", "carol"),
                                         evidence=[OTHER])
        state.derive()
        assert state.proposition(conclusion).status is \
            PropositionStatus.CONTESTED, "it fell with its premise"

        zed = state.assert_observation(("job-7", "owner", "zed"),
                                       evidence=[EXTRACTED])
        state.derive()
        assert state.proposition(zed).live, "nothing live to disagree with it"

        clash, = [c for c in state.contradictions()
                  if c.kind == "value" and {c.left, c.right} == {bob, carol}]
        state.settle(clash.id, keep=bob, evidence=[RECEIPT])
        state.derive()

        live = [p.value for p in state.propositions(live=True)
                if p.field == "owner"]
        assert len(live) <= 1, (
            f"`owner` is declared to hold one value and holds {live}; the "
            "conclusion came back through the revival and was never measured")

    def test_the_same_pair_colliding_again_is_a_new_row(self):
        """A settled row is history — it records a disagreement somebody
        resolved and the evidence they resolved it on. Folding a later
        collision of the same pair into it would overwrite the settlement
        with the news that it did not hold."""
        state = CognitiveState()
        state.declare_field("total_s", "one")
        a = state.assert_observation(("job-7", "total_s", 1.0),
                                     evidence=[RECEIPT])
        b = state.assert_observation(("job-7", "total_s", 2.0),
                                     evidence=[OTHER])
        first, = [x for x in state.contradictions() if x.kind == "value"]
        state.settle(first.id, keep=a, evidence=[EXTRACTED])
        assert state.proposition(a).live
        assert state.proposition(b).status is PropositionStatus.REFUTED

        settled, = [x for x in state.contradictions() if x.id == first.id]
        assert settled.settled is True and settled.kept == a, \
            "the settled row stayed as it was"

    def test_a_conclusion_that_dies_twice_gets_two_rows(self):
        """The reachable case, and it is not exotic.

        Settling revives a conclusion and retires the `dead_premise` row that
        recorded its fall. If the premise then dies again — refuted this time
        — the conclusion falls again, and that is NEWS: a second event, with
        a different cause, about the same pair. Folding it into the retired
        row would overwrite a settlement with the fact that it did not last,
        and the ledger would show one resolved disagreement where two things
        happened.
        """
        state = CognitiveState()
        state.declare_field("total_s", "one")
        state.add_rule("slow", ("?j", "slow", True),
                       [("?j", "total_s", 154.024)], RuleAuthority.SYSTEM)
        kept = state.assert_observation(("job-7", "total_s", 154.024),
                                        evidence=[RECEIPT])
        state.derive()
        slow, = [p.id for p in state.propositions() if p.field == "slow"]
        state.assert_observation(("job-7", "total_s", 186.7), evidence=[OTHER])
        state.derive()

        clash, = [x for x in state.contradictions() if x.kind == "value"]
        state.settle(clash.id, keep=kept, evidence=[EXTRACTED])
        state.derive()
        assert state.proposition(slow).status is PropositionStatus.DERIVED
        retired, = [x for x in state.contradictions()
                    if x.kind == "dead_premise"]
        assert retired.settled is True

        state.refute(kept, evidence=[OTHER])
        assert state.proposition(slow).status is PropositionStatus.CONTESTED
        rows = [x for x in state.contradictions() if x.kind == "dead_premise"]
        assert len(rows) == 2, (
            "the second fall was folded into the row that recorded the first")
        assert rows[0].settled is True, "the settlement is still on the record"
        assert rows[1].settled is False, "and the new fall is not resolved"

    def test_a_settlement_re_enters_the_delta(self):
        """The kept side is live again, so closure owes it the conclusions it
        licenses — and a settlement that revived a premise without staging it
        would leave the store believing a thing and not what follows from it."""
        state = CognitiveState()
        state.declare_field("total_s", "one")
        state.add_rule("slow", ("?j", "slow", True),
                       [("?j", "total_s", 154.024)], RuleAuthority.SYSTEM)
        kept = state.assert_observation(("job-7", "total_s", 154.024),
                                        evidence=[RECEIPT])
        state.derive()
        slow, = [p.id for p in state.propositions() if p.field == "slow"]
        state.assert_observation(("job-7", "total_s", 186.7), evidence=[OTHER])
        state.derive()
        assert state.proposition(slow).status is PropositionStatus.CONTESTED

        clash, = [x for x in state.contradictions() if x.kind == "value"]
        state.settle(clash.id, keep=kept, evidence=[EXTRACTED])
        assert kept in state.pending()["propositions"] or \
            state.proposition(slow).status is PropositionStatus.DERIVED
        state.derive()
        assert state.proposition(slow).status is PropositionStatus.DERIVED

    def test_settling_twice_is_refused(self):
        state, clash, first, second, _slow = self._contested()
        state.settle(clash.id, keep=first, evidence=[EXTRACTED])
        with pytest.raises(CognitionError):
            state.settle(clash.id, keep=second, evidence=[EXTRACTED])

    def test_settling_in_favour_of_a_stranger_is_refused(self):
        state, clash, _first, _second, slow = self._contested()
        with pytest.raises(CognitionError):
            state.settle(clash.id, keep=slow, evidence=[EXTRACTED])

    def test_a_settlement_needs_evidence(self):
        state, clash, first, _second, _slow = self._contested()
        with pytest.raises(CognitionError):
            state.settle(clash.id, keep=first)

    @pytest.mark.parametrize("kind", ["refutation", "hypothesis"])
    def test_only_a_value_collision_has_two_sides_to_choose_between(self, kind):
        state = CognitiveState()
        state.declare_field("total_s", "one")
        pid = state.assert_observation(("job-7", "total_s", 154.024),
                                       evidence=[RECEIPT])
        if kind == "refutation":
            state.refute(pid, evidence=[OTHER])
        else:
            state.assert_hypothesis(("job-7", "total_s", 186.7),
                                    evidence=[EXTRACTED])
            state.derive()
        clash, = [c for c in state.contradictions() if c.kind == kind]
        with pytest.raises(CognitionError):
            state.settle(clash.id, keep=pid, evidence=[EXTRACTED])

    def test_settling_something_nobody_recorded_is_refused(self):
        state = CognitiveState()
        with pytest.raises(UnknownId):
            state.settle("c1", keep="p1", evidence=[EXTRACTED])


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

class TestSupportIsComputedNotStored:
    """`grade` is the best any live proof can do — the maximum, over proofs
    still standing, of the weakest premise in that proof — and it is read off
    the DAG every time it is asked for.

    The case that decides this is the happy one. A premise first extracted
    from prose and later confirmed by a receipt lifts everything derived from
    it, and nothing re-derives, because nothing needs to. A stored grade
    would still be reporting the old number: the store understating its own
    evidence, quietly, for as long as nobody ran closure again.
    """

    def _chain(self):
        state, _ = store_with_controls()
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT],
                                 authority=EvidenceAuthority.DETERMINISTIC)
        weak = state.assert_observation(("alice", "payment_link", "acct-9"),
                                        evidence=[OTHER])
        derived, = state.derive()
        return state, weak, derived

    def test_a_leaf_is_graded_by_its_own_authority(self):
        state, weak, _derived = self._chain()
        assert state.support(weak).grade is EvidenceAuthority.SOURCE

    def test_a_conclusion_is_graded_by_its_weakest_premise(self):
        state, _weak, derived = self._chain()
        assert state.support(derived).grade is EvidenceAuthority.SOURCE

    def test_promoting_a_premise_lifts_the_conclusion_with_no_re_derivation(self):
        """The stale-grade case, which is what makes this a read. The stored
        authority on the proposition is still SOURCE — nothing re-derived —
        and the support computed now is not."""
        state, weak, derived = self._chain()
        state.assert_observation(("alice", "payment_link", "acct-9"),
                                 evidence=[RECEIPT],
                                 authority=EvidenceAuthority.DETERMINISTIC)
        state.derive()
        assert state.proposition(derived).authority is EvidenceAuthority.SOURCE
        assert state.support(derived).grade is EvidenceAuthority.DETERMINISTIC
        assert state.support(weak).grade is EvidenceAuthority.DETERMINISTIC

    def test_the_best_live_proof_decides_it(self):
        state = CognitiveState()
        state.add_rule("by_admin", ("?a", "controls", "?c"),
                       [("?a", "admin_access", "?c")], RuleAuthority.DOMAIN)
        state.add_rule("by_owner", ("?a", "controls", "?c"),
                       [("?a", "owns", "?c")], RuleAuthority.DOMAIN)
        state.assert_observation(("alice", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        state.assert_observation(("alice", "owns", "acct-9"),
                                 evidence=[OTHER],
                                 authority=EvidenceAuthority.DETERMINISTIC)
        state.derive()
        controls, = [p for p in state.propositions() if p.field == "controls"]
        assert state.support(controls.id).grade is \
            EvidenceAuthority.DETERMINISTIC, "the better route, not the first"

    def test_a_hypothesis_is_graded_by_the_model_step_that_made_it(self):
        """`None` used to come back here, which conflated "the store will not
        stand behind this" with "the store has stopped believing this" — the
        two things a confidence read exists to keep apart. A hypothesis IS
        supported: by a model, badly. The `hypothesis` field already says
        which kind of claim it is, so the grade does not have to."""
        state = CognitiveState()
        pid = state.assert_hypothesis(
            ("alice", "role", "admin"), evidence=[EXTRACTED],
            authority=EvidenceAuthority.MODEL_EXTRACTION)
        support = state.support(pid)
        assert support.status is PropositionStatus.HYPOTHESIZED
        assert support.grade is EvidenceAuthority.MODEL_EXTRACTION
        assert support.evidence_leaves == (
            door(EXTRACTED, EvidenceAuthority.MODEL_EXTRACTION),)

    def test_a_summary_of_guesses_floors_at_the_model(self):
        state = CognitiveState()
        guess = state.assert_hypothesis(("alice", "role", "admin"),
                                        evidence=[EXTRACTED])
        seen = state.assert_observation(("bob", "role", "admin"),
                                        evidence=[RECEIPT])
        summary = state.summarize([seen, guess])
        assert summary["floor_grade"] is EvidenceAuthority.MODEL_HYPOTHESIS
        assert summary["hypothesized"] == (guess,)

    def test_something_the_store_no_longer_believes_has_no_grade(self):
        """Not "poorly supported" — a refusal. A caller rendering None as a
        low number has turned a refusal into an opinion."""
        state = CognitiveState()
        pid = state.assert_observation(("job-7", "state", "running"),
                                       evidence=[RECEIPT])
        state.refute(pid, evidence=[OTHER])
        assert state.support(pid).grade is None

    def test_support_names_the_collisions_and_keeps_them_apart(self):
        state = CognitiveState()
        state.declare_field("total_s", "one")
        seen = state.assert_observation(("job-7", "total_s", 154.024),
                                        evidence=[RECEIPT])
        state.assert_hypothesis(("job-7", "total_s", 186.7),
                                evidence=[EXTRACTED])
        state.derive()
        support = state.support(seen)
        assert support.contested_by == ()
        assert len(support.hypothesis) == 1, \
            "a model disagreeing is not the store being unable to stand up"

    def test_the_leaves_carry_the_doors_they_came_through(self):
        state, _weak, derived = self._chain()
        doors = {ref.authority
                 for ref in state.support(derived).evidence_leaves}
        assert doors == {EvidenceAuthority.DETERMINISTIC,
                         EvidenceAuthority.SOURCE}

    def test_a_summary_is_only_as_good_as_its_worst_claim(self):
        state, weak, derived = self._chain()
        strong, = [p.id for p in state.propositions()
                   if p.field == "admin_access"]
        summary = state.summarize([strong, weak, derived])
        assert summary["floor_grade"] is EvidenceAuthority.SOURCE
        assert summary["contested"] == ()
        assert summary["hypothesized"] == ()

    def test_a_summary_names_what_is_wrong_rather_than_counting_it(self):
        state = CognitiveState()
        state.declare_field("total_s", "one")
        first = state.assert_observation(("job-7", "total_s", 154.024),
                                         evidence=[RECEIPT])
        second = state.assert_observation(("job-7", "total_s", 186.7),
                                          evidence=[OTHER])
        guess = state.assert_hypothesis(("job-7", "owner", "alice"),
                                        evidence=[EXTRACTED])
        summary = state.summarize([first, second, guess])
        assert set(summary["contested"]) == {first, second}
        assert summary["hypothesized"] == (guess,)

    def test_support_for_something_nobody_asserted_is_refused(self):
        with pytest.raises(UnknownId):
            CognitiveState().support("p1")


# ---------------------------------------------------------------------------
# The public doors onto what the store holds
# ---------------------------------------------------------------------------

class TestTheStoreAnswersAboutItself:
    """Without these, every caller writes its own scan — and the first one to
    get the liveness filter wrong builds a plausible answer out of retracted
    claims, or keeps a second copy of the triple-to-id fact the merge rules
    are written against."""

    def test_query_matches_a_pattern_over_live_propositions(self):
        state = CognitiveState()
        state.assert_observation(("alice", "controls", "acct-1"),
                                 evidence=[RECEIPT])
        state.assert_observation(("alice", "controls", "acct-9"),
                                 evidence=[OTHER])
        dead = state.assert_observation(("bob", "controls", "acct-1"),
                                        evidence=[RECEIPT])
        state.refute(dead, evidence=[OTHER])
        found = state.query(("?who", "controls", "?what"))
        assert [p.entity for p in found] == ["alice", "alice"]
        assert len(state.query(("?who", "controls", "?what"), live=False)) == 3

    def test_claim_turns_a_triple_back_into_this_stores_id(self):
        state = CognitiveState()
        pid = state.assert_observation(("alice", "controls", "acct-1"),
                                       evidence=[RECEIPT])
        assert state.claim(("alice", "controls", "acct-1")) == pid
        assert state.claim(("alice", "controls", "acct-9")) is None

    def test_claim_keeps_the_type_band_the_merge_rules_use(self):
        state = CognitiveState()
        flag = state.assert_observation(("job-7", "retried", True),
                                        evidence=[RECEIPT])
        assert state.claim(("job-7", "retried", True)) == flag
        assert state.claim(("job-7", "retried", 1)) is None

    def test_contradictions_for_names_both_sides(self):
        state = CognitiveState()
        state.declare_field("total_s", "one")
        first = state.assert_observation(("job-7", "total_s", 154.024),
                                         evidence=[RECEIPT])
        second = state.assert_observation(("job-7", "total_s", 186.7),
                                          evidence=[OTHER])
        other = state.assert_observation(("job-8", "total_s", 3.0),
                                         evidence=[RECEIPT])
        assert [c.id for c in state.contradictions_for(first)] == \
               [c.id for c in state.contradictions_for(second)]
        assert state.contradictions_for(other) == ()


# ---------------------------------------------------------------------------
# Subjects: the thing two receipts are about
# ---------------------------------------------------------------------------

def store_with_receipt(entity="job_status#r5", field="state",
                       value="completed", authority=EvidenceAuthority.SOURCE):
    """One receipt's fact, ready to be linked. The shape the shadow makes."""
    state = CognitiveState()
    pid = state.assert_observation((entity, field, value), evidence=[RECEIPT],
                                   authority=authority)
    return state, pid


class TestASubjectCannotBeSpelledLikeAReceipt:
    """The two namespaces are disjoint *by construction*, which is a claim
    about `check_subject` and not about anybody's naming habits.

    It has to be. The kernel does not own the spelling of a receipt entity —
    the layer above does, and it spells one `tool#seq`. So the promise this
    package can keep is the one it can enforce at its own door: no string
    carrying `#` is ever a subject, and no subject-spelled string is ever
    accepted as a link's near end. Between them a projection can never land
    where a receipt's own facts live, and a receipt can never be linked to
    itself under a second spelling.
    """

    def test_a_subject_is_a_kind_and_a_value(self):
        assert check_subject("job:jl-731") == ("job", "jl-731")
        assert subject_parts("asset:led.a41") == ("asset", "led.a41")

    def test_the_split_is_at_the_first_separator(self):
        """A value may carry the separator — `result:mcp://x` is a real
        identifier shape — and the kind is always what precedes the first
        one, because a kind cannot contain it."""
        assert check_subject("result:mcp://x") == ("result", "mcp://x")

    @pytest.mark.parametrize("receipt", [
        "job_status#r5", "mcp.job_status#r5",
        # The one that decides it: a tool whose own name carries a colon. It
        # LOOKS subject-spelled and is not, because the `#` in the value is
        # refused — which is the whole of why the marker is banned rather
        # than merely discouraged.
        "plugin:job_status#r5",
    ])
    def test_no_receipt_entity_parses_as_a_subject(self, receipt):
        assert RECEIPT_MARKER in receipt
        assert subject_parts(receipt) is None

    def test_a_subject_may_not_carry_the_receipt_marker(self):
        with pytest.raises(CognitionError):
            check_subject("job:jl#731")

    @pytest.mark.parametrize("bad", [
        "", "job", ":jl-731", "job:", 7, None, "job:jl 731", "job:jl\n731",
        "?job:jl-731", "jo b:jl-731", "job" + SUBJECT_SEPARATOR + "x" * 900,
    ])
    def test_what_is_not_a_subject(self, bad):
        with pytest.raises(CognitionError):
            check_subject(bad)
        assert subject_parts(bad) is None

    def test_a_variable_is_never_a_subject_kind(self):
        """`?job` is the pattern spelling. If it parsed as a kind, a rule
        variable and a subject would be the same string in two places."""
        assert subject_parts("?job:anything") is None

    def test_the_cap_is_a_named_bound(self):
        assert subject_parts("job:" + "x" * SUBJECT_CAP) is not None
        assert subject_parts("job:" + "x" * (SUBJECT_CAP + 1)) is None

    def test_spelling_one_checks_its_own_round_trip(self):
        """A caller building a subject out of a declaration's kind and a
        payload's value has no reason to have thought about a kind carrying
        the separator — which would spell a string that reads back as a
        different subject entirely."""
        assert subject_entity("job", "jl-731") == "job:jl-731"
        with pytest.raises(CognitionError):
            subject_entity("job:extra", "jl-731")


class TestALinkIsAClaimAndNotARename:
    """Every obligation a proposition has, a link has: evidence naming what
    it rests on, an authority stamped at the door it came through, and an
    event. A link that could be made on nothing would be the one mistake in
    this design that manufactures evidence-shaped noise — two tools that
    never disagreed, reported as a contradiction."""

    def test_a_link_names_the_pair_and_returns_its_id(self):
        state, _ = store_with_receipt()
        lid = state.link("job_status#r5", "job:jl-731", evidence=[DECLARED],
                         authority=EvidenceAuthority.SOURCE)
        held, = state.links()
        assert held.id == lid
        assert (held.entity, held.subject) == ("job_status#r5", "job:jl-731")
        assert held.kind == "job" and held.value == "jl-731"

    def test_a_link_with_no_evidence_is_refused(self):
        state, _ = store_with_receipt()
        with pytest.raises(CognitionError):
            state.link("job_status#r5", "job:jl-731", evidence=[],
                       authority=EvidenceAuthority.SOURCE)
        assert state.links() == ()

    def test_evidence_is_stamped_by_the_door(self):
        """Over whatever the caller put there, exactly as the two assertion
        doors do — a caller able to write the stamp could file a guess as a
        declaration by constructing the ref rather than by choosing a
        grade."""
        state, _ = store_with_receipt()
        state.link("job_status#r5", "job:jl-731",
                   evidence=[DECLARED.stamped(
                       EvidenceAuthority.DETERMINISTIC)],
                   authority=EvidenceAuthority.MODEL_INTERPRETATION)
        held, = state.links()
        assert {ref.authority for ref in held.evidence} == \
            {EvidenceAuthority.MODEL_INTERPRETATION}

    def test_the_authority_has_no_default(self):
        """The same rule the graph's `add_edge` keeps, and permanently: a
        caller that does not say how it knows two receipts are about one
        thing has not said it, and "probably deterministic" is the guess this
        package exists to refuse."""
        state, _ = store_with_receipt()
        with pytest.raises(TypeError):
            state.link("job_status#r5", "job:jl-731", evidence=[DECLARED])

    def test_an_entity_the_store_holds_nothing_about_is_refused(self):
        """A link is a claim that *this receipt* is about that subject. A
        receipt this store never saw is not a receipt: the subject would be
        born with nothing to project and the log would name an entity its own
        events cannot explain."""
        state, _ = store_with_receipt()
        with pytest.raises(UnknownId):
            state.link("job_status#r9", "job:jl-731", evidence=[DECLARED],
                       authority=EvidenceAuthority.SOURCE)

    def test_a_subject_is_never_the_near_end_of_a_link(self):
        """Which is also how "a projection never projects again" is
        structural rather than a rule somebody has to remember."""
        state, _ = store_with_receipt()
        state.link("job_status#r5", "job:jl-731", evidence=[DECLARED],
                   authority=EvidenceAuthority.SOURCE)
        state.derive()
        with pytest.raises(CognitionError):
            state.link("job:jl-731", "party:red", evidence=[DECLARED],
                       authority=EvidenceAuthority.SOURCE)

    def test_a_self_link_is_the_same_refusal(self):
        """One wall, not two that can drift apart: the entity would have to
        be subject-spelled to equal the subject."""
        state, _ = store_with_receipt()
        with pytest.raises(CognitionError):
            state.link("job:jl-731", "job:jl-731", evidence=[DECLARED],
                       authority=EvidenceAuthority.SOURCE)

    def test_a_subject_that_is_not_spelled_like_one_is_refused(self):
        state, _ = store_with_receipt()
        with pytest.raises(CognitionError):
            state.link("job_status#r5", "jl-731", evidence=[DECLARED],
                       authority=EvidenceAuthority.SOURCE)

    def test_the_same_pair_twice_is_one_link(self):
        """Idempotent on the pair, the edge-identity discipline the graph
        keeps: evidence unions, a revision is written, and no second record
        appears to be counted as a second claim."""
        state, _ = store_with_receipt()
        first = state.link("job_status#r5", "job:jl-731", evidence=[DECLARED],
                           authority=EvidenceAuthority.SOURCE)
        again = state.link("job_status#r5", "job:jl-731", evidence=[OTHER],
                           authority=EvidenceAuthority.SOURCE)
        assert again == first
        held, = state.links()
        assert held.revision == 2 and held.previous == "l1@1"
        assert set(held.evidence) == {
            DECLARED.stamped(EvidenceAuthority.SOURCE),
            OTHER.stamped(EvidenceAuthority.SOURCE)}

    def test_the_revisions_of_a_link_are_readable(self):
        """`history`'s sibling. The digest renders a link's revisions, so a
        reader could see that one had been upgraded and had no call to ask
        what it was before — a fact the store held and would not hand
        over."""
        state, _ = store_with_receipt()
        lid = state.link("job_status#r5", "job:jl-731", evidence=[DECLARED],
                         authority=EvidenceAuthority.MODEL_INTERPRETATION)
        state.link("job_status#r5", "job:jl-731", evidence=[OTHER],
                   authority=EvidenceAuthority.SOURCE)
        history = state.link_history(lid)
        assert [item.revision for item in history] == [1, 2]
        assert [item.authority for item in history] == [
            EvidenceAuthority.MODEL_INTERPRETATION, EvidenceAuthority.SOURCE]
        assert history[-1] == state.link_record(lid)

    def test_a_link_nobody_made_has_no_history(self):
        state, _ = store_with_receipt()
        with pytest.raises(UnknownId):
            state.link_history("l9")

    def test_re_stating_a_link_unchanged_writes_no_revision(self):
        state, _ = store_with_receipt()
        state.link("job_status#r5", "job:jl-731", evidence=[DECLARED],
                   authority=EvidenceAuthority.SOURCE)
        state.link("job_status#r5", "job:jl-731", evidence=[DECLARED],
                   authority=EvidenceAuthority.SOURCE)
        held, = state.links()
        assert held.revision == 1, "a retry is not a change of mind"

    def test_the_authority_rises_and_never_falls(self):
        state, _ = store_with_receipt()
        state.link("job_status#r5", "job:jl-731", evidence=[DECLARED],
                   authority=EvidenceAuthority.MODEL_INTERPRETATION)
        state.link("job_status#r5", "job:jl-731", evidence=[DECLARED],
                   authority=EvidenceAuthority.SOURCE)
        state.link("job_status#r5", "job:jl-731", evidence=[DECLARED],
                   authority=EvidenceAuthority.MODEL_HYPOTHESIS)
        held, = state.links()
        assert held.authority is EvidenceAuthority.SOURCE

    def test_one_receipt_may_be_about_two_subjects(self):
        """Not a refusal: a call that names a job *and* the asset it produced
        is about both, and its facts belong at both."""
        state, _ = store_with_receipt()
        state.link("job_status#r5", "job:jl-731", evidence=[DECLARED],
                   authority=EvidenceAuthority.SOURCE)
        state.link("job_status#r5", "asset:led.a41", evidence=[DECLARED],
                   authority=EvidenceAuthority.SOURCE)
        state.derive()
        assert {link.subject for link in state.links_for("job_status#r5")} == \
            {"job:jl-731", "asset:led.a41"}
        assert state.claim(("job:jl-731", "state", "completed"))
        assert state.claim(("asset:led.a41", "state", "completed"))

    def test_the_store_answers_which_receipts_stand_behind_a_subject(self):
        state, _ = store_with_receipt()
        state.assert_observation(("compute#7", "state", "running"),
                                 evidence=[OTHER])
        for entity in ("job_status#r5", "compute#7"):
            state.link(entity, "job:jl-731", evidence=[DECLARED],
                       authority=EvidenceAuthority.SOURCE)
        assert [link.entity for link in state.linked_to("job:jl-731")] == \
            ["job_status#r5", "compute#7"]


class TestProjectionCarriesTheFactWithoutMovingIt:
    """Linking never edits a proposition. The receipt's fact stays where it
    was seen — its entity, its history, its evidence — and the subject gets a
    *derived* copy whose premise is that fact.

    Rewriting was the alternative and it destroys what the store is for: a
    proposition's entity is where it was seen, and two receipts merged into
    one entity can no longer say which of them said what.
    """

    @staticmethod
    def _linked(fact=EvidenceAuthority.SOURCE,
                link=EvidenceAuthority.SOURCE):
        state, pid = store_with_receipt(authority=fact)
        lid = state.link("job_status#r5", "job:jl-731", evidence=[DECLARED],
                         authority=link)
        state.derive()
        return state, pid, lid

    def test_the_subjects_fact_is_derived_from_the_receipts(self):
        state, pid, lid = self._linked()
        cid = state.claim(("job:jl-731", "state", "completed"))
        assert state.proposition(cid).status is PropositionStatus.DERIVED
        assert state.proposition(pid).status is PropositionStatus.OBSERVED
        assert state.proposition(pid).entity == "job_status#r5", \
            "the receipt's fact did not move"
        proof, = state.derivations_for(cid)
        assert proof.premises == (pid,)
        assert proof.rule == PROJECTION_RULE_ID
        assert proof.link == lid

    def test_the_proof_walks_back_to_the_call_that_showed_it(self):
        state, pid, lid = self._linked()
        proof = state.prove(state.claim(("job:jl-731", "state", "completed")))
        step, = proof.steps
        assert step.rule_name == "projection"
        assert step.link == lid
        premise, = step.premises
        assert premise.proposition == pid
        assert premise.evidence == (RECEIPT.stamped(EvidenceAuthority.SOURCE),)

    def test_the_links_evidence_is_at_the_leaves(self):
        """"Why do we think this call was about this job" is the question a
        wrong link makes urgent, and the receipt's own refs cannot answer
        it."""
        state, _pid, _lid = self._linked()
        support = state.support(
            state.claim(("job:jl-731", "state", "completed")))
        assert set(support.evidence_leaves) == {
            DECLARED.stamped(EvidenceAuthority.SOURCE),
            RECEIPT.stamped(EvidenceAuthority.SOURCE)}

    @pytest.mark.parametrize("fact,link,expected", [
        (EvidenceAuthority.DETERMINISTIC, EvidenceAuthority.SOURCE,
         EvidenceAuthority.SOURCE),
        (EvidenceAuthority.SOURCE, EvidenceAuthority.DETERMINISTIC,
         EvidenceAuthority.SOURCE),
        (EvidenceAuthority.DETERMINISTIC, EvidenceAuthority.DETERMINISTIC,
         EvidenceAuthority.DETERMINISTIC),
    ])
    def test_the_grade_is_the_weaker_of_the_fact_and_the_link(
            self, fact, link, expected):
        """Both ways round, because a rule that took the *stronger* would
        pass a test written in one direction only — and would launder a
        platform's declaration into a measurement, which is precisely what
        the grade exists to stop."""
        state, _pid, _lid = self._linked(fact=fact, link=link)
        cid = state.claim(("job:jl-731", "state", "completed"))
        assert state.proposition(cid).authority is expected
        assert state.support(cid).grade is expected

    def test_a_text_proposition_does_not_project(self):
        """v1 bound, and structural: a text-only proposition has no entity at
        all in this store, so there is nothing to project it from."""
        state, _ = store_with_receipt()
        state.assert_observation(text="the deployment declined, citing policy",
                                 evidence=[RECEIPT])
        state.link("job_status#r5", "job:jl-731", evidence=[DECLARED],
                   authority=EvidenceAuthority.SOURCE)
        state.derive()
        assert [p.text for p in state.propositions()
                if p.entity == "job:jl-731"] == [None]

    def test_a_fact_carrying_both_projects_only_its_triple(self):
        state = CognitiveState()
        state.assert_observation(("job_status#r5", "state", "failed"),
                                 text="OOM on the second shard",
                                 evidence=[RECEIPT])
        state.link("job_status#r5", "job:jl-731", evidence=[DECLARED],
                   authority=EvidenceAuthority.SOURCE)
        state.derive()
        cid = state.claim(("job:jl-731", "state", "failed"))
        assert state.proposition(cid).text is None, \
            "prose about a receipt is not prose about a subject"

    def test_a_hypothesis_does_not_project_until_it_is_observed(self):
        state = CognitiveState()
        state.assert_hypothesis(("job_status#r5", "state", "completed"),
                                evidence=[EXTRACTED])
        state.link("job_status#r5", "job:jl-731", evidence=[DECLARED],
                   authority=EvidenceAuthority.SOURCE)
        state.derive()
        assert state.claim(("job:jl-731", "state", "completed")) is None
        state.assert_observation(("job_status#r5", "state", "completed"),
                                 evidence=[RECEIPT])
        state.derive()
        assert state.claim(("job:jl-731", "state", "completed"))

    def test_a_second_link_on_the_same_entity_projects_again(self):
        state, _pid, _lid = self._linked()
        state.link("job_status#r5", "asset:led.a41", evidence=[DECLARED],
                   authority=EvidenceAuthority.SOURCE)
        state.derive()
        assert len(state.derivations()) == 2
        assert {p.entity for p in state.propositions()} == {
            "job_status#r5", "job:jl-731", "asset:led.a41"}


def beliefs(state):
    """What a store holds, with every name taken out of it.

    Built out of `digest()` rather than beside it, so a field the digest
    stops rendering stops being compared *here* too and the narrowing shows
    up in one place instead of quietly weakening a second comparator.

    Ids are deliberately gone. They are handed out in insertion order, so two
    stores told the same things in a different order hold the same claims
    under different names — the module docstring of `core.cognition.state`
    states that as a property and `tests/test_cognition_replay.py` pins it.
    What survives the renaming is every claim with its status and grade, and
    every proof read as *triples*: the rule, its premises, its conclusion and
    the link that licensed it. A projection that went missing, landed at the
    wrong grade, or lost its link is a difference here.
    """
    digest = state.digest()
    rows = {row["id"]: row for row in digest["propositions"]}
    links = {row["id"]: (row["entity"], row["subject"], row["authority"])
             for row in digest["links"]}

    def claim(pid):
        row = rows[pid]
        return (row["entity"], row["field"], row["value"], row["text"])

    return {
        "claims": sorted((claim(pid), row["status"], row["authority"])
                         for pid, row in rows.items()),
        "proofs": sorted(
            (row["rule"], tuple(sorted(claim(p) for p in row["premises"])),
             claim(row["conclusion"]),
             links[row["link"]] if row["link"] else None)
            for row in digest["derivations"]),
        "links": sorted(links.values()),
        "contradictions": sorted(
            (row["kind"], claim(row["left"]),
             claim(row["right"]) if row["right"] else None)
            for row in digest["contradictions"]),
    }


class TestTheLinkMayArriveBeforeOrAfterTheFacts:
    """Order-independence, and it is the load-bearing property of the
    projection engine.

    The shadow above links a receipt at the moment it harvests it, and which
    of the two lands first is a detail of a loop nobody should have to think
    about. A store that answered differently depending on the order would be
    answering about its own scheduling rather than about the world. So both
    directions are in `apply_delta` and both arrival orders are compared.

    **Compared as beliefs, and the exact digest is the wrong comparator
    here** — which is worth saying rather than working around. The two orders
    below present genuinely different deltas (one closes over the link with
    the facts already held; the other closes over a fact with the link
    already held), and a store that closes twice inserts a derived
    proposition between two observations, so the same claims end up under
    different `pN`. That is a documented property of this engine and not a
    defect for this test to paper over. `beliefs()` compares everything the
    renaming does not reach: every claim, every status, every grade, every
    proof read as triples, every link.
    """

    @staticmethod
    def _build(link_first):
        """The same three things said, with the flush moved.

        `link_first` closes the link against a store that holds one fact, and
        the second fact then projects through the *fact* direction of the
        delta; the other order closes both facts through the *link*
        direction. Each arrangement exercises one direction on its own, which
        is why dropping either one is caught.
        """
        state = CognitiveState()
        state.assert_observation(("job_status#r5", "state", "completed"),
                                 evidence=[RECEIPT])
        if link_first:
            state.link("job_status#r5", "job:jl-731", evidence=[DECLARED],
                       authority=EvidenceAuthority.SOURCE)
            state.derive()
        state.assert_observation(("job_status#r5", "total_s", 154.024),
                                 evidence=[RECEIPT])
        if not link_first:
            state.derive()
            state.link("job_status#r5", "job:jl-731", evidence=[DECLARED],
                       authority=EvidenceAuthority.SOURCE)
        state.derive()
        return state

    def test_the_two_orders_believe_the_same_thing(self):
        assert beliefs(self._build(True)) == beliefs(self._build(False))

    def test_and_both_of_them_actually_projected(self):
        """A property test over a store where nothing happened proves
        nothing: two empty stores believe the same thing."""
        for state in (self._build(True), self._build(False)):
            assert state.claim(("job:jl-731", "state", "completed"))
            assert state.claim(("job:jl-731", "total_s", 154.024))
            assert len(state.derivations()) == 2

    def test_a_link_beside_new_facts_still_projects_the_older_ones(self):
        """The hole between the two directions, and the one a test written
        only from the two ends misses.

        A step that carries a new link *and* new facts is the ordinary case
        at the top of this package — a receipt harvested over two steps, the
        identifier read on the second. The fact direction reaches only what
        changed, and what changed is not everything the entity holds. A store
        that let the fact half stand in for the link half here would leave the
        receipt's *earlier* figures off the subject and say nothing.
        """
        state = CognitiveState()
        state.assert_observation(("job_status#r5", "state", "completed"),
                                 evidence=[RECEIPT])
        state.derive()
        state.assert_observation(("job_status#r5", "total_s", 154.024),
                                 evidence=[RECEIPT])
        state.link("job_status#r5", "job:jl-731", evidence=[DECLARED],
                   authority=EvidenceAuthority.SOURCE)
        state.derive()
        assert state.claim(("job:jl-731", "total_s", 154.024)), "the new fact"
        assert state.claim(("job:jl-731", "state", "completed")), \
            "and the one the entity was already holding"

    def test_one_step_carrying_both_does_the_work_once(self):
        """The third arrangement, and the one where the exact digest *is* the
        right comparator: a single flush carrying a new link and new facts
        together. Both directions of `_project` reach the same pairs, and the
        store that results is byte-for-byte the one that would have closed
        over the link alone — deduplicated, in one order, with no second
        proof of anything."""
        def build(link_last):
            state = CognitiveState()
            state.assert_observation(("job_status#r5", "state", "completed"),
                                     evidence=[RECEIPT])
            if not link_last:
                state.link("job_status#r5", "job:jl-731", evidence=[DECLARED],
                           authority=EvidenceAuthority.SOURCE)
            state.assert_observation(("job_status#r5", "total_s", 154.024),
                                     evidence=[RECEIPT])
            if link_last:
                state.link("job_status#r5", "job:jl-731", evidence=[DECLARED],
                           authority=EvidenceAuthority.SOURCE)
            state.derive()
            return state

        assert build(True).digest_json() == build(False).digest_json()
        assert len(build(True).derivations()) == 2, "and it did project"

    def test_a_fact_arriving_after_the_link_projects_immediately(self):
        """The direction a link-only engine would lose, stated on its own so
        that the pair above cannot pass with half the work done."""
        state, _pid, _lid = TestProjectionCarriesTheFactWithoutMovingIt \
            ._linked()
        state.assert_observation(("job_status#r5", "total_s", 154.024),
                                 evidence=[OTHER])
        state.derive()
        assert state.claim(("job:jl-731", "total_s", 154.024))

    def test_a_link_arriving_after_the_facts_projects_what_is_held(self):
        """And the direction a fact-only engine would lose."""
        state = CognitiveState()
        state.assert_observation(("job_status#r5", "state", "completed"),
                                 evidence=[RECEIPT])
        state.derive()
        state.link("job_status#r5", "job:jl-731", evidence=[DECLARED],
                   authority=EvidenceAuthority.SOURCE)
        state.derive()
        assert state.claim(("job:jl-731", "state", "completed"))

    def test_a_flush_between_the_two_changes_the_names_and_not_the_beliefs(
            self):
        """The one thing timing *does* reach, pinned rather than wished away:
        ids are handed out in insertion order, and a flush between the writes
        inserts a projection before the next observation arrives. Same claims,
        same statuses — different names. The module docstring of
        `core.cognition.state` owns that sentence; this is it with a link in
        it."""
        def build(flush):
            state = CognitiveState()
            state.assert_observation(("job_status#r5", "state", "completed"),
                                     evidence=[RECEIPT])
            state.link("job_status#r5", "job:jl-731", evidence=[DECLARED],
                       authority=EvidenceAuthority.SOURCE)
            if flush:
                state.derive()
            state.assert_observation(("job_status#r5", "total_s", 154.024),
                                     evidence=[RECEIPT])
            state.derive()
            return state

        early, late = build(True), build(False)
        assert early.digest_json() != late.digest_json()
        assert {(p.triple, p.status) for p in early.propositions()} == \
               {(p.triple, p.status) for p in late.propositions()}

    def test_projection_reaches_fixpoint_in_a_bounded_number_of_passes(self):
        """Termination with a hard bound rather than by the suite not
        hanging. A projection's conclusions land on subject entities, which
        can never be the near end of a link, so projection adds no cycle of
        its own — and a spinning closure does not fail a test, it takes the
        machine."""
        state = CognitiveState()
        for index in range(50):
            state.assert_observation(("job_status#r5", f"col{index}", index),
                                     evidence=[RECEIPT])
        state.link("job_status#r5", "job:jl-731", evidence=[DECLARED],
                   authority=EvidenceAuthority.SOURCE)
        state.stats.reset()
        derived = state.derive()
        assert len(derived) == 50
        assert state.stats.delta_passes <= 3, state.stats
        state.stats.reset()
        state.derive()
        assert state.stats.delta_passes == 0, \
            "a settled store did more work when asked again"


class TestTwoReceiptsDisagreeingAboutOneJob:
    """The shape the whole spine was built for: two status tools, one job,
    two answers. It is a real finding from a production transcript, and
    before subjects the store could not see it — the two facts were about
    different entities and nothing in a triple said they were about one
    thing.

    What must happen: the receipts stay live, because a receipt does not
    disagree with itself; the two *projections* contest, because that is where
    the disagreement is; the collision is settleable at the subject; and the
    survivor still proves down to the call that showed it.
    """

    @staticmethod
    def _pair():
        state = CognitiveState()
        state.declare_field("state", "one")
        first = state.assert_observation(("derive_status#r1", "state",
                                          "completed"), evidence=[RECEIPT])
        second = state.assert_observation(("compute_job_status#r2", "state",
                                           "running"), evidence=[OTHER])
        for entity in ("derive_status#r1", "compute_job_status#r2"):
            state.link(entity, "job:jl-731", evidence=[DECLARED],
                       authority=EvidenceAuthority.SOURCE)
        state.derive()
        return state, first, second

    def test_the_contest_is_at_the_subject(self):
        state, _first, _second = self._pair()
        clash, = [c for c in state.contradictions() if c.kind == "value"]
        both = {state.proposition(clash.left).entity,
                state.proposition(clash.right).entity}
        assert both == {"job:jl-731"}
        assert not state.proposition(clash.left).live
        assert not state.proposition(clash.right).live

    def test_the_receipts_stay_live(self):
        """A receipt does not disagree with itself. If the collision reached
        the receipts, one call's report of its own result would have been
        retracted because another call said something else."""
        state, first, second = self._pair()
        assert state.proposition(first).status is PropositionStatus.OBSERVED
        assert state.proposition(second).status is PropositionStatus.OBSERVED

    def test_nothing_contests_while_the_field_carries_many(self):
        """The contest is the declaration's doing and not the link's:
        undeclared, both projections stand side by side and the store says
        nothing."""
        state = CognitiveState()
        for entity, value in (("derive_status#r1", "completed"),
                              ("compute_job_status#r2", "running")):
            state.assert_observation((entity, "state", value),
                                     evidence=[RECEIPT])
            state.link(entity, "job:jl-731", evidence=[DECLARED],
                       authority=EvidenceAuthority.SOURCE)
        state.derive()
        assert state.contradictions() == ()
        assert len([p for p in state.propositions(live=True)
                    if p.entity == "job:jl-731"]) == 2

    def test_the_subject_level_collision_can_be_settled(self):
        state, _first, second = self._pair()
        clash, = [c for c in state.contradictions() if c.kind == "value"]
        keep = state.claim(("job:jl-731", "state", "running"))
        state.settle(clash.id, keep=keep, evidence=[OTHER])
        assert state.proposition(keep).status is PropositionStatus.DERIVED
        other = state.claim(("job:jl-731", "state", "completed"))
        assert state.proposition(other).status is PropositionStatus.REFUTED
        step, = state.prove(keep).steps
        assert step.premises[0].proposition == second, \
            "the survivor still names the call that showed it"

    def test_the_receipts_are_named_on_both_sides(self):
        """What a reader of the contest needs: not "the store is unhappy" but
        "these two calls disagree"."""
        state, _first, _second = self._pair()
        clash, = [c for c in state.contradictions() if c.kind == "value"]
        told = set()
        for side in (clash.left, clash.right):
            step, = state.prove(side).steps
            told.add(step.premises[0].proposition)
        assert len(told) == 2
        assert {link.entity for link in state.linked_to("job:jl-731")} == \
            {"derive_status#r1", "compute_job_status#r2"}


class TestAGuessedIdentityNeverContestsAnObservation:
    """The reserved rung, implemented now because the invariant is the part
    that would be easy to lose later.

    Nothing in this release passes a `MODEL_*` grade to `link` — §2.2 holds
    the model-assisted linker until the extraction door is measured in
    missions, because a wrong link manufactures evidence-shaped noise. The
    door accepts the grade anyway, and what it does with it is the whole
    guarantee: the projections land `HYPOTHESIZED`, so they stay out of
    closure, out of every contest, and can only ever be *reported* against
    what a receipt said.
    """

    @staticmethod
    def _guessed(authority=EvidenceAuthority.MODEL_INTERPRETATION):
        state = CognitiveState()
        state.declare_field("state", "one")
        state.assert_observation(("guess#r9", "state", "running"),
                                 evidence=[RECEIPT])
        state.assert_observation(("job_status#r5", "state", "completed"),
                                 evidence=[RECEIPT])
        state.link("job_status#r5", "job:jl-731", evidence=[DECLARED],
                   authority=EvidenceAuthority.SOURCE)
        lid = state.link("guess#r9", "job:jl-731", evidence=[EXTRACTED],
                         authority=authority)
        state.derive()
        return state, lid

    @pytest.mark.parametrize("authority", HYPOTHESIS_AUTHORITIES)
    def test_a_model_graded_link_projects_hypotheses(self, authority):
        state, _lid = self._guessed(authority)
        guessed = state.claim(("job:jl-731", "state", "running"))
        assert state.proposition(guessed).status is \
            PropositionStatus.HYPOTHESIZED
        assert state.proposition(guessed).authority is authority

    def test_it_is_reported_against_the_observation_and_moves_nothing(self):
        state, _lid = self._guessed()
        observed = state.claim(("job:jl-731", "state", "completed"))
        assert state.proposition(observed).status is PropositionStatus.DERIVED
        assert [c.kind for c in state.contradictions()] == ["hypothesis"], \
            "a guessed identity may report a disagreement and never win one"

    def test_confirming_the_link_lifts_what_it_carried(self):
        """And the good direction: a link first guessed and later declared
        promotes its projections, without anything re-deriving."""
        state = CognitiveState()
        state.assert_observation(("job_status#r5", "state", "completed"),
                                 evidence=[RECEIPT])
        state.link("job_status#r5", "job:jl-731", evidence=[EXTRACTED],
                   authority=EvidenceAuthority.MODEL_EXTRACTION)
        state.derive()
        cid = state.claim(("job:jl-731", "state", "completed"))
        assert state.proposition(cid).status is PropositionStatus.HYPOTHESIZED
        before = len(state.derivations())
        state.link("job_status#r5", "job:jl-731", evidence=[DECLARED],
                   authority=EvidenceAuthority.SOURCE)
        state.derive()
        assert state.proposition(cid).status is PropositionStatus.DERIVED
        assert state.support(cid).grade is EvidenceAuthority.SOURCE
        assert len(state.derivations()) == before, "a proof is not a belief"


class TestAProjectionFallsWithItsPremise:
    """Retraction is free, and that is one of the arguments for projecting
    rather than for teaching the matcher that two entities are one. A refuted
    receipt fact kills its subject-level copy through the cascade that was
    already here — no second code path, and no second place to get it
    wrong."""

    def test_refuting_the_receipts_fact_retracts_the_subjects(self):
        state, pid, _lid = TestProjectionCarriesTheFactWithoutMovingIt \
            ._linked()
        cid = state.claim(("job:jl-731", "state", "completed"))
        state.refute(pid, evidence=[OTHER])
        assert state.proposition(cid).status is PropositionStatus.CONTESTED
        assert "dead_premise" in [c.kind for c in state.contradictions()]

    def test_a_contested_receipt_fact_takes_its_projection_too(self):
        state = CognitiveState()
        state.declare_field("total_s", "one")
        state.assert_observation(("job_status#r5", "total_s", 154.024),
                                 evidence=[RECEIPT])
        state.link("job_status#r5", "job:jl-731", evidence=[DECLARED],
                   authority=EvidenceAuthority.SOURCE)
        state.derive()
        cid = state.claim(("job:jl-731", "total_s", 154.024))
        state.assert_observation(("job_status#r5", "total_s", 186.7),
                                 evidence=[OTHER])
        state.derive()
        assert state.proposition(cid).status is PropositionStatus.CONTESTED

    def test_a_second_receipt_keeps_the_subjects_fact_standing(self):
        """The other half, so that the rule is not simply "anything touching
        a dead premise dies": a subject fact with a live second proof
        stays."""
        state = CognitiveState()
        first = state.assert_observation(("derive_status#r1", "state",
                                          "completed"), evidence=[RECEIPT])
        state.assert_observation(("compute_job_status#r2", "state",
                                  "completed"), evidence=[OTHER])
        for entity in ("derive_status#r1", "compute_job_status#r2"):
            state.link(entity, "job:jl-731", evidence=[DECLARED],
                       authority=EvidenceAuthority.SOURCE)
        state.derive()
        cid = state.claim(("job:jl-731", "state", "completed"))
        assert len(state.derivations_for(cid)) == 2, "two calls, one claim"
        state.refute(first, evidence=[OTHER])
        assert state.proposition(cid).status is PropositionStatus.DERIVED


class TestASubjectIsAnOrdinaryEntity:
    """Which is the entire reason projection was chosen over teaching the
    matcher about equivalence classes. Rules bind it, goals name it,
    obligations are computed over it and the confidence read grades it —
    none of which needed a line of new code, and every one of which would
    have been a separate place for a second implementation to drift."""

    def test_a_rule_joins_two_receipts_at_the_subject(self):
        """The join that was impossible before: `admin_access` from one call
        and `payment_link` from another, meeting because both calls named the
        same job."""
        state, _rid = store_with_controls()
        state.assert_observation(("tool_a#r1", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        state.assert_observation(("tool_b#r2", "payment_link", "acct-9"),
                                 evidence=[OTHER])
        for entity in ("tool_a#r1", "tool_b#r2"):
            state.link(entity, "job:jl-731", evidence=[DECLARED],
                       authority=EvidenceAuthority.SOURCE)
        state.derive()
        assert state.claim(("job:jl-731", "controls", "acct-9")), \
            "neither receipt could conclude this on its own"

    def test_a_goal_naming_a_subject_binds(self):
        state, _rid = store_with_controls()
        state.add_goal(("job:jl-731", "controls", "acct-9"))
        state.assert_observation(("tool_a#r1", "admin_access", "acct-9"),
                                 evidence=[RECEIPT])
        state.link("tool_a#r1", "job:jl-731", evidence=[DECLARED],
                   authority=EvidenceAuthority.SOURCE)
        state.derive()
        owed = [o.pattern for o in state.frontier()]
        assert ("job:jl-731", "payment_link", "acct-9") in owed
        assert ("job:jl-731", "admin_access", "acct-9") not in owed, \
            "the projected premise is satisfied, so it is not still owed"

    def test_the_summary_floor_is_the_weakest_of_the_subjects_facts(self):
        state = CognitiveState()
        state.assert_observation(("tool_a#r1", "state", "completed"),
                                 evidence=[RECEIPT],
                                 authority=EvidenceAuthority.DETERMINISTIC)
        state.assert_observation(("tool_b#r2", "owner", "ops"),
                                 evidence=[OTHER],
                                 authority=EvidenceAuthority.DETERMINISTIC)
        state.link("tool_a#r1", "job:jl-731", evidence=[DECLARED],
                   authority=EvidenceAuthority.DETERMINISTIC)
        state.link("tool_b#r2", "job:jl-731", evidence=[DECLARED],
                   authority=EvidenceAuthority.SOURCE)
        state.derive()
        summary = state.summarize([
            state.claim(("job:jl-731", "state", "completed")),
            state.claim(("job:jl-731", "owner", "ops"))])
        assert summary["floor_grade"] is EvidenceAuthority.SOURCE


class TestTheProjectionRuleBelongsToTheEngine:
    """It is not a rule anybody added and it is in no store's rule set — it
    is part of the engine, like the retraction cascade. What it needs is a
    name a proof step can carry and a lookup that cannot collide with a
    caller's."""

    def test_it_cannot_collide_with_a_rule_a_caller_adds(self):
        state = CognitiveState()
        rid = state.add_rule("controls", CONTROLS_HEAD, CONTROLS_BODY,
                             RuleAuthority.DOMAIN)
        assert rid.startswith("r")
        assert SUBJECT_SEPARATOR in PROJECTION_RULE_ID
        assert PROJECTION_RULE_ID not in [rule.id for rule in state.rules()]

    def test_it_is_not_content_and_does_not_appear_in_the_rules(self):
        state, _pid, _lid = TestProjectionCarriesTheFactWithoutMovingIt \
            ._linked()
        assert state.rules() == ()
        assert state.rule(PROJECTION_RULE_ID) is PROJECTION_RULE

    def test_it_is_built_in_because_it_cannot_be_written_down(self):
        """Its second premise is a link, not a triple — so its head variable
        is bound by nothing the body can state, and `add_rule` refuses it for
        range restriction. Correctly: that is what "not expressible as a
        rule" looks like from inside the rule language."""
        state = CognitiveState()
        with pytest.raises(RuleMalformed):
            state.add_rule(PROJECTION_RULE.name, PROJECTION_RULE.head,
                           PROJECTION_RULE.body, RuleAuthority.SYSTEM)

    def test_it_derives_because_it_is_system_authority(self):
        assert PROJECTION_RULE.authority is RuleAuthority.SYSTEM
        assert PROJECTION_RULE.participates_in_closure
