import os
import json
import subprocess
import tempfile
from types import SimpleNamespace
from typing import List, Dict, Any, Optional
from openai import OpenAI


class UnifiedClient:
    """
    Unified client:
      - OpenAI → uses OpenAI SDK
      - Mistral → uses cURL for reliability and proper SSE streaming
    """

    def __init__(self, provider_override: Optional[str] = None):
        self.provider = (provider_override or os.getenv("ELF_PROVIDER") or "openai").lower()

        if self.provider == "openai":
            key = os.getenv("OPENAI_API_KEY")
            if not key:
                raise RuntimeError("Missing OPENAI_API_KEY")
            self.client = OpenAI(api_key=key)

        elif self.provider == "mistral":
            self.api_key = os.getenv("MISTRAL_API_KEY")
            if not self.api_key:
                raise RuntimeError("Missing MISTRAL_API_KEY")

        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

    # ------------------------------------------------------------
    # Public unified interface
    # ------------------------------------------------------------
    def chat(self, model: str, messages: List[Dict[str, Any]], stream: bool = False):
        if self.provider == "openai":
            return self._chat_openai(model, messages, stream)
        elif self.provider == "mistral":
            return self._chat_mistral(model, messages, stream)

    # ------------------------------------------------------------
    # OpenAI SDK
    # ------------------------------------------------------------
    def _chat_openai(self, model: str, messages: List[Dict[str, Any]], stream: bool):
        if stream:
            return self.client.chat.completions.create(model=model, messages=messages, stream=True)
        result = self.client.chat.completions.create(model=model, messages=messages)
        return result.choices[0].message.content

    # ------------------------------------------------------------
    # Mistral via cURL
    # ------------------------------------------------------------
    def _chat_mistral(self, model: str, messages: List[Dict[str, Any]], stream: bool):
        if not model:
            model = "codestral-latest"

        payload = {"model": model, "messages": messages, "stream": stream}

        # --- Use a temporary JSON file for -d @file syntax ---
        with tempfile.NamedTemporaryFile("w+", delete=False) as tmp:
            json.dump(payload, tmp)
            tmp.flush()
            tmp_path = tmp.name

        cmd = [
            "curl",
            "-s",
            "https://api.mistral.ai/v1/chat/completions",
            "-H", f"Authorization: Bearer {self.api_key}",
            "-H", "Content-Type: application/json",
            "-d", f"@{tmp_path}"
        ]

        if not stream:
            res = subprocess.run(cmd, capture_output=True, text=True)
            os.unlink(tmp_path)
            try:
                parsed = json.loads(res.stdout)
                return parsed["choices"][0]["message"]["content"]
            except Exception:
                return res.stdout.strip()

        # --- Streaming mode ---
        def mistral_stream():
            with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as proc:
                for line in proc.stdout:
                    # print(line)
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[len("data: "):]
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        content = obj["choices"][0]["delta"].get("content")
                        if content:
                            yield SimpleNamespace(
                                choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
                            )
                    except Exception:
                        continue
            os.unlink(tmp_path)

        return mistral_stream()
