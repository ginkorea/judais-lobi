# core/tools/web_research.py — several pages, read once, into one citable pack

"""``perform_web_research``: a research pack — the sources, kept whole.

One tool call that fetches several pages and returns them as one typed
payload, so the mission's result store holds a set of sources under a
single handle and the model can ask for ``sources[1].sections[3].text``.

**The change that makes it work without a search engine.**  This tool
used to take a query, hand it to :mod:`core.tools.web_search`, and fetch
the top hits.  With no provider configured that is a tool that can do
nothing at all — and searching is the *one* part of research that needs
somebody else's service.  So it now takes ``urls`` as well, and the two
are independent:

* ``urls=[…]`` — read these.  Needs nothing configured beyond
  ``--profile research``, and it is the path the ``research`` pack's
  missions take: a person gives an address, or a page names one;
* ``query="…"`` — ask the configured provider what to read, then read
  it.  When the provider refuses, the pack comes back with
  ``search.error`` set and the reason in it, and **no invented sources**;
* ``follow_links=n`` — after the given pages, follow up to *n* links
  found on them, so "the figure is on the page this one links to" is one
  call.  Off by default: following links a model did not choose is how a
  bounded research task becomes a crawl.
* ``mode="academic"`` — the arXiv / Semantic Scholar / OpenAlex path in
  :mod:`core.tools.research_sources`, which is keyless and *is* a search
  engine, for the literature question that would otherwise need one.

**Every failure is a source too.**  A page that 404s or was refused by
the allow-list appears in ``failed`` with its URL and the reason.  A pack
that silently omitted it would let a mission answer "I read all three"
with two.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Sequence

from core.tools.fetch_page import read_page
from core.tools.research_sources import get_academic_sources
from core.tools.tool import Tool
from core.tools.web_search import search as run_search

#: How many pages one call will read unless told otherwise.  A ceiling on
#: a research pack is a ceiling on the context it costs and on the load it
#: puts on somebody else's server.
DEFAULT_MAX_PAGES = 3


def _pack(query: str) -> Dict[str, Any]:
    return {
        "query": query,
        "search": {},
        "sources": [],
        "failed": [],
        "counts": {"sources": 0, "failed": 0},
        "error": "",
        "message": "",
    }


def _add(pack: Dict[str, Any], page: Dict[str, Any]) -> None:
    if page.get("error"):
        pack["failed"].append({
            "url": page.get("final_url") or page.get("url", ""),
            "status": page.get("status", 0),
            "error": page["error"],
            "message": page.get("message", ""),
        })
    else:
        pack["sources"].append(page)
    pack["counts"] = {"sources": len(pack["sources"]),
                      "failed": len(pack["failed"])}


def research(
    query: str = "",
    urls: Optional[Sequence[str]] = None,
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_results: int = 5,
    follow_links: int = 0,
    max_chars_per_page: int = 0,
    sleep_seconds: float = 0.0,
    timeout: Optional[float] = None,
    session: Any = None,
) -> Dict[str, Any]:
    """Fetch a set of pages and return them as one pack.  See the module doc."""
    pack = _pack(str(query or ""))
    wanted: List[str] = [str(u).strip() for u in (urls or []) if str(u).strip()]

    if not wanted and pack["query"]:
        found = run_search(pack["query"], max_results=max_results,
                           timeout=timeout)
        pack["search"] = found
        if found.get("error"):
            pack["error"] = found["error"]
            pack["message"] = found["message"]
            return pack
        wanted = [item["url"] for item in found["results"] if item.get("url")]

    if not wanted:
        pack["error"] = "nothing_to_read"
        pack["message"] = (
            "No `urls` were given and no query produced any. This tool reads "
            "pages; it does not know of any on its own.")
        return pack

    seen: set = set()
    for url in wanted[:max(1, int(max_pages))]:
        if url in seen:
            continue
        seen.add(url)
        _add(pack, read_page(url, timeout=timeout, session=session,
                             max_chars=int(max_chars_per_page or 0)))
        if sleep_seconds:
            time.sleep(sleep_seconds)

    remaining = int(follow_links or 0)
    if remaining > 0:
        for candidate in _links_of(pack["sources"]):
            if remaining <= 0:
                break
            if candidate in seen:
                continue
            seen.add(candidate)
            remaining -= 1
            _add(pack, read_page(candidate, timeout=timeout, session=session,
                                 max_chars=int(max_chars_per_page or 0)))
            if sleep_seconds:
                time.sleep(sleep_seconds)

    return pack


def _links_of(sources: Sequence[Dict[str, Any]]) -> List[str]:
    """Every link on the pages already read, in the order they appeared."""
    out: List[str] = []
    for page in sources:
        for link in page.get("links") or []:
            url = link.get("url") or ""
            if url and url not in out:
                out.append(url)
    return out


def academic(query: str, *, max_results: int = 5,
             include_abstracts: bool = True,
             sources: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """The keyless literature search: arXiv, Semantic Scholar, OpenAlex."""
    registry = get_academic_sources()
    selected = list(sources or registry.keys())
    seen: set = set()
    results: List[Dict[str, Any]] = []
    reached: List[str] = []

    for name in selected:
        source = registry.get(name)
        if source is None:
            continue
        found = source.search(query, max_results=max_results)
        if found:
            reached.append(name)
        for item in found:
            key = item.get("doi") or item.get("url") or item.get("title")
            if not key or key in seen:
                continue
            if not include_abstracts:
                item = dict(item)
                item["abstract"] = ""
            results.append(item)
            seen.add(key)

    pack = _pack(query)
    pack["search"] = {"provider": "academic", "sources_reached": reached,
                      "count": len(results)}
    pack["sources"] = results[:max_results]
    pack["counts"] = {"sources": len(pack["sources"]), "failed": 0}
    if not results:
        pack["error"] = "no_results"
        pack["message"] = (
            f"None of {selected} returned a record for {query!r}. That may "
            f"be an empty literature or an unreachable API; it is not a "
            f"finding about the field.")
    return pack


def render(pack: Dict[str, Any]) -> str:
    """The pack as prose, labelled so every claim can be traced to a URL."""
    from core.tools.fetch_page import render as render_page

    if pack.get("error") and not pack.get("sources"):
        return (f"RESEARCH FAILED for {pack.get('query')!r}\n"
                f"error: {pack['error']}\n{pack.get('message', '')}")

    lines = [f"Research pack for {pack.get('query') or 'the given URLs'!r}: "
             f"{pack['counts']['sources']} source(s) read, "
             f"{pack['counts']['failed']} failed.", ""]
    for index, source in enumerate(pack.get("sources") or []):
        lines.append(f"=== source[{index}] ===")
        if "sections" in source:
            lines.append(render_page(source))
        else:                                    # an academic record
            lines.append(json.dumps(source, ensure_ascii=False, indent=2))
        lines.append("")
    for failure in pack.get("failed") or []:
        lines.append(f"NOT READ: {failure['url']} — {failure['error']}: "
                     f"{failure['message']}")
    return "\n".join(lines).strip()


class WebResearchTool(Tool):
    """``perform_web_research`` — several sources in one governed call."""

    name = "perform_web_research"
    description = (
        "Reads several pages into one research pack: sources[] (each a typed "
        "page with url, title, sections[], links[]) and failed[] with the "
        "reason each unread URL was not read. Give `urls` to read pages you "
        "already know of; give `query` to ask the configured search provider "
        "first; `mode=academic` searches arXiv/Semantic Scholar/OpenAlex.")


    def __call__(
        self,
        query: Any = "",
        urls: Optional[Sequence[str]] = None,
        max_results: int = 5,
        max_pages: int = DEFAULT_MAX_PAGES,
        max_chars_per_page: int = 0,
        include_abstracts: bool = True,
        follow_links: int = 0,
        mode: str = "web",
        sources: Optional[Sequence[str]] = None,
        sleep_seconds: float = 0.0,
        timeout: Optional[float] = None,
        session: Any = None,
        **_ignored: Any,
    ):
        text_query = str(query or "")
        if str(mode or "web").lower() == "academic":
            pack = academic(text_query, max_results=max_results,
                            include_abstracts=include_abstracts,
                            sources=sources)
        else:
            if isinstance(urls, str):
                urls = [urls]
            pack = research(text_query, urls,
                            max_pages=max_pages, max_results=max_results,
                            follow_links=follow_links,
                            max_chars_per_page=max_chars_per_page,
                            sleep_seconds=sleep_seconds, timeout=timeout,
                            session=session)

        evidence = json.dumps(pack, ensure_ascii=False)
        text = render(pack)
        if pack["error"] and not pack["sources"]:
            return (1, "", text, evidence)
        return (0, text, "", evidence)
