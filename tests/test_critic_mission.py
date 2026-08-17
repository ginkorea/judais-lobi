# tests/test_critic_mission.py — the critic on the mission path

"""The second opinion, and the one rule it must never break.

`core/critic/` was built, tested and unreachable: nothing in `core/`
constructed a `CriticOrchestrator`, and `critic/triggers.py` had written
down when a mission earns a second pass without anybody ever asking it.
This is the caller, and these are the two things worth asserting about it.

**It never moves `grounded`.** That field is a mechanical fact — this token
is in this payload, this path resolves to this value — reproducible by
anyone holding the transcript. A critic's verdict is a model's opinion, and
folding one into the other would make a governance field unreproducible
without changing how the record looks. So the verdict arrives as one more
row in `grounding.checks`, marked `advisory`.

**A missing provider is said out loud.** "We asked and nobody answered" and
"we never asked" are different facts about a deployment, and a tier that
reported them alike would let a control quietly not exist.
"""

from __future__ import annotations

import json

import pytest

from core.critic.config import CriticConfig, CriticProviderConfig
from core.critic.mission import (
    FAIL,
    LOCAL_ENDPOINT_ENV,
    MISSION_CRITIC_SYSTEM_PROMPT,
    PASS,
    SKIPPED,
    CriticOpinion,
    MissionCritic,
)
from core.critic.models import CriticRisk, CriticVerdict, ExternalCriticReport
from core.critic.triggers import MissionTriggerConfig


class StubBackend:
    """Answers with a fixed report and remembers what it was shown."""

    provider_name = "stub"

    def __init__(self, report=None):
        self.report = report or ExternalCriticReport(
            provider="stub", verdict=CriticVerdict.APPROVE)
        self.calls = []

    def critique(self, payload_json, model, max_tokens, timeout,
                 system=""):
        self.calls.append({"payload": payload_json, "model": model,
                           "max_tokens": max_tokens, "system": system})
        return self.report


def critic(backend=None, **kw):
    """A critic that reads no config file and no real environment."""
    kw.setdefault("environ", {})
    return MissionCritic(CriticConfig(), backend=backend, **kw)


# ── when it fires at all ─────────────────────────────────────────────────────

class TestItFiresOnlyWhereTheTriggersSayItMay:
    """`core.critic.triggers` owns the cost model. Nothing here restates it.

    A second copy of the policy written in `if`s inside the mission loop is
    how two budgets come to disagree, which the trigger module says in as
    many words is worse than either.
    """

    def test_a_clean_answer_earns_nothing(self):
        backend = StubBackend()
        assert critic(backend).review("an answer", [],
                                      answered_with_caveat=False) is None
        assert backend.calls == [], "a clean answer cost a model call"

    def test_an_ungrounded_caveat_earns_a_pass(self):
        opinion = critic(StubBackend()).review(
            "an answer", [], answered_with_caveat=True)
        assert opinion is not None
        assert opinion.reason == "answered_with_caveat"

    def test_no_row_and_a_skipped_row_are_different_answers(self):
        """`None` is "nobody asked"; `skipped` is "a rule fired and nobody
        could answer". A deployment has to be able to tell those apart."""
        unreachable = critic(None)
        assert unreachable.review("a", [], answered_with_caveat=False) is None
        skipped = unreachable.review("a", [], answered_with_caveat=True)
        assert skipped.verdict == SKIPPED

    def test_the_budget_binds(self):
        """Two calls per session: one draft and, in a campaign, one
        challenge to it. A budget that never bound would not be one."""
        agent = critic(StubBackend(),
                       trigger=MissionTriggerConfig(max_calls_per_session=1))
        assert agent.review("a", [], answered_with_caveat=True) is not None
        assert agent.review("a", [], answered_with_caveat=True) is None
        assert agent.calls == 1


# ── the verdict sits beside the mechanical one ───────────────────────────────

class TestTheVerdictIsAdvisory:
    def test_a_pass_row(self):
        row = critic(StubBackend()).review(
            "a", [], answered_with_caveat=True).as_check()
        assert row["check"] == "critic"
        assert row["verdict"] == PASS
        assert row["advisory"] is True

    def test_a_fail_row_says_what_it_disputes(self):
        backend = StubBackend(ExternalCriticReport(
            provider="stub", verdict=CriticVerdict.BLOCK,
            logic_concerns=["80.847 is a duration, not a score"]))
        row = critic(backend).review(
            "a", [], answered_with_caveat=True).as_check()
        assert row["verdict"] == FAIL
        assert row["unsupported"] == ["80.847 is a duration, not a score"]
        assert "duration" in row["detail"]

    def test_a_fail_row_is_still_marked_advisory(self):
        """The load-bearing flag. Without it a consumer recomputing a
        verdict from the rows would be folding a model's opinion into a
        mechanical fact, and the record would look identical."""
        backend = StubBackend(ExternalCriticReport(
            verdict=CriticVerdict.CAUTION, logic_concerns=["hm"]))
        row = critic(backend).review(
            "a", [], answered_with_caveat=True).as_check()
        assert row["verdict"] == FAIL
        assert row["advisory"] is True

    def test_the_row_carries_every_key_a_mechanical_row_carries(self):
        row = critic(StubBackend()).review(
            "a", [], answered_with_caveat=True).as_check()
        assert set(row) == {
            "check", "advisory", "configured", "grounded", "verdict",
            "considered", "minimum", "unsupported", "detail"}, (
            "a consumer indexing checks[i]['configured'] must not fall over "
            "on this row")

    def test_a_risk_with_no_logic_concern_still_reaches_the_row(self):
        backend = StubBackend(ExternalCriticReport(
            verdict=CriticVerdict.BLOCK,
            top_risks=[CriticRisk(description="the SDK was never called")]))
        row = critic(backend).review(
            "a", [], answered_with_caveat=True).as_check()
        assert row["unsupported"] == ["the SDK was never called"]

    @pytest.mark.parametrize("verdict", [CriticVerdict.REFUSED,
                                         CriticVerdict.UNAVAILABLE])
    def test_a_critic_that_did_not_answer_is_not_a_pass(self, verdict):
        """UNKNOWN, not 0.5 — the rule every tier in this package has. A
        critic that could not be reached has found nothing AND checked
        nothing, and those must not report alike."""
        opinion = critic(StubBackend(ExternalCriticReport(
            verdict=verdict, raw_response="503"))).review(
                "a", [], answered_with_caveat=True)
        assert opinion.verdict == SKIPPED
        assert "503" in opinion.detail


# ── what it is shown ─────────────────────────────────────────────────────────

class TestThePayload:
    def test_it_carries_the_answer_the_evidence_and_the_findings(self):
        backend = StubBackend()
        critic(backend).review(
            "the answer", ['{"gate": {"confidence": 0.7446}}'],
            objective="what happened", unsupported=("0.7448",),
            answered_with_caveat=True)
        payload = json.loads(backend.calls[0]["payload"])
        assert payload["answer"] == "the answer"
        assert payload["objective"] == "what happened"
        assert payload["mechanically_unsupported"] == ["0.7448"]
        assert payload["tool_results"] == ['{"gate": {"confidence": 0.7446}}']

    def test_the_credentials_never_leave(self):
        backend = StubBackend()
        critic(backend).review(
            "ran with sk-abcdef123456789012345678901234567890", [],
            answered_with_caveat=True)
        assert "sk-abcdef" not in backend.calls[0]["payload"]

    def test_each_tool_result_is_bounded_on_its_own(self):
        """Per result, not in total: a budget spent end to end would hand
        the critic the whole of the first payload and none of the last, and
        the claim under review is as likely to be in one as the other."""
        backend = StubBackend()
        agent = MissionCritic(CriticConfig(), backend=backend, environ={},
                              max_evidence_chars=50)
        agent.review("a", ["x" * 400, "y" * 400], answered_with_caveat=True)
        payload = json.loads(backend.calls[0]["payload"])
        assert len(payload["tool_results"]) == 2
        assert all(t.endswith("…[cut]") for t in payload["tool_results"])

    def test_the_job_is_adversarial_and_is_not_the_code_reviewers(self):
        backend = StubBackend()
        critic(backend).review("a", [], answered_with_caveat=True)
        system = backend.calls[0]["system"]
        assert system == MISSION_CRITIC_SYSTEM_PROMPT
        assert "missing_tests" not in system, (
            "a critic told to look for missing tests on a mission answer "
            "looks for them")
        assert "not to agree with it" in system


# ── who answers ──────────────────────────────────────────────────────────────

class TestProviderResolution:
    """Local first, and it is `core.critic.triggers`' conclusion, not a new
    one: the local plane is the only tier guaranteed to exist and the only
    one that keeps a governed draft on the box it was produced on."""

    def test_a_local_endpoint_is_enough(self):
        agent = MissionCritic(CriticConfig(),
                              environ={LOCAL_ENDPOINT_ENV: "http://x:8000/v1"})
        assert agent.available
        assert agent.provider == "local"

    def test_local_wins_over_a_configured_frontier_provider(self):
        """Escalation is a handling decision. Posting actor names and scores
        to another company is not settled by whichever provider had a key."""
        config = CriticConfig(enabled=True, providers=[
            CriticProviderConfig(provider="anthropic", model="m",
                                 api_key_env_var="ANTHROPIC_API_KEY")])
        agent = MissionCritic(
            config, environ={LOCAL_ENDPOINT_ENV: "http://x:8000/v1"},
            keystore=_Keystore("a-key"))
        assert agent.provider == "local"

    def test_a_frontier_provider_is_reached_when_declared_and_keyed(self):
        config = CriticConfig(enabled=True, providers=[
            CriticProviderConfig(provider="anthropic", model="m",
                                 api_key_env_var="ANTHROPIC_API_KEY")])
        agent = MissionCritic(config, environ={},
                              keystore=_Keystore("a-key"))
        assert agent.provider == "anthropic"

    def test_a_key_with_no_declaration_is_not_a_decision(self):
        """`critic.enabled` false: a key in the environment is not a
        deployment saying it wants governed drafts posted anywhere."""
        config = CriticConfig(enabled=False, providers=[
            CriticProviderConfig(provider="anthropic", model="m")])
        agent = MissionCritic(config, environ={}, keystore=_Keystore("a-key"))
        assert agent.available is False

    def test_a_declaration_with_no_key_refuses_and_names_what_is_missing(self):
        config = CriticConfig(enabled=True, providers=[
            CriticProviderConfig(provider="anthropic", model="m",
                                 api_key_env_var="ANTHROPIC_API_KEY")])
        agent = MissionCritic(config, environ={}, keystore=_Keystore(None))
        opinion = agent.review("a", [], answered_with_caveat=True)
        assert opinion.verdict == SKIPPED
        assert LOCAL_ENDPOINT_ENV in opinion.detail
        assert "ANTHROPIC_API_KEY" in opinion.detail

    def test_nothing_configured_at_all_says_where_to_configure_it(self):
        opinion = MissionCritic(CriticConfig(), environ={}).review(
            "a", [], answered_with_caveat=True)
        assert opinion.verdict == SKIPPED
        assert ".judais-lobi.yml" in opinion.detail


class _Keystore:
    def __init__(self, key):
        self.key = key

    def get_key(self, *args, **kwargs):
        return self.key


# ── the local backend is the one that already exists ─────────────────────────

class TestTheLocalCriticSpeaksThroughLocalBackend:
    """Not a second HTTP client. `LocalBackend` already repairs a base URL
    missing its `/v1`, strips the harmony tokens a served gpt-oss would 500
    on, and reports what model is loaded — a `requests.post` here would be a
    second owner of all of it."""

    def test_the_backend_is_a_localbackend(self):
        from core.critic.backends import LocalCritic
        from core.runtime.backends.local_backend import LocalBackend

        assert isinstance(LocalCritic(endpoint="http://x:8000/v1").backend,
                          LocalBackend)

    def test_it_declares_no_tools(self):
        """A harmony model with a function namespace declared answers a
        yes/no question with a tool call — the reason `plain_chat_fn`
        declares none either."""
        from core.critic.backends import LocalCritic

        backend = LocalCritic(endpoint="http://x:8000/v1").backend
        assert backend.capabilities.supports_tool_calls is False

    def test_the_reply_is_parsed_by_the_shared_parser(self):
        from core.critic.backends import LocalCritic

        class Chatty:
            def chat(self, model, messages, stream=False, **kw):
                return ('Sure!\n```json\n{"verdict": "block", '
                        '"logic_concerns": ["no"]}\n```')

        report = LocalCritic(backend=Chatty()).critique("{}", "m", 512, 30.0)
        assert report.verdict == CriticVerdict.BLOCK
        assert report.provider == "local"

    def test_an_unreachable_server_is_unavailable_not_an_exception(self):
        from core.critic.backends import LocalCritic

        class Dead:
            def chat(self, *a, **kw):
                raise OSError("connection refused")

        report = LocalCritic(backend=Dead()).critique("{}", "m", 512, 30.0)
        assert report.verdict == CriticVerdict.UNAVAILABLE
        assert "connection refused" in report.raw_response

    def test_it_is_in_the_registry(self):
        from core.critic.backends import LocalCritic, create_backend

        assert isinstance(create_backend("local", "", ""), LocalCritic)


def test_a_skipped_opinion_is_the_default_shape():
    """Constructed with nothing, `CriticOpinion` says it has no opinion."""
    assert CriticOpinion().verdict == SKIPPED
    assert CriticOpinion().as_check()["configured"] is False
