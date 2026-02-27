from __future__ import annotations

import json
import time
from typing import Any, Dict, List

from core.tools.tool import Tool
from core.tools.web_search import WebSearchTool
from core.tools.fetch_page import FetchPageTool
from core.tools.research_sources import get_academic_sources


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
        include_abstracts: bool = True,
        mode: str = "web",
        sources: List[str] | None = None,
        sleep_seconds: float = 0.0,
        return_format: str = "json",
    ):
        safe_query = "" if query is None else str(query)
        if mode == "academic":
            payload = self._academic_research(
                safe_query,
                max_results=max_results,
                include_abstracts=include_abstracts,
                sources=sources,
            )
        else:
            payload = self._web_research(
                safe_query,
                max_results=max_results,
                max_pages=max_pages,
                max_chars_per_page=max_chars_per_page,
                include_full_text=include_full_text,
                sleep_seconds=sleep_seconds,
            )

        if return_format == "json":
            return json.dumps(payload, ensure_ascii=False)
        return payload

    def _web_research(
        self,
        query: str,
        *,
        max_results: int,
        max_pages: int,
        max_chars_per_page: int,
        include_full_text: bool,
        sleep_seconds: float,
    ) -> Dict[str, Any]:
        search_tool = WebSearchTool()
        raw = search_tool(
            query,
            max_results=max_results,
            include_snippets=True,
            return_format="json",
        )
        try:
            search_payload = json.loads(raw)
        except Exception:
            return {
                "query": query,
                "source": "duckduckgo",
                "results": [],
                "sources": [],
                "counts": {"results": 0, "sources": 0},
                "error": "search_parse_failed",
            }

        results = search_payload.get("results", [])
        if not results:
            return {
                "query": query,
                "source": search_payload.get("source", "duckduckgo"),
                "results": [],
                "sources": [],
                "counts": {"results": 0, "sources": 0},
            }

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

        return {
            "query": query,
            "source": search_payload.get("source", "duckduckgo"),
            "results": results,
            "sources": sources,
            "counts": {
                "results": len(results),
                "sources": len(sources),
            },
        }

    def _academic_research(
        self,
        query: str,
        *,
        max_results: int,
        include_abstracts: bool,
        sources: List[str] | None,
    ) -> Dict[str, Any]:
        registry = get_academic_sources()
        selected = sources or list(registry.keys())
        seen: set[str] = set()
        results: List[Dict[str, Any]] = []

        for name in selected:
            source = registry.get(name)
            if source is None:
                continue
            for item in source.search(query, max_results=max_results):
                key = item.get("doi") or item.get("url") or item.get("title")
                if not key or key in seen:
                    continue
                if not include_abstracts:
                    item = dict(item)
                    item["abstract"] = ""
                results.append(item)
                seen.add(key)

        results = results[:max_results]
        return {
            "query": query,
            "source": "academic",
            "results": results,
            "sources": results,
            "counts": {
                "results": len(results),
                "sources": len(results),
            },
        }
