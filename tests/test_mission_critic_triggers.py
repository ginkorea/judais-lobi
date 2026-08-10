# tests/test_mission_critic_triggers.py

"""When a mission spends a critic call — which IS the cost model.

The critic is eleven working modules and it was built for the coding pipeline;
the mission path never reached it. The expensive way to fix that is to fire on
every turn, which turns a cheap local agent into two models on every turn and
gives back the reason it exists.

So the tests that matter are the ones asserting it does **not** fire. A
catalogue lookup, a lineage walk, a search that found nothing and a poll are
the ordinary traffic of a session, and any of them firing means the design is
wrong.
"""

import pytest

from core.critic.triggers import (
    MissionCriticContext,
    MissionTriggerConfig,
    should_invoke_mission_critic,
)


@pytest.fixture()
def config():
    return MissionTriggerConfig()


class TestItFiresWhereBeingWrongIsExpensive:
    def test_an_answer_kept_with_an_ungrounded_caveat(self, config):
        """The mechanical check found something and a repair did not fix it."""
        fire, why = should_invoke_mission_critic(
            MissionCriticContext(answered_with_caveat=True,
                                 unsupported_count=1), config)
        assert fire and why == "answered_with_caveat"

    def test_a_challenged_claim(self, config):
        """Under challenge the fluent move is a NEW figure, not a retraction."""
        fire, why = should_invoke_mission_critic(
            MissionCriticContext(mutation="claim_challenged"), config)
        assert fire and why == "claim_challenged"

    def test_a_draft_for_a_partner(self, config):
        fire, why = should_invoke_mission_critic(
            MissionCriticContext(audience="partner",
                                 draft_carries_figures=True), config)
        assert fire and why == "partner_audience"


class TestItDoesNotFireOnOrdinaryTraffic:
    """The half that decides whether this is affordable."""

    @pytest.mark.parametrize("context", [
        MissionCriticContext(audience="analyst"),
        MissionCriticContext(),                                # a lookup
        MissionCriticContext(mutation="target_switched"),
        MissionCriticContext(mutation="route_closed"),
        MissionCriticContext(mutation="constraint_added"),
        MissionCriticContext(audience="analyst", unsupported_count=0),
    ])
    def test_no_trigger(self, context, config):
        fire, why = should_invoke_mission_critic(context, config)
        assert not fire, why
        assert why == "no_trigger"

    def test_a_partner_answer_with_no_figures_does_not_fire(self, config):
        """A numeric verifier has nothing to do on a draft with no numbers.

        The boundary refusal is exactly this: a correct, careful, partner-
        facing answer that states a policy and cites no figure.
        """
        fire, why = should_invoke_mission_critic(
            MissionCriticContext(audience="partner",
                                 draft_carries_figures=False), config)
        assert not fire and why == "no_trigger"


class TestTheBudgetBinds:
    def test_an_exhausted_budget_refuses_even_a_real_trigger(self, config):
        fire, why = should_invoke_mission_critic(
            MissionCriticContext(answered_with_caveat=True,
                                 critic_calls_this_session=2), config)
        assert not fire and why == "budget_exhausted"

    def test_exhausted_is_distinguishable_from_untriggered(self, config):
        """Two different facts about a session.

        A report that cannot tell "nothing needed checking" from "we ran out
        of checks" cannot say whether the budget is set correctly.
        """
        _, exhausted = should_invoke_mission_critic(
            MissionCriticContext(answered_with_caveat=True,
                                 critic_calls_this_session=99), config)
        _, quiet = should_invoke_mission_critic(
            MissionCriticContext(), config)
        assert exhausted != quiet

    def test_the_mission_budget_is_smaller_than_the_coding_one(self):
        """A budget that never binds is not a budget.

        The coding tier allows ten calls across a session of many patches. A
        mission has one draft and, in a campaign, one challenge to it.
        """
        from core.critic.config import CriticConfig

        assert (MissionTriggerConfig().max_calls_per_session
                < CriticConfig().max_calls_per_session)

    def test_disabled_is_reported_as_disabled(self):
        fire, why = should_invoke_mission_critic(
            MissionCriticContext(answered_with_caveat=True),
            MissionTriggerConfig(enabled=False))
        assert not fire and why == "disabled"


class TestEachTriggerCanBeTurnedOffIndependently:
    """A deployment that wants only the challenge trigger can have it."""

    def test_turning_off_the_caveat_trigger_leaves_the_others(self):
        config = MissionTriggerConfig(on_ungrounded_caveat=False)
        quiet, _ = should_invoke_mission_critic(
            MissionCriticContext(answered_with_caveat=True), config)
        assert not quiet
        fires, why = should_invoke_mission_critic(
            MissionCriticContext(mutation="claim_challenged"), config)
        assert fires and why == "claim_challenged"


class TestTheExpectedFiringRate:
    """~2 of 8 missions, asserted rather than asserted in prose.

    The suite is the closest thing to a real workload anybody has measured, so
    the cost model is checked against it: the read-only missions must not fire
    and the drafting one must.
    """

    #: The eight missions as the harness runs them today: audience is not set
    #: (so `analyst`), no campaign mutation, and only the synthesis mission
    #: produces a draft the grounding check can fail.
    SUITE = {
        "catalogue_recon": MissionCriticContext(),
        "lineage_archaeology": MissionCriticContext(),
        "absence_is_an_answer": MissionCriticContext(
            draft_carries_figures=False),
        "withdrawn_is_not_available": MissionCriticContext(),
        "the_boundary_holds": MissionCriticContext(
            draft_carries_figures=False),
        "two_halves_of_the_pipeline": MissionCriticContext(),
        "submit_and_follow": MissionCriticContext(),
        # The one that fabricated: its draft failed grounding and was kept
        # with a caveat.
        "read_a_finished_run": MissionCriticContext(
            answered_with_caveat=True, unsupported_count=1,
            audience="partner"),
    }

    def test_only_the_drafting_mission_fires(self):
        config = MissionTriggerConfig()
        fired = {key for key, ctx in self.SUITE.items()
                 if should_invoke_mission_critic(ctx, config)[0]}
        assert fired == {"read_a_finished_run"}, (
            f"the critic fires on {sorted(fired)}. Anything beyond the "
            f"drafting missions is a second model on ordinary traffic, which "
            f"is the expense the local agent exists to avoid.")

    def test_a_partner_audience_would_add_one_more(self):
        """Set the audience an analyst would set and the rate is 2 of 8."""
        config = MissionTriggerConfig()
        suite = dict(self.SUITE)
        suite["two_halves_of_the_pipeline"] = MissionCriticContext(
            audience="partner", draft_carries_figures=True)
        fired = {k for k, c in suite.items()
                 if should_invoke_mission_critic(c, config)[0]}
        assert len(fired) == 2, sorted(fired)
