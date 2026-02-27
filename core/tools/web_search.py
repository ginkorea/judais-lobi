# tools/web_search.py

from core.tools.tool import Tool
from core.tools.fetch_page import FetchPageTool
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

class WebSearchTool(Tool):
    name = "perform_web_search"
    description = "Performs a web search using DuckDuckGo and returns the top results."

    def __call__(self, query, max_results=5, deep_dive=False, k_articles=3):
        headers = {"User-Agent": "Mozilla/5.0"}
        safe_query = "" if query is None else str(query)
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(safe_query)}"
        try:
            res = requests.post(url, headers=headers, timeout=15)
            res.raise_for_status()
        except requests.RequestException as exc:
            return f"Search failed: {exc}"

        soup = BeautifulSoup(res.text or "", "html.parser")
        results = []

        for a in soup.find_all("a", {"class": "result__a"}, limit=max_results):
            href = a.get("href")
            text = a.get_text()
            results.append({"title": text, "url": href})

        if not results:
            return "No results found."

        markdown_results = "\n".join([f"- [{r['title']}]({r['url']})" for r in results])

        if deep_dive and results:
            fetch = FetchPageTool()
            detailed = [
                f"### {r['title']}\nURL: {r['url']}\n\n{fetch(r['url'])}"
                for r in results[:k_articles]
            ]
            return "\n\n---\n\n".join(detailed)

        return markdown_results
