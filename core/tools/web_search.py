# core/tools/web_search.py — asking a search engine, from a framework that has none

"""``perform_web_search``: a query in, ranked ``(title, url, snippet)`` out.

**A search engine is somebody else's service, and this framework does not
have one.**  That sentence is the whole design.  The old tool scraped
DuckDuckGo's HTML endpoint and, when the scrape came back empty — which
it does, on a schedule nobody controls, for a shape of markup nobody
promised — returned the string ``"No results found."``  An agent cannot
tell that apart from *"the web contains nothing about this"*, and the two
readings lead to opposite answers.

So there are **providers**, chosen by name:

* ``duckduckgo`` — the HTML endpoint scrape, kept because it needs no
  key and it is what shipped.  It is best-effort and says so: a scrape
  that finds no result rows raises :class:`SearchUnavailable` naming the
  provider, rather than reporting an empty web;
* ``searxng`` — a SearXNG instance's JSON API, at ``SEARXNG_URL``.
  Keyless, self-hostable, and the recommendation for anyone who wants
  search to be *reliable*: point it at your own instance and the answer
  stops depending on a scrape;
* anything a platform registers.  :func:`register_provider` is the hook,
  and a provider is one function — ``(query, max_results, timeout) ->
  [{"title", "url", "snippet"}]`` — which is small enough that a keyed
  commercial API is twenty lines in a platform's own repository.
  Nothing keyed ships here: a framework that hard-coded one vendor's
  endpoint would be a framework with an opinion about whose search you
  buy.

**Research does not require this tool.**  The ``research`` pack marks it
optional (``perform_web_search?``) for exactly this reason.  Reading
given URLs and following the links on them is research; a search engine
only changes where the first URL comes from.  When no provider can
answer, the refusal says so **by name** and names the environment
variable that would fix it, and the mission goes on with the URLs it
was given.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional, Sequence
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests
from bs4 import BeautifulSoup

from core.tools.fetch_page import (USER_AGENT, default_timeout, host_allowed,
                                   read_page)
from core.tools.tool import Tool

#: Which provider answers a search.  Unset means :data:`DEFAULT_PROVIDER`.
PROVIDER_ENV = "SEARCH_PROVIDER"

#: The base URL of a SearXNG instance, for the ``searxng`` provider.  With
#: the provider selected and this unset, the tool refuses by name rather
#: than guessing at a public instance somebody else pays for.
SEARXNG_URL_ENV = "SEARXNG_URL"

#: What answers when nobody chose.  DuckDuckGo's HTML endpoint, because it
#: is keyless and because it is what this tool did before providers
#: existed — changing the default would have taken a capability away from
#: every existing caller to make a point.
DEFAULT_PROVIDER = "duckduckgo"

#: One search result, as every provider must shape it.
RESULT_FIELDS = ("title", "url", "snippet")


class SearchUnavailable(RuntimeError):
    """No provider could answer, and the message says which and why.

    Distinct from *"the web has nothing about this"* on purpose: that is
    an empty result list from a provider that worked, and it is a finding.
    This is the tool telling the mission that it did not look.
    """


def _duckduckgo(query: str, max_results: int, timeout: float) -> List[Dict[str, str]]:
    """The HTML endpoint, scraped.  Keyless, unofficial, and best-effort."""
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    # The allow-list is checked HERE and not only in the page fetcher.
    # An operator who narrowed the reachable web to one host and still had
    # a search engine reaching out over the internet would have a hole in
    # the shape of this tool, and a mission graded on a restricted plane
    # would be quietly asking a live index questions about it.
    if not host_allowed(url):
        raise SearchUnavailable(
            "the `duckduckgo` provider reaches html.duckduckgo.com, which "
            "is outside the allow-list this run was given. Search is not "
            "available in this session; that is an operator's decision and "
            "not an empty web.")
    try:
        response = requests.post(url, headers={"User-Agent": USER_AGENT},
                                 timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SearchUnavailable(
            f"the `duckduckgo` provider could not be reached: {exc}") from exc

    soup = BeautifulSoup(response.text or "", "html.parser")
    results: List[Dict[str, str]] = []
    seen: set = set()
    for row in soup.select("div.result__body") or soup.select("div.result"):
        link = row.select_one("a.result__a")
        if link is None:
            continue
        href = _unwrap(str(link.get("href") or ""))
        if not href or href in seen:
            continue
        snippet = row.select_one(
            "a.result__snippet") or row.select_one("div.result__snippet")
        results.append({
            "title": " ".join((link.get_text() or "").split()),
            "url": href,
            "snippet": " ".join((snippet.get_text() or "").split())
                       if snippet else "",
        })
        seen.add(href)
        if len(results) >= max_results:
            break

    if not results:
        raise SearchUnavailable(
            "the `duckduckgo` provider returned no result rows. That is a "
            "scrape of an endpoint nobody promised, so it means the scrape "
            f"failed and NOT that the web is empty. Set {PROVIDER_ENV}="
            f"searxng with {SEARXNG_URL_ENV} pointing at an instance for a "
            "provider with an API, or work from URLs you already have.")
    return results


def _searxng(query: str, max_results: int, timeout: float) -> List[Dict[str, str]]:
    """A SearXNG instance's JSON API.  Keyless, and somebody's own."""
    base = (os.getenv(SEARXNG_URL_ENV, "") or "").strip().rstrip("/")
    if not base:
        raise SearchUnavailable(
            f"{PROVIDER_ENV}=searxng needs {SEARXNG_URL_ENV} to name an "
            f"instance; this framework ships no default one because a "
            f"default would be somebody else's bandwidth.")
    if not host_allowed(base):
        raise SearchUnavailable(
            f"{SEARXNG_URL_ENV} points at a host outside the allow-list.")
    try:
        response = requests.get(
            f"{base}/search",
            params={"q": query, "format": "json"},
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise SearchUnavailable(
            f"the `searxng` provider at {base} could not answer: {exc}") from exc

    results = []
    for item in (payload.get("results") or [])[:max_results]:
        url = str(item.get("url") or "")
        if not url:
            continue
        results.append({
            "title": str(item.get("title") or ""),
            "url": url,
            "snippet": " ".join(str(item.get("content") or "").split()),
        })
    return results


#: name -> ``(query, max_results, timeout) -> [{title, url, snippet}]``.
PROVIDERS: Dict[str, Callable[[str, int, float], List[Dict[str, str]]]] = {
    "duckduckgo": _duckduckgo,
    "searxng": _searxng,
}


def register_provider(
        name: str,
        provider: Callable[[str, int, float], List[Dict[str, str]]]) -> None:
    """Add a search backend under *name*.  THE HOOK.

    A platform with a keyed API — Brave, Tavily, an internal index —
    writes the function in its own repository and calls this at import
    time, then runs with ``SEARCH_PROVIDER=<name>``.  The contract is the
    signature and the three fields of :data:`RESULT_FIELDS`; anything
    else the provider knows stays in the provider.

    A provider that cannot answer must raise :class:`SearchUnavailable`
    with a message naming itself.  Returning ``[]`` means *the index
    holds nothing for this query*, which is a finding a mission may
    report, and the two must not be confused.
    """
    if not name or not callable(provider):
        raise ValueError("register_provider(name, callable)")
    PROVIDERS[str(name).strip().lower()] = provider


def selected_provider() -> str:
    return (os.getenv(PROVIDER_ENV, "") or DEFAULT_PROVIDER).strip().lower()


def search(query: str, *, max_results: int = 5,
           provider: str = "", timeout: Optional[float] = None
           ) -> Dict[str, Any]:
    """Run one search through the selected provider.

    Returns ``{query, provider, results, count, error, message}``.  A
    provider that raised leaves ``error`` set and ``results`` empty, and
    the two are never confused with a provider that answered nothing.
    """
    name = (provider or selected_provider()).strip().lower()
    query = str(query or "").strip()
    payload: Dict[str, Any] = {
        "query": query, "provider": name, "results": [], "count": 0,
        "error": "", "message": "",
    }
    if not query:
        payload["error"] = "no_query"
        payload["message"] = "No query given."
        return payload
    if name not in PROVIDERS:
        payload["error"] = "unknown_provider"
        payload["message"] = (
            f"{PROVIDER_ENV}={name!r} names no provider. This build has "
            f"{sorted(PROVIDERS)}; a platform adds its own with "
            f"core.tools.web_search.register_provider().")
        return payload
    try:
        found = PROVIDERS[name](query, max(1, int(max_results)),
                                timeout if timeout is not None
                                else default_timeout())
    except SearchUnavailable as exc:
        payload["error"] = "provider_unavailable"
        payload["message"] = str(exc)
        return payload
    except Exception as exc:                     # a provider is third-party
        payload["error"] = "provider_failed"
        payload["message"] = f"the {name!r} provider raised {type(exc).__name__}: {exc}"
        return payload

    results = [
        {field: str(item.get(field, "") or "") for field in RESULT_FIELDS}
        for item in (found or [])
    ]
    payload["results"] = results
    payload["count"] = len(results)
    return payload


def render(payload: Dict[str, Any]) -> str:
    """Search results as the prose a model reads."""
    if payload.get("error"):
        return (f"SEARCH UNAVAILABLE (provider: {payload.get('provider')})\n"
                f"error: {payload['error']}\n{payload.get('message', '')}\n"
                f"This is the search engine failing, NOT an empty web. Do "
                f"not state that nothing was found.")
    if not payload.get("results"):
        return (f"The {payload.get('provider')} provider answered and "
                f"returned no results for {payload.get('query')!r}.")
    lines = [f"{payload['count']} result(s) from {payload['provider']} for "
             f"{payload['query']!r}:"]
    for index, item in enumerate(payload["results"], 1):
        lines.append(f"[{index}] {item['title']}\n    {item['url']}"
                     + (f"\n    {item['snippet']}" if item["snippet"] else ""))
    return "\n".join(lines)


class WebSearchTool(Tool):
    """``perform_web_search`` — ranked URLs from whichever provider is set."""

    name = "perform_web_search"
    description = (
        "Searches the web through the configured provider (SEARCH_PROVIDER) "
        "and returns ranked title/url/snippet results. A provider that "
        "cannot answer refuses by name; that is not an empty web.")


    def __call__(self, query: Any = "", max_results: int = 5,
                 deep_dive: bool = False, k_articles: int = 3,
                 provider: str = "", timeout: Optional[float] = None,
                 **_ignored: Any):
        payload = search(str(query or ""), max_results=int(max_results or 5),
                         provider=provider, timeout=timeout)
        if deep_dive and payload["results"]:
            payload["pages"] = [
                read_page(item["url"], timeout=timeout)
                for item in payload["results"][:max(1, int(k_articles or 1))]
            ]
        evidence = json.dumps(payload, ensure_ascii=False)
        text = render(payload)
        if payload["error"]:
            return (1, "", text, evidence)
        return (0, text, "", evidence)


def _unwrap(url: str) -> str:
    """DuckDuckGo wraps a result in ``/l/?uddg=…``; the target is the result."""
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    if "duckduckgo.com" in (parsed.netloc or "") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        return unquote(target) if target else url
    return url


def result_urls(payload: Dict[str, Any]) -> Sequence[str]:
    """Just the URLs, for a caller about to fetch them."""
    return [item["url"] for item in (payload.get("results") or [])
            if item.get("url")]
