from __future__ import annotations

import json
import time
from typing import Any, Dict, List

from core.tools.tool import Tool
from core.tools.web_search import WebSearchTool
from core.tools.fetch_page import FetchPageTool


class WebResearchTool(Tool):
    name = "perform_web_research"
    description = "Searches the web and fetches top pages into a structured research pack."

    def __call__(
        self,
        query,
        max_results: int = 5,
        max_pages: int = 3,
        max_chars_per_page: int = 8000,
        include_full_text: bool = False,
        sleep_seconds: float = 0.0,
        return_format: str = "json",
    ):
        safe_query = "" if query is None else str(query)
        search_tool = WebSearchTool()
        raw = search_tool(
            safe_query,
            max_results=max_results,
            include_snippets=True,
            return_format="json",
        )
        try:
            search_payload = json.loads(raw)
        except Exception:
            return raw

        results = search_payload.get("results", [])
        if not results:
            return "No results found."

        fetch_tool = FetchPageTool()
        sources: List[Dict[str, Any]] = []
        for result in results[: max_pages]:
            url = result.get("url") or ""
            if not url:
                continue
            page_raw = fetch_tool(url, max_chars=max_chars_per_page, return_format="json")
            try:
                page = json.loads(page_raw)
            except Exception:
                page = {
                    "url": url,
                    "title": result.get("title") or "",
                    "text": page_raw,
                    "truncated": False,
                    "char_count": len(page_raw or ""),
                }
            if not include_full_text:
                page.pop("text", None)
            sources.append(
                {
                    "title": result.get("title") or page.get("title", ""),
                    "url": url,
                    "snippet": result.get("snippet", ""),
                    "page": page,
                }
            )
            if sleep_seconds:
                time.sleep(sleep_seconds)

        payload = {
            "query": safe_query,
            "source": search_payload.get("source", "duckduckgo"),
            "results": results,
            "sources": sources,
            "counts": {
                "results": len(results),
                "sources": len(sources),
            },
        }

        if return_format == "json":
            return json.dumps(payload, ensure_ascii=False)
        return payload
