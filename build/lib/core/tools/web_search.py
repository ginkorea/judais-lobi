# tools/web_search.py

from core.tools.tool import Tool
from core.tools.fetch_page import FetchPageTool
import requests
from bs4 import BeautifulSoup

class WebSearchTool(Tool):
    name = "perform_web_search"
    description = "Performs a web search using DuckDuckGo and returns the top results."

    def __call__(self, query, max_results=5, deep_dive=False, k_articles=3):
        headers = {"User-Agent": "Mozilla/5.0"}
        url = f"https://html.duckduckgo.com/html/?q={query}"
        res = requests.post(url, headers=headers)
        soup = BeautifulSoup(res.text, "html.parser")
        results = []

        for a in soup.find_all("a", {"class": "result__a"}, limit=max_results):
            href = a.get("href")
            text = a.get_text()
            results.append({"title": text, "url": href})

        markdown_results = "\n".join([f"- [{r['title']}]({r['url']})" for r in results])

        if deep_dive and results:
            fetch = FetchPageTool()
            detailed = [
                f"### {r['title']}\nURL: {r['url']}\n\n{fetch(r['url'])}"
                for r in results[:k_articles]
            ]
            return "\n\n---\n\n".join(detailed)

        return markdown_results
