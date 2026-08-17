# core/critic/mission.py — a second opinion on a mission answer

"""Ask a model whether the draft holds up, and put the answer BESIDE the
mechanical verdict rather than inside it.

:mod:`core.critic.triggers` had already decided when this is worth paying
for and wrote the reasoning down: the mission tier fires on
``answered_with_caveat`` — the grounding check found something it could
not support and one repair turn did not fix it, so the draft is going out
with a warning on it and a reader is about to be asked to judge it — on a
partner-audience draft, and on a challenged claim.  It fires on none of a
catalogue lookup, a lineage walk, a search that found nothing.  What was
missing was a caller: nothing in ``core/`` constructed a critic at all,
which is why the whole subsystem sat in ``ROADMAP`` §1.2's *built, tested,
unreachable* row.  This is that caller.

**The critic never moves ``grounded``.**  That is the one rule this module
exists to hold.  ``grounded`` is a mechanical fact — this token is in this
payload, this path resolves to this value — reproducible by anyone holding
the transcript, and it is what a governance report is entitled to rely on.
A critic's verdict is a *model's opinion*: it varies with sampling, with
which provider had a key today, with a prompt somebody may edit next
month.  Latching an opinion onto a mechanical field would make the field
unreproducible, and it would do it silently — the record would look
exactly the same.  So the verdict arrives as one more row in
``grounding.checks``, marked ``advisory``, sitting next to the checks that
did the arithmetic and read by a human who can weigh the difference.

**The provider is resolved local-first**, which is also
:mod:`~core.critic.triggers`' conclusion and not a new one: the local
plane is "the ONLY tier guaranteed to exist", and escalating to a hosted
model means posting a governed draft — actor names, scores, a corpus hash
— to another company, which is a handling decision a deployment makes
explicitly in its critic config rather than one this module makes by
noticing an environment variable.

Off by default at every layer.  A skill turns it on with ``critic: true``
in its ``grounding:`` block; with no provider reachable the row says
``skipped`` and names what was missing, because "we asked and nobody
answered" and "we never asked" are different facts about a run.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

from core.critic.backends import CriticBackend, create_backend
from core.critic.config import CriticConfig, load_critic_config
from core.critic.keystore import CriticKeystore
from core.critic.models import CriticVerdict
from core.critic.redactor import Redactor
from core.critic.triggers import (
    MissionCriticContext, MissionTriggerConfig, should_invoke_mission_critic,
)

#: The critic looked and found nothing it would contradict.
PASS = "pass"
#: The critic disputes the draft.  **Advisory** — see the module docstring.
FAIL = "fail"
#: Nobody was asked, or nobody answered, and the row says which.
SKIPPED = "skipped"

#: The closed vocabulary of the ``critic`` row's ``verdict``.
CRITIC_VERDICTS = (PASS, FAIL, SKIPPED)

#: The environment variable naming a local endpoint, read by
#: :class:`~core.runtime.backends.local_backend.LocalBackend` and named here
#: only so the refusal can say what to set.
LOCAL_ENDPOINT_ENV = "LOCAL_API_BASE"

#: The adversarial job, and the reason a same-family critic is worth
#: anything at all.
#:
#: :mod:`core.runtime.reading` measured the failure this is written around:
#: a reader shown a claim *adopts* it, and on an opaque field it simply
#: ratifies whatever the sentence proposes.  The counter is to give the
#: reader a job it can only do by disagreeing — find what the draft cannot
#: support — and to tell it, in as many words, that saying "looks fine" to
#: a draft that is already carrying an ungrounded caveat is the failure
#: mode.  The verdict vocabulary is the coding critic's, so one parser
#: reads every provider: ``approve`` is a pass and ``caution``/``block``
#: are a fail.
MISSION_CRITIC_SYSTEM_PROMPT = """\
You are an adversarial reviewer of an analytical answer. The answer has \
already failed a mechanical grounding check, which means at least one thing \
in it could not be traced to a tool result. Your job is to find what is \
wrong with it, not to agree with it.

You are given the objective, the answer, what the mechanical check could \
not support, and the tool results the answer was drawn from. Judge ONLY \
against those tool results. You have no other knowledge of this run and \
must not supply any.

Look for: a figure attributed to the wrong field; a quantity described as \
something it is not; an identifier that appears nowhere in the evidence; a \
claim about work that was done, with nothing in the evidence showing it \
was; a conclusion wider than what the evidence supports.

"approve" means you looked and found nothing you would contradict. Saying \
that about an answer already carrying an ungrounded caveat is the failure \
this review exists to prevent, so say it only if you mean it.

Reply with exactly one JSON object and no other text:
{"verdict": "approve" or "caution" or "block",
 "logic_concerns": ["<one sentence each, quoting the words at fault>"],
 "confidence": 0.0 to 1.0}
"""


@dataclass(frozen=True)
class CriticOpinion:
    """What the critic said, in the shape a ``grounding.checks`` row takes.

    One owner of the row: the mission's record writer appends whatever
    :meth:`as_check` returns and reads none of the fields itself, so the
    day the critic grows something to say it is said here and not in two
    places.
    """

    verdict: str = SKIPPED
    detail: str = ""
    #: Which provider answered, or ``""`` when none did.
    provider: str = ""
    #: The trigger rule that asked for this, from
    #: :func:`~core.critic.triggers.should_invoke_mission_critic`.
    reason: str = ""
    #: What the critic disputed, one sentence each.
    concerns: Sequence[str] = ()

    def as_check(self) -> Dict[str, Any]:
        """This opinion as one row of ``grounding.checks``.

        The row carries every key the mechanical rows carry, so a consumer
        indexing ``checks[i]["configured"]`` does not fall over on it, plus
        ``advisory``.  **That flag is the load-bearing part**: the top-level
        ``grounded`` is computed without this row, and a consumer that
        recomputed a verdict by ``all(row["grounded"] for row in checks)``
        would otherwise be folding a model's opinion into a mechanical
        fact.  ``advisory`` is how a row says *do not*.
        """
        return {
            "check": "critic",
            "advisory": True,
            "configured": self.verdict != SKIPPED,
            # Its own opinion, and excluded from the mission's `grounded`
            # by `advisory`. See the module docstring.
            "grounded": self.verdict != FAIL,
            "verdict": self.verdict,
            "considered": len(self.concerns),
            "minimum": 0,
            "unsupported": list(self.concerns),
            "detail": self.detail,
        }


class MissionCritic:
    """Resolves a provider once, then answers one question per mission turn.

    Parameters
    ----------
    config:
        A :class:`~core.critic.config.CriticConfig`.  Loaded from the
        deployment's own files when omitted — ``~/.judais-lobi/critic.yml``
        and a project's ``.judais-lobi.yml`` ``critic:`` section.  Nothing
        new was invented for this: escalation to a hosted provider is
        declared where it was always declared.
    trigger:
        A :class:`~core.critic.triggers.MissionTriggerConfig`.  Its default
        budget is two calls per session — a mission has one draft and, in a
        campaign, one challenge to it, and a budget that allowed more would
        be a budget that never bound.
    backend:
        A ready :class:`~core.critic.backends.CriticBackend`, for a caller
        that has already chosen one and for tests.  Given one, no
        resolution happens and no environment is read.
    """

    def __init__(
        self,
        config: Optional[CriticConfig] = None,
        *,
        trigger: Optional[MissionTriggerConfig] = None,
        keystore: Optional[CriticKeystore] = None,
        backend: Optional[CriticBackend] = None,
        environ: Optional[Dict[str, str]] = None,
        max_evidence_chars: int = 20_000,
    ):
        self._config = config if config is not None else load_critic_config()
        self._trigger = trigger or MissionTriggerConfig()
        self._keystore = keystore or CriticKeystore()
        self._environ = os.environ if environ is None else environ
        self._max_evidence_chars = max(0, int(max_evidence_chars))
        self._calls = 0
        self._provider_config = None
        if backend is not None:
            self._backend: Optional[CriticBackend] = backend
            self._why_not = ""
        else:
            self._backend, self._why_not = self._resolve()

    # ── who answers ─────────────────────────────────────────────────────

    def _resolve(self):
        """``(backend, why not)``; exactly one is meaningful.

        **Local first.**  Not a fallback: :mod:`core.critic.triggers` argues
        it at length and the argument is that the local plane is the only
        one guaranteed to exist, and the only one that keeps a governed
        draft on the box it was produced on.  A hosted provider is reached
        only where a deployment wrote ``enabled: true`` into its critic
        config and a key resolves for it — an explicit handling decision,
        not a consequence of an API key happening to be in the environment.
        """
        if self._environ.get(LOCAL_ENDPOINT_ENV):
            backend = create_backend("local", "", "")
            if backend is not None:
                return backend, ""

        if self._config.enabled:
            for provider in self._config.providers:
                if not provider.enabled:
                    continue
                key = self._keystore.get_key(
                    provider.provider.lower(), provider.api_key_env_var,
                    provider.keyring_key, provider.keyring_service)
                if not key:
                    continue
                backend = create_backend(
                    provider.provider.lower(), key, provider.model)
                if backend is not None:
                    self._provider_config = provider
                    return backend, ""

        wanted = ", ".join(
            f"{p.provider} ({p.api_key_env_var or 'no env var named'})"
            for p in self._config.providers) if self._config.enabled else ""
        why = (f"no critic provider is reachable: {LOCAL_ENDPOINT_ENV} is "
               f"unset, so there is no local model to ask")
        if wanted:
            why += f", and no key resolved for {wanted}"
        else:
            why += (", and the critic config names no enabled provider "
                    "(`critic: {enabled: true}` in .judais-lobi.yml, or "
                    "~/.judais-lobi/critic.yml)")
        return None, why

    @property
    def available(self) -> bool:
        return self._backend is not None

    @property
    def provider(self) -> str:
        return getattr(self._backend, "provider_name", "") if self._backend \
            else ""

    @property
    def calls(self) -> int:
        return self._calls

    # ── the question ────────────────────────────────────────────────────

    def review(
        self,
        answer: str,
        evidence: Sequence[str],
        *,
        objective: str = "",
        unsupported: Sequence[str] = (),
        answered_with_caveat: bool = False,
        audience: str = "",
        mutation: str = "",
        carries_figures: bool = True,
    ) -> Optional[CriticOpinion]:
        """A second opinion, or ``None`` when no rule asked for one.

        ``None`` and a ``skipped`` row are different answers and are kept
        different: ``None`` means the triggers did not fire, so there is no
        row and the record looks exactly as it did before this existed;
        ``skipped`` means a rule *did* fire and nobody could answer, which
        is a fact about the deployment somebody should see.
        """
        fire, reason = should_invoke_mission_critic(
            MissionCriticContext(
                answered_with_caveat=answered_with_caveat,
                unsupported_count=len(unsupported),
                audience=audience,
                mutation=mutation,
                draft_carries_figures=carries_figures,
                critic_calls_this_session=self._calls,
            ),
            self._trigger,
        )
        if not fire:
            return None

        if self._backend is None:
            return CriticOpinion(verdict=SKIPPED, reason=reason,
                                 detail=self._why_not)

        payload = self._payload(answer, evidence, objective, unsupported)
        redactor = Redactor(level=self._config.redaction_level,
                            max_bytes=self._config.max_payload_bytes)
        redacted, _hash, _clamped, _size = redactor.redact_and_clamp(payload)

        self._calls += 1
        model = self._provider_config.model if self._provider_config else ""
        timeout = (self._provider_config.timeout_seconds
                   if self._provider_config else 60.0)
        report = self._backend.critique(
            redacted, model, self._config.max_tokens_per_call, timeout,
            MISSION_CRITIC_SYSTEM_PROMPT,
        )
        return self._opinion(report, reason)

    def _payload(self, answer: str, evidence: Sequence[str],
                 objective: str, unsupported: Sequence[str]) -> str:
        """What the critic is shown.  Bounded per result, not in total.

        Per result because the point of showing evidence at all is that
        every tool this mission called is represented: a total budget spent
        end-to-end would hand the critic the whole of the first payload and
        none of the last, and the claim it is being asked about is as
        likely to be in one as the other.
        """
        trimmed = []
        for text in evidence:
            text = str(text or "")
            if self._max_evidence_chars and len(text) > self._max_evidence_chars:
                text = text[: self._max_evidence_chars] + " …[cut]"
            trimmed.append(text)
        return json.dumps({
            "objective": objective,
            "answer": answer,
            "mechanically_unsupported": list(unsupported),
            "tool_results": trimmed,
        }, ensure_ascii=False, default=str)

    @staticmethod
    def _opinion(report, reason: str) -> CriticOpinion:
        """A provider report as a mission verdict.

        ``refused`` and ``unavailable`` become :data:`SKIPPED` rather than
        a pass, for the reason every tier here has the same rule about: a
        critic that could not be reached has found nothing and has also
        checked nothing, and those must not report alike.
        """
        provider = getattr(report, "provider", "") or ""
        verdict = getattr(report, "verdict", CriticVerdict.UNAVAILABLE)
        concerns = tuple(
            str(c) for c in (getattr(report, "logic_concerns", ()) or ()) if c)
        concerns += tuple(
            risk.description for risk in (getattr(report, "top_risks", ()) or ())
            if getattr(risk, "description", ""))

        if verdict == CriticVerdict.APPROVE:
            return CriticOpinion(
                verdict=PASS, provider=provider, reason=reason,
                detail=(f"{provider or 'the critic'} found nothing it would "
                        f"contradict in the evidence it was shown"))
        if verdict in (CriticVerdict.CAUTION, CriticVerdict.BLOCK):
            first = concerns[0] if concerns else "no reason given"
            return CriticOpinion(
                verdict=FAIL, provider=provider, reason=reason,
                concerns=concerns,
                detail=(f"{provider or 'the critic'} disputes this answer "
                        f"({verdict.value}): {first}"))
        raw = (getattr(report, "raw_response", "") or "").strip()
        return CriticOpinion(
            verdict=SKIPPED, provider=provider, reason=reason,
            detail=(f"{provider or 'the critic'} gave no usable verdict"
                    + (f": {raw[:200]}" if raw else "")))
