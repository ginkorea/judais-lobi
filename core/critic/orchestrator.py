# core/critic/orchestrator.py — Multi-round critic coordinator

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, List, Optional, Set

from core.critic.backends import create_backend
from core.critic.cache import CriticCache
from core.critic.config import CriticConfig
from core.critic.keystore import CriticKeystore
from core.critic.models import (
    AggregatedCriticReport,
    CriticRoundSummary,
    CriticVerdict,
    ExternalCriticReport,
)
from core.critic.pack_builder import CritiquePackBuilder
from core.critic.redactor import Redactor


class CriticOrchestrator:
    def __init__(self, config: CriticConfig, audit=None,
                 keystore: Optional[CriticKeystore] = None,
                 cache: Optional[CriticCache] = None):
        self._config = config
        self._audit = audit
        self._keystore = keystore or CriticKeystore()
        self._cache = cache or CriticCache(config.cache_dir)
        self._builder = CritiquePackBuilder()
        self._calls_this_session = 0
        self._round_history: List[CriticRoundSummary] = []
        self._backends = {}

        if self._config.enabled:
            for provider_cfg in self._config.providers:
                if not provider_cfg.enabled:
                    continue
                provider_name = provider_cfg.provider.lower()
                key = self._keystore.get_key(
                    provider_name,
                    provider_cfg.api_key_env_var,
                    provider_cfg.keyring_key,
                    provider_cfg.keyring_service,
                )
                if not key:
                    continue
                backend = create_backend(
                    provider_name,
                    key,
                    provider_cfg.model,
                )
                if backend is not None:
                    self._backends[provider_name] = (backend, provider_cfg)

    @property
    def is_available(self) -> bool:
        return bool(self._config.enabled and self._backends)

    @property
    def config(self) -> CriticConfig:
        return self._config

    @property
    def calls_this_session(self) -> int:
        return self._calls_this_session

    @property
    def round_history(self) -> List[CriticRoundSummary]:
        return list(self._round_history)

    def reset_session(self) -> None:
        self._calls_this_session = 0
        self._round_history = []

    def invoke(self, state, trigger_reason: str, session_manager=None) -> AggregatedCriticReport:
        if not self.is_available:
            return AggregatedCriticReport(
                consensus_verdict=CriticVerdict.UNAVAILABLE,
                timestamp=datetime.now(timezone.utc),
            )

        pack = self._builder.build(state, trigger_reason, session_manager)
        payload = pack.model_dump_json()

        redactor = Redactor(level=self._config.redaction_level,
                            max_bytes=self._config.max_payload_bytes)
        redacted, payload_hash, was_clamped, original_size = redactor.redact_and_clamp(payload)

        if self._config.cache_enabled:
            cached = self._cache.get(payload_hash)
            if cached is not None:
                return cached

        reports = []
        for provider, (backend, cfg) in self._backends.items():
            max_tokens = cfg.max_tokens_per_call or self._config.max_tokens_per_call
            report = backend.critique(
                redacted,
                cfg.model or backend.default_model,
                max_tokens,
                cfg.timeout_seconds,
            )
            report.provider = provider
            report.model = cfg.model or backend.default_model
            report.payload_hash = payload_hash
            reports.append(report)

        aggregated = self._aggregate(reports, payload_hash)
        if self._config.cache_enabled:
            self._cache.put(payload_hash, aggregated)

        self._calls_this_session += 1
        return aggregated

    def invoke_multi_round(
        self,
        state,
        trigger_reason: str,
        session_manager=None,
        revision_callback=None,
    ) -> AggregatedCriticReport:
        report = AggregatedCriticReport(consensus_verdict=CriticVerdict.UNAVAILABLE)
        current_concerns: Set[str] = set()

        max_rounds = max(1, self._config.max_rounds_per_invocation)
        for round_number in range(1, max_rounds + 1):
            report = self.invoke(state, trigger_reason, session_manager)
            report.round_number = round_number

            new_concerns = _collect_concerns(report)
            new_count = len(new_concerns - current_concerns)
            unique_count = len(new_concerns)
            is_noise = self._detect_noise(report, current_concerns)

            summary = CriticRoundSummary(
                round_number=round_number,
                verdict=report.consensus_verdict,
                unique_concerns_count=unique_count,
                new_concerns_count=new_count,
                mean_confidence=report.mean_confidence,
                is_noise=is_noise,
            )
            self._round_history.append(summary)

            if report.consensus_verdict in (
                CriticVerdict.APPROVE,
                CriticVerdict.CAUTION,
                CriticVerdict.REFUSED,
                CriticVerdict.UNAVAILABLE,
            ):
                break

            if report.consensus_verdict == CriticVerdict.BLOCK:
                if is_noise:
                    break
                if revision_callback is None:
                    break
                revised = revision_callback(report, state)
                if not revised:
                    break

            current_concerns = new_concerns

        return report

    def _aggregate(
        self,
        reports: List[ExternalCriticReport],
        payload_hash: str,
    ) -> AggregatedCriticReport:
        if not reports:
            return AggregatedCriticReport(
                consensus_verdict=CriticVerdict.UNAVAILABLE,
                payload_hash=payload_hash,
                timestamp=datetime.now(timezone.utc),
            )

        consensus = _compute_consensus([r.verdict for r in reports])
        all_risks = _dedupe_risks([r for rep in reports for r in rep.top_risks])
        all_missing_tests = _dedupe_strings([s for rep in reports for s in rep.missing_tests])
        all_logic_concerns = _dedupe_strings([s for rep in reports for s in rep.logic_concerns])
        all_suggested = _dedupe_strings([
            *[s for rep in reports for s in rep.suggested_plan_adjustments],
            *[s for rep in reports for s in rep.suggested_patch_adjustments],
        ])
        mean_conf = sum(r.confidence for r in reports) / max(len(reports), 1)

        return AggregatedCriticReport(
            provider_reports=reports,
            consensus_verdict=consensus,
            all_risks=all_risks,
            all_missing_tests=all_missing_tests,
            all_logic_concerns=all_logic_concerns,
            all_suggested_adjustments=all_suggested,
            mean_confidence=mean_conf,
            payload_hash=payload_hash,
            timestamp=datetime.now(timezone.utc),
        )

    def _detect_noise(self, report: AggregatedCriticReport,
                      prior_concerns: Set[str]) -> bool:
        if report.round_number <= 1:
            return False

        signals = []
        if report.mean_confidence < self._config.noise_confidence_threshold:
            signals.append("low_confidence")

        current_concerns = _collect_concerns(report)
        overlap_ratio = _overlap_ratio(current_concerns, prior_concerns)
        if overlap_ratio >= self._config.noise_overlap_ratio:
            signals.append("overlap")

        new_count = len(current_concerns - prior_concerns)
        if new_count == 0:
            signals.append("no_new_concerns")

        if _stable_caution(self._round_history, report.consensus_verdict):
            signals.append("stable_caution")

        return bool(signals)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_consensus(verdicts: Iterable[CriticVerdict]) -> CriticVerdict:
    verdicts = list(verdicts)
    if any(v == CriticVerdict.BLOCK for v in verdicts):
        return CriticVerdict.BLOCK
    if any(v == CriticVerdict.CAUTION for v in verdicts):
        return CriticVerdict.CAUTION
    if any(v == CriticVerdict.APPROVE for v in verdicts):
        return CriticVerdict.APPROVE
    if any(v == CriticVerdict.REFUSED for v in verdicts):
        return CriticVerdict.REFUSED
    return CriticVerdict.UNAVAILABLE


def _dedupe_strings(values: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for item in values:
        if not item:
            continue
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _dedupe_risks(risks: Iterable) -> List:
    seen = set()
    result = []
    for risk in risks:
        key = (risk.severity, risk.category, risk.description)
        if key in seen:
            continue
        seen.add(key)
        result.append(risk)
    return result


def _collect_concerns(report: AggregatedCriticReport) -> Set[str]:
    concerns = set(report.all_logic_concerns)
    concerns.update(report.all_missing_tests)
    concerns.update(r.description for r in report.all_risks if r.description)
    concerns.update(report.all_suggested_adjustments)
    return {c for c in concerns if c}


def _overlap_ratio(current: Set[str], prior: Set[str]) -> float:
    if not current:
        return 0.0
    if not prior:
        return 0.0
    overlap = len(current & prior)
    return overlap / max(len(current), 1)


def _stable_caution(history: List[CriticRoundSummary],
                    current_verdict: CriticVerdict) -> bool:
    if current_verdict != CriticVerdict.CAUTION:
        return False
    if len(history) < 2:
        return False
    last_two = history[-2:]
    return all(r.verdict == CriticVerdict.CAUTION for r in last_two)
