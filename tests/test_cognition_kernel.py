# tests/test_cognition_kernel.py — the walls, the closure, and the frontier

"""What the epistemic kernel refuses, what it derives, and what it still owes.

Four things are checked here and they are not the same thing.

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

Replay, the event log and the incrementality of closure are in
``tests/test_cognition_replay.py``.
"""

import pytest

from core.cognition import (AUTHORITY_RANK, CONTRADICTION_KINDS,
                            HYPOTHESIS_AUTHORITIES,
                            OBSERVATION_AUTHORITIES, TRUSTED_RULE_AUTHORITIES,
                            AuthorityRefused, CognitionError, CognitiveState,
                            EvidenceAuthority, EvidenceRef, ObligationState,
                            PropositionStatus, RuleAuthority, RuleMalformed,
                            UnknownId, value_tag)

RECEIPT = EvidenceRef(kind="receipt", locator="seq:1", note="read_file")
OTHER = EvidenceRef(kind="receipt", locator="seq:2")
EXTRACTED = EvidenceRef(kind="extraction", locator="turn:3")


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

    def test_two_hypotheses_disagreeing_with_each_other_are_not_reported(self):
        """v1 bound, said by a test so it is a decision: this report is about
        a model's claim against the *store's*. Two guesses disagreeing is the
        model being uncertain, which is not news."""
        state = CognitiveState()
        state.assert_hypothesis(("job-7", "total_s", 186.7),
                                evidence=[EXTRACTED])
        state.assert_hypothesis(("job-7", "total_s", 200.0),
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
