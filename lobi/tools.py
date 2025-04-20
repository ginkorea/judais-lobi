# tools.py

import requests
from bs4 import BeautifulSoup

def perform_web_search(query, max_results=5):
    """
    Perform a DuckDuckGo search and return the top results as markdown list.
    """
    headers = {"User-Agent": "Mozilla/5.0"}
    url = f"https://html.duckduckgo.com/html/?q={query}"
    res = requests.post(url, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")
    results = []

    for a in soup.find_all("a", {"class": "result__a"}, limit=max_results):
        href = a.get("href")
        text = a.get_text()
        results.append(f"- [{text}]({href})")

    return "\n".join(results)
