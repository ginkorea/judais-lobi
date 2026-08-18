"""The keyless literature search behind ``perform_web_research(mode="academic")``.

Three public APIs that need no key — arXiv's Atom feed, Semantic
Scholar's graph endpoint, OpenAlex's works endpoint — normalised to one
record shape so a mission can cite a paper the same way whichever index
found it.

They matter more than they look: they are the one *search* this framework
can do with nothing configured, and ``perform_web_search`` cannot make
that promise (see :mod:`core.tools.web_search`). A literature question is
therefore answerable on a bare install, and the ``research`` pack says so.

Every source here goes through :func:`_get`, which is the one place the
user agent, the timeout and the ``RESEARCH_ALLOWED_HOSTS`` allow-list are
applied. An operator who narrowed the reachable web meant it, and a
second HTTP client in this package that quietly ignored that would be the
hole the allow-list exists to close.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import requests
from xml.etree import ElementTree

from core.tools.fetch_page import USER_AGENT, default_timeout, host_allowed


def _get(url: str, **params: Any) -> Optional[requests.Response]:
    """One GET, allow-listed and timed out, or ``None``.

    ``None`` rather than a raise, because a source that cannot be reached
    is one fewer index and not the end of the search: the caller merges
    what the reachable ones returned and
    :func:`~core.tools.web_research.academic` reports which answered.
    """
    if not host_allowed(url):
        return None
    try:
        response = requests.get(
            url,
            params=params or None,
            headers={"User-Agent": USER_AGENT},
            timeout=default_timeout(),
        )
        response.raise_for_status()
    except requests.RequestException:
        return None
    return response


class ResearchSource(ABC):
    name: str

    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> List[Dict]:
        raise NotImplementedError


class ArxivSource(ResearchSource):
    name = "arxiv"

    def search(self, query: str, max_results: int = 5) -> List[Dict]:
        url = (
            "http://export.arxiv.org/api/query?"
            f"search_query=all:{quote_plus(query)}"
            f"&start=0&max_results={max_results}"
        )
        res = _get(url)
        if res is None:
            return []
        try:
            root = ElementTree.fromstring(res.text)
        except ElementTree.ParseError:
            return []

        ns = {"atom": "http://www.w3.org/2005/Atom"}
        results: List[Dict] = []
        for entry in root.findall("atom:entry", ns):
            title = _clean_text(entry.findtext("atom:title", default="", namespaces=ns))
            summary = _clean_text(entry.findtext("atom:summary", default="", namespaces=ns))
            published = entry.findtext("atom:published", default="", namespaces=ns)
            year = published[:4] if published else ""
            authors = [
                _clean_text(a.findtext("atom:name", default="", namespaces=ns))
                for a in entry.findall("atom:author", ns)
            ]
            url = ""
            pdf_url = ""
            for link in entry.findall("atom:link", ns):
                rel = link.attrib.get("rel", "")
                href = link.attrib.get("href", "")
                title_attr = link.attrib.get("title", "")
                if rel == "alternate" and not url:
                    url = href
                if title_attr == "pdf" or href.endswith(".pdf"):
                    pdf_url = href
            results.append(
                {
                    "title": title,
                    "url": url,
                    "pdf_url": pdf_url,
                    "abstract": summary,
                    "authors": [a for a in authors if a],
                    "year": year,
                    "venue": "arXiv",
                    "doi": "",
                    "source": self.name,
                }
            )
        return results


class SemanticScholarSource(ResearchSource):
    name = "semantic_scholar"

    def search(self, query: str, max_results: int = 5) -> List[Dict]:
        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        params = {
            "query": query,
            "limit": max_results,
            "fields": "title,authors,year,venue,abstract,externalIds,url,openAccessPdf",
        }
        res = _get(url, **params)
        if res is None:
            return []
        try:
            data = res.json()
        except json.JSONDecodeError:
            return []
        results: List[Dict] = []
        for item in data.get("data", []):
            authors = [a.get("name", "") for a in item.get("authors", [])]
            external_ids = item.get("externalIds") or {}
            doi = external_ids.get("DOI", "") or ""
            open_pdf = item.get("openAccessPdf") or {}
            results.append(
                {
                    "title": item.get("title", "") or "",
                    "url": item.get("url", "") or "",
                    "pdf_url": open_pdf.get("url", "") or "",
                    "abstract": item.get("abstract", "") or "",
                    "authors": [a for a in authors if a],
                    "year": str(item.get("year", "") or ""),
                    "venue": item.get("venue", "") or "",
                    "doi": doi,
                    "source": self.name,
                }
            )
        return results


class OpenAlexSource(ResearchSource):
    name = "openalex"

    def search(self, query: str, max_results: int = 5) -> List[Dict]:
        url = "https://api.openalex.org/works"
        params = {
            "search": query,
            "per-page": max_results,
        }
        res = _get(url, **params)
        if res is None:
            return []
        try:
            data = res.json()
        except json.JSONDecodeError:
            return []
        results: List[Dict] = []
        for item in data.get("results", []):
            title = item.get("title", "") or ""
            doi = item.get("doi", "") or ""
            if doi.startswith("https://doi.org/"):
                doi = doi.replace("https://doi.org/", "")
            host_venue = item.get("host_venue") or {}
            venue = host_venue.get("display_name", "") or ""
            # `or {}` at every hop and not `.get(k, {})`: OpenAlex sends the
            # key with a null value for a work with no located source, and
            # `.get("primary_location", {})` returns that null, so the next
            # `.get` raised AttributeError on a record the index is entitled
            # to send. One unlocated paper took the whole search down.
            location = item.get("primary_location") or {}
            url = ((location.get("source") or {}).get("homepage_url") or "")
            if not url:
                url = item.get("id", "") or ""
            authors = [
                (a.get("author") or {}).get("display_name", "")
                for a in item.get("authorships", [])
            ]
            abstract = _decode_openalex_abstract(item.get("abstract_inverted_index"))
            results.append(
                {
                    "title": title,
                    "url": url,
                    "pdf_url": "",
                    "abstract": abstract,
                    "authors": [a for a in authors if a],
                    "year": str(item.get("publication_year", "") or ""),
                    "venue": venue,
                    "doi": doi,
                    "source": self.name,
                }
            )
        return results


def get_academic_sources() -> Dict[str, ResearchSource]:
    return {
        ArxivSource.name: ArxivSource(),
        SemanticScholarSource.name: SemanticScholarSource(),
        OpenAlexSource.name: OpenAlexSource(),
    }


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _decode_openalex_abstract(index: Optional[Dict]) -> str:
    if not index:
        return ""
    words = []
    for word, positions in index.items():
        for pos in positions:
            words.append((pos, word))
    words.sort(key=lambda item: item[0])
    return " ".join(w for _, w in words)
