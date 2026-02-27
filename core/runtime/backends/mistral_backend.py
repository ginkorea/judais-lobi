# core/runtime/backends/mistral_backend.py — Mistral cURL/SSE wrapper

import json
import os
import subprocess
import tempfile
from types import SimpleNamespace
from typing import Dict, List

from core.runtime.backends.base import Backend, BackendCapabilities


class MistralBackend(Backend):
    def __init__(self):
        self.api_key = os.getenv("MISTRAL_API_KEY")
        if not self.api_key:
            raise RuntimeError("Missing MISTRAL_API_KEY")

    def chat(self, model: str, messages: List[Dict], stream: bool = False):
        if not model:
            model = "codestral-latest"

        payload = {"model": model, "messages": messages, "stream": stream}

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
            "-d", f"@{tmp_path}",
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
            with subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            ) as proc:
                for line in proc.stdout:
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
                                choices=[
                                    SimpleNamespace(
                                        delta=SimpleNamespace(content=content)
                                    )
                                ]
                            )
                    except Exception:
                        continue
            os.unlink(tmp_path)

        return mistral_stream()

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            supports_streaming=True,
            supports_json_mode=True,
            supports_tool_calls=False,
            max_context_tokens=None,
            max_output_tokens=None,
        )
