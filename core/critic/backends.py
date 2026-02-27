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
    ) -> ExternalCriticReport:
        raise NotImplementedError


class OpenAICritic(CriticBackend):
    provider_name = "openai"

    def critique(self, payload_json: str, model: str,
                 max_tokens: int, timeout: float) -> ExternalCriticReport:
        start = time.monotonic()
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key)
            result = client.chat.completions.create(
                model=model or self.default_model,
                messages=[
                    {"role": "system", "content": CRITIC_SYSTEM_PROMPT},
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
                 max_tokens: int, timeout: float) -> ExternalCriticReport:
        start = time.monotonic()
        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=self.api_key)
            message = client.messages.create(
                model=model or self.default_model,
                max_tokens=max_tokens,
                temperature=0,
                system=CRITIC_SYSTEM_PROMPT,
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
                 max_tokens: int, timeout: float) -> ExternalCriticReport:
        start = time.monotonic()
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            gen_model = genai.GenerativeModel(model or self.default_model)
            response = gen_model.generate_content(
                [CRITIC_SYSTEM_PROMPT, payload_json],
                generation_config={"max_output_tokens": max_tokens, "temperature": 0},
                request_options={"timeout": timeout},
            )
            content = getattr(response, "text", "")
            elapsed = time.monotonic() - start
            return _parse_critic_response(content, self.provider_name,
                                          model or self.default_model, elapsed)
        except Exception as exc:
            return _unavailable_report(self.provider_name, model, exc, start)


BACKEND_REGISTRY = {
    "openai": OpenAICritic,
    "anthropic": AnthropicCritic,
    "google": GoogleCritic,
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
