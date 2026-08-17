# core/critic/backends.py — Critic backend interfaces + provider adapters

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from core.critic.models import CriticRisk, CriticVerdict, ExternalCriticReport


CRITIC_SYSTEM_PROMPT = """You are an external logic auditor for code changes.
Return a single JSON object with the following keys:
verdict (approve|caution|block|refused), top_risks (list), missing_tests (list),
logic_concerns (list), suggested_plan_adjustments (list),
suggested_patch_adjustments (list), questions_for_builder (list), confidence (0-1).
Be concise, actionable, and grounded in the provided artifacts.
"""


class CriticBackend(ABC):
    provider_name: str = ""

    def __init__(self, api_key: str, default_model: str = ""):
        self.api_key = api_key
        self.default_model = default_model

    @abstractmethod
    def critique(
        self,
        payload_json: str,
        model: str,
        max_tokens: int,
        timeout: float,
        system: str = CRITIC_SYSTEM_PROMPT,
    ) -> ExternalCriticReport:
        """One critique of *payload_json*, as this provider answers it.

        *system* is the job, and it is a parameter because there are two
        of them.  :data:`CRITIC_SYSTEM_PROMPT` audits a code change and
        asks for missing tests and patch adjustments; a mission answer has
        no patch and no tests, and a critic told to look for them looks for
        them.  The default keeps every existing caller — the kernel
        orchestrator — sending exactly what it sent before.
        """
        raise NotImplementedError


class OpenAICritic(CriticBackend):
    provider_name = "openai"

    def critique(self, payload_json: str, model: str,
                 max_tokens: int, timeout: float,
                 system: str = CRITIC_SYSTEM_PROMPT) -> ExternalCriticReport:
        start = time.monotonic()
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key)
            result = client.chat.completions.create(
                model=model or self.default_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": payload_json},
                ],
                response_format={"type": "json_object"},
                max_tokens=max_tokens,
                timeout=timeout,
            )
            content = result.choices[0].message.content
            elapsed = time.monotonic() - start
            return _parse_critic_response(content, self.provider_name,
                                          model or self.default_model, elapsed)
        except Exception as exc:
            return _unavailable_report(self.provider_name, model, exc, start)


class AnthropicCritic(CriticBackend):
    provider_name = "anthropic"

    def critique(self, payload_json: str, model: str,
                 max_tokens: int, timeout: float,
                 system: str = CRITIC_SYSTEM_PROMPT) -> ExternalCriticReport:
        start = time.monotonic()
        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=self.api_key)
            message = client.messages.create(
                model=model or self.default_model,
                max_tokens=max_tokens,
                temperature=0,
                system=system,
                messages=[{"role": "user", "content": payload_json}],
                timeout=timeout,
            )
            content = _extract_anthropic_text(message)
            elapsed = time.monotonic() - start
            return _parse_critic_response(content, self.provider_name,
                                          model or self.default_model, elapsed)
        except Exception as exc:
            return _unavailable_report(self.provider_name, model, exc, start)


class GoogleCritic(CriticBackend):
    provider_name = "google"

    def critique(self, payload_json: str, model: str,
                 max_tokens: int, timeout: float,
                 system: str = CRITIC_SYSTEM_PROMPT) -> ExternalCriticReport:
        start = time.monotonic()
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            gen_model = genai.GenerativeModel(model or self.default_model)
            response = gen_model.generate_content(
                [system, payload_json],
                generation_config={"max_output_tokens": max_tokens, "temperature": 0},
                request_options={"timeout": timeout},
            )
            content = getattr(response, "text", "")
            elapsed = time.monotonic() - start
            return _parse_critic_response(content, self.provider_name,
                                          model or self.default_model, elapsed)
        except Exception as exc:
            return _unavailable_report(self.provider_name, model, exc, start)


class LocalCritic(CriticBackend):
    """The critic a deployment with no frontier key still has.

    The reference deployment's ask, and :mod:`core.critic.triggers` had
    already written down why it is the *default* rather than the fallback:
    the local plane is "the ONLY tier guaranteed to exist", and a control
    that quietly does not exist for half the users is worse than none.  It
    is also the only one that sends nothing off the box — a governed draft
    carries actor names and scores, and shipping it to a hosted model is a
    handling decision, not a config default.

    Same weights, different job.  What makes it a second opinion and not
    the generator agreeing with itself is the system prompt: the caller
    passes an adversarial one (see
    :data:`core.critic.mission.MISSION_CRITIC_SYSTEM_PROMPT`), and the
    two-step ordering the reading tier measured — commit to a reading
    before being shown the claim — is the same lesson one level up.

    **Not a second HTTP client.**  ``LocalBackend`` already speaks
    ``POST {LOCAL_API_BASE}/chat/completions``, already repairs a base URL
    missing its ``/v1``, already strips harmony control tokens a served
    gpt-oss would 500 on, and already reports what model is loaded.  A
    ``requests.post`` here would be a second owner of all of it.
    """

    provider_name = "local"

    def __init__(self, api_key: str = "", default_model: str = "",
                 endpoint: str = "", backend: Any = None):
        super().__init__(api_key=api_key, default_model=default_model)
        self._endpoint = endpoint
        self._backend = backend

    @property
    def backend(self):
        """The shared local client, built on first use.

        Lazily, because constructing one reads the environment and a
        registry lookup must not depend on a server being configured.
        """
        if self._backend is None:
            from core.runtime.backends.local_backend import LocalBackend

            self._backend = LocalBackend(
                endpoint=self._endpoint or None,
                model=self.default_model or None,
                api_key=self.api_key or None,
                # It is being asked one question in prose and must answer
                # in JSON. A function namespace declared here is how a
                # harmony model answers a yes/no question with a tool call
                # — the same reason `plain_chat_fn` declares none.
                supports_tool_calls=False,
            )
        return self._backend

    def critique(self, payload_json: str, model: str,
                 max_tokens: int, timeout: float,
                 system: str = CRITIC_SYSTEM_PROMPT) -> ExternalCriticReport:
        """One call, no ``response_format``, and the parse does the rest.

        Structured decoding is deliberately not requested.  vLLM supports
        it and llama.cpp's server and Ollama's shim variously do not, and a
        400 from asking would turn "the local critic had no opinion" into
        "the local critic is broken" on exactly the deployments this exists
        for.  :func:`_try_parse_json` already recovers an object from a
        fenced block or from the first ``{`` to the last ``}``, which is
        what a chatty local model produces.

        *timeout* is accepted and not forwarded: ``LocalBackend`` holds one
        (``CHAT_TIMEOUT``, long on purpose — a cold vLLM loads weights for
        ~100s before the first reply) and a second, shorter one here would
        make a first call fail for a reason nobody could see.
        """
        start = time.monotonic()
        try:
            reply = self.backend.chat(
                model=model or self.default_model or "",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": payload_json},
                ],
                stream=False,
                max_tokens=max_tokens,
                temperature=0,
            )
            elapsed = time.monotonic() - start
            return _parse_critic_response(
                reply, self.provider_name,
                model or self.default_model or "", elapsed)
        except Exception as exc:
            return _unavailable_report(self.provider_name, model, exc, start)


BACKEND_REGISTRY = {
    "openai": OpenAICritic,
    "anthropic": AnthropicCritic,
    "google": GoogleCritic,
    "local": LocalCritic,
}


def create_backend(provider: str, api_key: str,
                   default_model: str) -> Optional[CriticBackend]:
    cls = BACKEND_REGISTRY.get(provider)
    if cls is None:
        return None
    return cls(api_key=api_key, default_model=default_model)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_critic_response(raw: Any, provider: str,
                           model: str, elapsed: float) -> ExternalCriticReport:
    if isinstance(raw, str):
        raw_text = raw
    else:
        try:
            raw_text = json.dumps(raw)
        except Exception:
            raw_text = str(raw)
    data = None

    if isinstance(raw, dict):
        data = raw
    else:
        data = _try_parse_json(raw_text)

    if not isinstance(data, dict):
        return ExternalCriticReport(
            provider=provider,
            model=model,
            verdict=CriticVerdict.UNAVAILABLE,
            raw_response=raw_text,
            response_time_seconds=elapsed,
            timestamp=datetime.now(timezone.utc),
        )

    verdict_raw = str(data.get("verdict", "unavailable")).lower()
    try:
        verdict = CriticVerdict(verdict_raw)
    except Exception:
        verdict = CriticVerdict.UNAVAILABLE

    report = ExternalCriticReport(
        provider=provider,
        model=model,
        verdict=verdict,
        top_risks=_parse_risks(data.get("top_risks", [])),
        missing_tests=list(data.get("missing_tests", []) or []),
        logic_concerns=list(data.get("logic_concerns", []) or []),
        suggested_plan_adjustments=list(
            data.get("suggested_plan_adjustments", []) or []
        ),
        suggested_patch_adjustments=list(
            data.get("suggested_patch_adjustments", []) or []
        ),
        questions_for_builder=list(data.get("questions_for_builder", []) or []),
        confidence=float(data.get("confidence", 0.0) or 0.0),
        raw_response=raw_text,
        response_time_seconds=elapsed,
        timestamp=datetime.now(timezone.utc),
    )
    return report


def _parse_risks(raw) -> list:
    risks = []
    if not raw:
        return risks
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                try:
                    risks.append(CriticRisk.model_validate(item))
                except Exception:
                    desc = item.get("description", "") if isinstance(item, dict) else str(item)
                    risks.append(CriticRisk(description=desc))
            else:
                risks.append(CriticRisk(description=str(item)))
    elif isinstance(raw, dict):
        try:
            risks.append(CriticRisk.model_validate(raw))
        except Exception:
            risks.append(CriticRisk(description=str(raw)))
    else:
        risks.append(CriticRisk(description=str(raw)))
    return risks


def _try_parse_json(text: str) -> Optional[dict]:
    try:
        return json.loads(text)
    except Exception:
        pass

    # Try to extract a JSON code block
    block = _extract_code_block(text)
    if block:
        try:
            return json.loads(block)
        except Exception:
            return None

    # Fallback: take substring between first { and last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            return None
    return None


def _extract_code_block(text: str) -> Optional[str]:
    fence = "```"
    if fence not in text:
        return None
    parts = text.split(fence)
    for i in range(1, len(parts), 2):
        block = parts[i].strip()
        if block.startswith("json"):
            block = block[4:].strip()
        if block.startswith("{") and block.endswith("}"):
            return block
    return None


def _extract_anthropic_text(message) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, list) and content:
        first = content[0]
        text = getattr(first, "text", None)
        if text is not None:
            return text
    if isinstance(content, str):
        return content
    return ""


def _unavailable_report(provider: str, model: str,
                         exc: Exception, start: float) -> ExternalCriticReport:
    elapsed = time.monotonic() - start
    return ExternalCriticReport(
        provider=provider,
        model=model,
        verdict=CriticVerdict.UNAVAILABLE,
        raw_response=f"{type(exc).__name__}: {exc}",
        response_time_seconds=elapsed,
        timestamp=datetime.now(timezone.utc),
    )
