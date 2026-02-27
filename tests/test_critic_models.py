# tests/test_critic_models.py — Tests for core.critic.models

from datetime import datetime

from core.critic.models import (
    CriticVerdict,
    CriticRisk,
    ExternalCriticReport,
    AggregatedCriticReport,
    CriticRoundSummary,
    CritiquePack,
    CriticTriggerContext,
)


class TestCriticVerdict:
    def test_values(self):
        assert CriticVerdict.APPROVE == "approve"
        assert CriticVerdict.CAUTION == "caution"
        assert CriticVerdict.BLOCK == "block"
        assert CriticVerdict.REFUSED == "refused"
        assert CriticVerdict.UNAVAILABLE == "unavailable"

    def test_str_enum(self):
        assert isinstance(CriticVerdict.APPROVE, str)
        assert CriticVerdict("approve") is CriticVerdict.APPROVE


class TestCriticRisk:
    def test_defaults(self):
        risk = CriticRisk()
        assert risk.severity == "medium"
        assert risk.category == ""
        assert risk.description == ""
        assert risk.affected_files == []
        assert risk.confidence == 0.5

    def test_roundtrip(self):
        risk = CriticRisk(severity="high", category="logic",
                          description="missing check", affected_files=["a.py"],
                          confidence=0.8)
        data = risk.model_dump()
        risk2 = CriticRisk.model_validate(data)
        assert risk2.severity == "high"
        assert risk2.affected_files == ["a.py"]


class TestExternalCriticReport:
    def test_defaults(self):
        report = ExternalCriticReport()
        assert report.verdict == CriticVerdict.UNAVAILABLE
        assert isinstance(report.timestamp, datetime)

    def test_roundtrip(self):
        report = ExternalCriticReport(provider="openai", model="gpt",
                                      verdict=CriticVerdict.APPROVE,
                                      confidence=0.6)
        data = report.model_dump()
        report2 = ExternalCriticReport.model_validate(data)
        assert report2.provider == "openai"
        assert report2.verdict == CriticVerdict.APPROVE


class TestAggregatedCriticReport:
    def test_defaults(self):
        report = AggregatedCriticReport()
        assert report.consensus_verdict == CriticVerdict.UNAVAILABLE
        assert report.provider_reports == []

    def test_roundtrip(self):
        child = ExternalCriticReport(provider="openai",
                                     verdict=CriticVerdict.CAUTION)
        report = AggregatedCriticReport(provider_reports=[child],
                                        consensus_verdict=CriticVerdict.CAUTION,
                                        mean_confidence=0.2)
        data = report.model_dump()
        report2 = AggregatedCriticReport.model_validate(data)
        assert report2.consensus_verdict == CriticVerdict.CAUTION
        assert len(report2.provider_reports) == 1


class TestCriticRoundSummary:
    def test_construction(self):
        summary = CriticRoundSummary(
            round_number=1,
            verdict=CriticVerdict.CAUTION,
            unique_concerns_count=3,
            new_concerns_count=2,
            mean_confidence=0.4,
        )
        assert summary.is_noise is False


class TestCritiquePack:
    def test_defaults(self):
        pack = CritiquePack()
        assert pack.task_description == ""
        assert pack.plan_steps == []
        assert pack.patch_snippets == []

    def test_roundtrip(self):
        pack = CritiquePack(task_description="t", files_changed=2)
        data = pack.model_dump()
        pack2 = CritiquePack.model_validate(data)
        assert pack2.files_changed == 2


class TestCriticTriggerContext:
    def test_defaults(self):
        ctx = CriticTriggerContext(current_phase="PLAN", next_phase="RETRIEVE",
                                   total_iterations=3)
        assert ctx.consecutive_fix_loops == 0
        assert ctx.critic_calls_this_session == 0
