# tools/web_search.py

from __future__ import annotations

import json
from typing import Dict, List, Optional
from urllib.parse import quote_plus, urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup

from core.tools.tool import Tool
from core.tools.fetch_page import FetchPageTool

class WebSearchTool(Tool):
    name = "perform_web_search"
    description = "Performs a web search using DuckDuckGo and returns the top results."

    def __call__(
        self,
        query,
        max_results: int = 5,
        deep_dive: bool = False,
        k_articles: int = 3,
        include_snippets: bool = True,
        return_format: str = "markdown",
    ):
        headers = {"User-Agent": "Mozilla/5.0"}
        safe_query = "" if query is None else str(query)
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(safe_query)}"
        try:
            res = requests.post(url, headers=headers, timeout=15)
            res.raise_for_status()
        except requests.RequestException as exc:
            return f"Search failed: {exc}"

        soup = BeautifulSoup(res.text or "", "html.parser")
        results: List[Dict[str, str]] = []
        seen_urls: set[str] = set()

        for result in soup.select("div.result__body"):
            link = result.select_one("a.result__a")
            if not link:
                continue
            href = link.get("href") or ""
            href = self._normalize_result_url(href)
            if not href or href in seen_urls:
                continue
            title = (link.get_text() or "").strip()
            snippet = ""
            if include_snippets:
                snippet_node = (
                    result.select_one("a.result__snippet")
                    or result.select_one("div.result__snippet")
                    or result.select_one("span.result__snippet")
                )
                if snippet_node:
                    snippet = (snippet_node.get_text() or "").strip()
            results.append(
                {
                    "title": title,
                    "url": href,
                    "snippet": snippet,
                }
            )
            seen_urls.add(href)
            if len(results) >= max_results:
                break

        if not results:
            for a in soup.find_all("a", {"class": "result__a"}):
                href = a.get("href") or ""
                href = self._normalize_result_url(href)
                if not href or href in seen_urls:
                    continue
                title = (a.get_text() or "").strip()
                results.append({"title": title, "url": href, "snippet": ""})
                seen_urls.add(href)
                if len(results) >= max_results:
                    break

        if not results:
            return "No results found."

        if return_format == "json":
            payload = {
                "query": safe_query,
                "source": "duckduckgo",
                "results": results,
                "count": len(results),
            }
            return json.dumps(payload, ensure_ascii=False)

        markdown_results = "\n".join(
            [
                f"- [{r['title']}]({r['url']})"
                + (f" — {r['snippet']}" if r.get("snippet") else "")
                for r in results
            ]
        )

        if deep_dive and results:
            fetch = FetchPageTool()
            detailed = [
                f"### {r['title']}\nURL: {r['url']}\n\n{fetch(r['url'])}"
                for r in results[:k_articles]
            ]
            return "\n\n---\n\n".join(detailed)

        return markdown_results

    @staticmethod
    def _normalize_result_url(url: str) -> str:
        if not url:
            return ""
        parsed = urlparse(url)
        if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
            params = parse_qs(parsed.query)
            target = params.get("uddg", [""])[0]
            return unquote(target) if target else url
        return url
