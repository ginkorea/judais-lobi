# tools/fetch_page.py

from __future__ import annotations

import json
import re
from typing import Optional

import requests
from bs4 import BeautifulSoup

from core.tools.tool import Tool

class FetchPageTool(Tool):
    name = "fetch_page_content"
    description = "Fetches and extracts visible text from the given URL."

    def __call__(
        self,
        url,
        max_chars: int = 8000,
        return_format: str = "text",
    ):
        try:
            res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
            res.raise_for_status()
            soup = BeautifulSoup(res.text or "", "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            title = (soup.title.get_text() if soup.title else "").strip()
            text = " ".join(p.get_text(" ", strip=True) for p in soup.find_all("p"))
            if not text:
                body = soup.body.get_text(" ", strip=True) if soup.body else ""
                text = body
            text = re.sub(r"\s+", " ", text).strip()
            truncated = False
            if max_chars and len(text) > max_chars:
                text = text[:max_chars].rstrip()
                truncated = True
            if return_format == "json":
                payload = {
                    "url": url,
                    "title": title,
                    "text": text,
                    "truncated": truncated,
                    "char_count": len(text),
                }
                return json.dumps(payload, ensure_ascii=False)
            return text
        except requests.RequestException as exc:
            return f"Failed to fetch or parse: {exc}"
        except Exception as exc:
            return f"Failed to fetch or parse: {exc}"
