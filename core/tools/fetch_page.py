# core/tools/fetch_page.py — one page off the open web, as a typed result

"""Fetch a URL and turn it into something a mission can cite.

The tool this module ships is the floor of the ``research`` pack: with
nothing configured — no API key, no search provider, no browser — an
agent under ``--profile research`` can be handed a URL and read the page
at it.  Everything else research does is built on that: a search engine
proposes URLs, a link on one page names another, but the reading is
here.

**What changed and why.**  The 0.7-era tool returned *a string of the
page's paragraphs*, up to ``max_chars``, and the string was all a caller
got: a failure came back as the prose ``"Failed to fetch or parse: …"``
with exit code 0, a 404 was indistinguishable from an empty page, and a
long page was cut at 8 000 characters with nothing saying what had gone.
An agent asked to cite the page it read had a paragraph and no URL, no
title, no status, no way back to the part that was cut.  Three of those
are the difference between a research answer and a plausible one.

So the result is **typed**, and the type is the contract:

* ``url`` / ``final_url`` — what was asked for, and where the redirects
  ended.  The pair is the citation, and they are separate fields because
  an answer that cites the URL it was given when the server moved it is
  citing a page it did not read;
* ``status`` — the HTTP status.  A 404 is a *result*, not an exception:
  ``exit_code`` is 1, the payload says ``status: 404``, and the mission
  can report that the page is not there.  The failure this replaces is
  an agent that reads ``Failed to fetch`` as "the tool is broken", tries
  twice more and then answers from memory;
* ``title``, ``headings``, ``sections`` — the page's own structure.
  ``sections`` is the field that makes a long page readable: each
  heading and the text under it, so a model whose transcript got a
  bounded cut asks the result store for ``sections[7].text`` instead of
  asking for a bigger cut.  See :mod:`core.runtime.results`;
* ``links`` — every anchor in the main content, resolved to absolute
  URLs.  Research is following one page to the next, and a relative
  ``href`` a model has to resolve in its head is a URL it will get
  wrong;
* ``fetched_at`` — when.  A page is a claim about a moment.  Written in
  ISO 8601 **basic** form (``20260818T015207Z``) and not the extended one,
  which is not cosmetic: see :func:`stamp`.

**No new dependency.**  ``requests`` and ``beautifulsoup4`` are already
hard requirements of this package; the parser asked for is stdlib
``html.parser``, never ``lxml``, so a wheel that installs cleanly today
installs cleanly after this.

**What it refuses, and by name.**  A scheme that is not ``http``/
``https`` (``file://`` is a filesystem read wearing a URL, and this tool
holds ``http.read`` and not ``fs.read``); a host outside
``RESEARCH_ALLOWED_HOSTS`` when that is set; a body past
``RESEARCH_MAX_PAGE_BYTES``; a response that is not text.  Each comes
back as a payload with ``error`` naming the rule and, where there is
one, the environment variable that would change it — the refusal names
the fix, like every other refusal in this framework.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from core.tools.tool import Tool

#: Comma-separated hosts this process may fetch from.  **Unset means no
#: restriction**, which is the honest default for a tool whose whole job
#: is the open web and whose scope (``http.read``) is already a decision
#: an operator made with ``--profile research``.  Set, it is a hard
#: allow-list checked before a socket is opened: an operator running a
#: mission against a known corpus can say so, and a page the model
#: invented an address for is refused by name rather than fetched.
#:
#: A leading dot means "and its subdomains" (``.example.org`` matches
#: ``docs.example.org``); anything else is an exact host match.  The port
#: is not part of it — a host is a host.
ALLOWED_HOSTS_ENV = "RESEARCH_ALLOWED_HOSTS"

#: How many bytes of a response body are read before the fetch is
#: refused, as a string an operator can set.  A bound on the *download*
#: and not on the result: :data:`core.bounding.MAX_RESULT_BYTES` decides
#: how much of the extracted text a model sees, and the store keeps the
#: whole extraction either way.  This one exists because a 400 MB file
#: served as ``text/html`` should not be read into this process at all.
MAX_PAGE_BYTES_ENV = "RESEARCH_MAX_PAGE_BYTES"

#: Default for :data:`MAX_PAGE_BYTES_ENV`: 4 MiB, which is far past any
#: article and far short of a corpus dump.
DEFAULT_MAX_PAGE_BYTES = 4 * 1024 * 1024

#: Seconds before a fetch gives up, as an environment override.
TIMEOUT_ENV = "RESEARCH_TIMEOUT_S"

DEFAULT_TIMEOUT_S = 20.0

#: How ``fetched_at`` is written.  ISO 8601 basic, and the reason is
#: :func:`stamp`.
STAMP_FORMAT = "%Y%m%dT%H%M%SZ"

#: The chunk the body is read in.  Small enough that the size limit is
#: enforced on the way in rather than after the whole thing has landed.
_CHUNK = 64 * 1024

#: What this fetcher calls itself to a server.  A named, honest agent
#: string rather than a browser's: a site that would rather not be read
#: by a robot is entitled to know that it is talking to one.
USER_AGENT = "judais-lobi-research/1.0 (+https://github.com/ginkorea/judais-lobi)"

#: Stripped before any text is taken.  Chrome, not content: a nav bar in
#: the extracted text is a nav bar in the answer's quotations.
_NOT_CONTENT = (
    "script", "style", "noscript", "template", "svg", "iframe",
    "nav", "header", "footer", "aside", "form", "button",
)

#: Where the main content usually is, in the order worth trying.  Falls
#: back to ``<body>``, which is always right and sometimes noisy.
_MAIN_SELECTORS = ("main", "article", "[role=main]", "#content", "#main")

_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")

_WHITESPACE = re.compile(r"\s+")


def stamp(when: Optional[datetime] = None) -> str:
    """Now, as ``20260818T015207Z`` — and the compact form is load-bearing.

    A tool result is **evidence**, and
    :class:`~core.runtime.grounding.NumericGroundingCheck` reads every
    figure out of it: an answer's number is grounded when some figure in
    some result equals it.  An extended timestamp —
    ``2026-08-18T01:52:07+00:00`` — offers that check a two-digit minute
    and a two-digit second, each preceded by a colon, which is not a word
    character, so ``FIGURE`` matches them.  Every fetch therefore donated
    two arbitrary numbers between 0 and 59 to the evidence set.

    That is the laundering ``NumericGroundingCheck.prepare``'s own
    docstring warns about, arriving through the clock: a model that
    invented "the outage lasted 52 hours" was reported as **grounded**
    whenever the page happened to be fetched at 52 seconds past. It was
    found as a test that failed about one run in six, which is what that
    defect looks like from outside — and the same trap is waiting for any
    platform whose tool results carry a wall clock.

    The basic form has no separators, so the whole run of digits is
    followed by ``T`` and the time by ``Z``; ``FIGURE``'s word-character
    boundaries refuse both, and the timestamp contributes **no** figures
    at all.  It is still ISO 8601 and still the same instant.
    """
    when = when or datetime.now(timezone.utc)
    return when.astimezone(timezone.utc).strftime(STAMP_FORMAT)


class PageRefused(ValueError):
    """A fetch this tool will not make, with the rule that stopped it."""

    def __init__(self, error: str, message: str):
        super().__init__(message)
        #: A short machine word — ``bad_scheme``, ``host_not_allowed`` —
        #: so a mission can branch on the *kind* of refusal without
        #: reading prose.
        self.error = error
        self.message = message


# ── the knobs, read at call time ────────────────────────────────────────────

def allowed_hosts() -> Tuple[str, ...]:
    """The configured allow-list, or ``()`` for "no restriction"."""
    raw = os.getenv(ALLOWED_HOSTS_ENV, "") or ""
    return tuple(part.strip().lower() for part in raw.split(",") if part.strip())


def max_page_bytes() -> int:
    """The download ceiling.  A malformed value is the default, not a crash."""
    try:
        value = int(os.getenv(MAX_PAGE_BYTES_ENV, "") or 0)
    except ValueError:
        return DEFAULT_MAX_PAGE_BYTES
    return value if value > 0 else DEFAULT_MAX_PAGE_BYTES


def default_timeout() -> float:
    try:
        value = float(os.getenv(TIMEOUT_ENV, "") or 0)
    except ValueError:
        return DEFAULT_TIMEOUT_S
    return value if value > 0 else DEFAULT_TIMEOUT_S


def host_allowed(url: str, hosts: Optional[Tuple[str, ...]] = None) -> bool:
    """Whether *url*'s host passes the allow-list.  Empty list allows all."""
    hosts = allowed_hosts() if hosts is None else hosts
    if not hosts:
        return True
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    for entry in hosts:
        if entry.startswith("."):
            if host == entry[1:] or host.endswith(entry):
                return True
        elif host == entry:
            return True
    return False


def check_url(url: str) -> str:
    """*url*, or a :class:`PageRefused` naming the rule it broke.

    The two rules that must be settled **before a socket is opened**: the
    scheme, because ``file:///etc/shadow`` through a tool holding
    ``http.read`` would be a filesystem read that no ``fs.read`` scope
    was ever asked for; and the allow-list, because an operator who
    narrowed the reachable web meant it.
    """
    url = (url or "").strip()
    if not url:
        raise PageRefused("no_url", "No URL given; this tool reads one page.")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise PageRefused(
            "bad_scheme",
            f"{url!r} is not an http(s) URL. This tool holds `http.read` and "
            f"reads the web; a local file is a different tool and a "
            f"different scope.")
    if not parsed.hostname:
        raise PageRefused("no_host", f"{url!r} names no host.")
    if not host_allowed(url):
        raise PageRefused(
            "host_not_allowed",
            f"{parsed.hostname} is not in {ALLOWED_HOSTS_ENV} "
            f"({', '.join(allowed_hosts())}), so this run may not fetch it. "
            f"That is an operator's decision for this session, not a "
            f"transient failure — do not retry it and do not answer as "
            f"though the page had been read.")
    return url


# ── the fetch ───────────────────────────────────────────────────────────────

def fetch_html(url: str, *, timeout: Optional[float] = None,
               session: Any = None) -> Dict[str, Any]:
    """One HTTP GET, bounded, with everything a citation needs.

    Returns ``{url, final_url, status, content_type, html, bytes,
    redirected, error, message}``.  ``error`` is ``""`` on success and a
    machine word otherwise; **the function does not raise** for anything
    the network did, because "the page is not there" is an answer a
    research mission has to be able to give.

    *session* is the seam a platform reaches for: anything with a
    ``get(url, headers=…, timeout=…, stream=True, allow_redirects=True)``
    will do, so a deployment behind a proxy or holding a cache passes its
    own ``requests.Session`` and this module keeps no opinion about it.
    """
    try:
        url = check_url(url)
    except PageRefused as refusal:
        return _failed(url, refusal.error, refusal.message)

    getter = session if session is not None else requests
    limit = max_page_bytes()
    try:
        response = getter.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.5"},
            timeout=timeout if timeout is not None else default_timeout(),
            stream=True,
            allow_redirects=True,
        )
    except requests.Timeout as exc:
        return _failed(url, "timeout", f"{url} did not answer in time: {exc}")
    except requests.RequestException as exc:
        return _failed(url, "unreachable", f"{url} could not be reached: {exc}")

    final_url = str(getattr(response, "url", "") or url)
    status = int(getattr(response, "status_code", 0) or 0)
    content_type = str(response.headers.get("Content-Type", "") or "")

    body = b""
    over = False
    try:
        for chunk in response.iter_content(_CHUNK):
            if not chunk:
                continue
            body += chunk
            if len(body) > limit:
                over = True
                break
    except requests.RequestException as exc:
        return _failed(url, "truncated_stream",
                       f"{url} stopped mid-body: {exc}", status=status,
                       final_url=final_url, content_type=content_type)
    finally:
        try:
            response.close()
        except Exception:                        # pragma: no cover - defensive
            pass

    if over:
        return _failed(
            url, "too_large",
            f"{url} is larger than {limit} bytes and was not read. Raise "
            f"{MAX_PAGE_BYTES_ENV} if this page is genuinely wanted.",
            status=status, final_url=final_url, content_type=content_type)

    if status >= 400:
        return _failed(
            url, f"http_{status}",
            f"{url} answered HTTP {status}. The page was not read, so "
            f"nothing about its contents can be stated.",
            status=status, final_url=final_url, content_type=content_type)

    encoding = getattr(response, "encoding", None) or "utf-8"
    try:
        text = body.decode(encoding, "replace")
    except LookupError:
        text = body.decode("utf-8", "replace")

    return {
        "url": url,
        "final_url": final_url,
        "status": status,
        "content_type": content_type,
        "html": text,
        "bytes": len(body),
        "redirected": final_url != url,
        "error": "",
        "message": "",
    }


def _failed(url: str, error: str, message: str, *, status: int = 0,
            final_url: str = "", content_type: str = "") -> Dict[str, Any]:
    return {
        "url": url,
        "final_url": final_url or url,
        "status": status,
        "content_type": content_type,
        "html": "",
        "bytes": 0,
        "redirected": False,
        "error": error,
        "message": message,
    }


# ── the extraction ──────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    return _WHITESPACE.sub(" ", text or "").strip()


def _soup(html: str) -> BeautifulSoup:
    """Parsed with the stdlib parser, on purpose.

    ``lxml`` is faster and is not a dependency of this package.  A parser
    chosen by whatever happens to be installed is a tool that extracts
    different text on two machines, which is the worst property a
    citation can have.
    """
    return BeautifulSoup(html or "", "html.parser")


def _main_node(soup: BeautifulSoup):
    for selector in _MAIN_SELECTORS:
        found = soup.select_one(selector)
        if found is not None:
            return found
    return soup.body or soup


def extract(html: str, *, base_url: str = "") -> Dict[str, Any]:
    """Readable text, structure and links out of one HTML document.

    ``{title, headings, sections, text, links}``.  Sections are the
    interesting part: ``[{heading, level, text}]`` in document order,
    with the material before the first heading carried as a section whose
    heading is ``""``.  A model reading a long page through the mission
    result store asks for one of these rather than for more of the whole.
    """
    soup = _soup(html)
    title = _clean(soup.title.get_text()) if soup.title else ""

    for tag in soup(_NOT_CONTENT):
        tag.decompose()

    node = _main_node(soup)
    if not title:
        first_h1 = node.find("h1")
        title = _clean(first_h1.get_text()) if first_h1 else ""

    sections: List[Dict[str, Any]] = []
    current = {"heading": "", "level": 0, "parts": []}
    for element in node.find_all(
            [*_HEADINGS, "p", "li", "td", "th", "pre", "blockquote", "dd",
             "dt", "figcaption"]):
        name = element.name.lower()
        if name in _HEADINGS:
            if current["parts"] or current["heading"]:
                sections.append(current)
            current = {"heading": _clean(element.get_text(" ")),
                       "level": int(name[1]), "parts": []}
            continue
        # A <p> inside a <li> inside a <td> would otherwise be counted
        # three times. Only the innermost block contributes its text.
        if element.find([*_HEADINGS, "p", "li", "td", "th", "pre",
                         "blockquote", "dd", "dt", "figcaption"]):
            continue
        chunk = _clean(element.get_text(" "))
        if chunk:
            current["parts"].append(chunk)
    if current["parts"] or current["heading"]:
        sections.append(current)

    rendered = [
        {"heading": s["heading"], "level": s["level"],
         "text": " ".join(s["parts"])}
        for s in sections
    ]
    # A page with no block-level markup at all — a bare string in a body —
    # would otherwise extract to nothing and read as an empty page, which
    # is a different fact from "there is nothing here worth quoting".
    if not any(s["text"] for s in rendered):
        whole = _clean(node.get_text(" ")) if node else ""
        rendered = [{"heading": "", "level": 0, "text": whole}] if whole else []

    text = "\n\n".join(
        (f"{s['heading']}\n{s['text']}" if s["heading"] else s["text"]).strip()
        for s in rendered if s["heading"] or s["text"]
    ).strip()

    links: List[Dict[str, str]] = []
    seen = set()
    for anchor in node.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        absolute = urljoin(base_url, href) if base_url else href
        if absolute in seen:
            continue
        seen.add(absolute)
        links.append({"url": absolute, "text": _clean(anchor.get_text(" "))})

    return {
        "title": title,
        "headings": [s["heading"] for s in rendered if s["heading"]],
        "sections": rendered,
        "text": text,
        "links": links,
    }


def read_page(url: str, *, timeout: Optional[float] = None,
              max_chars: int = 0, session: Any = None) -> Dict[str, Any]:
    """:func:`fetch_html` then :func:`extract`, as the one payload a tool returns.

    ``max_chars`` bounds ``text`` **and says so** in ``truncated``; zero
    is no bound and is the default, because the store keeps the whole
    result and :mod:`core.bounding` decides what a model sees.  A caller
    that genuinely wants less asks for less.
    """
    fetched = fetch_html(url, timeout=timeout, session=session)
    payload: Dict[str, Any] = {
        "url": fetched["url"],
        "final_url": fetched["final_url"],
        "status": fetched["status"],
        "content_type": fetched["content_type"],
        "redirected": fetched["redirected"],
        "fetched_at": stamp(),
        "title": "",
        "headings": [],
        "sections": [],
        "text": "",
        "links": [],
        "char_count": 0,
        "truncated": False,
        "error": fetched["error"],
        "message": fetched["message"],
    }
    if fetched["error"]:
        return payload

    kind = fetched["content_type"].split(";")[0].strip().lower()
    if kind and not (kind.startswith("text/") or kind in (
            "application/xhtml+xml", "application/xml", "application/json")):
        payload["error"] = "not_text"
        payload["message"] = (
            f"{fetched['final_url']} is {kind}, which this tool does not "
            f"read. Nothing about its contents can be stated.")
        return payload

    if kind in ("text/plain", "application/json") or (
            kind == "" and "<" not in fetched["html"][:200]):
        text = fetched["html"]
        payload.update({
            "title": "",
            "sections": [{"heading": "", "level": 0, "text": text}],
            "text": text,
        })
    else:
        payload.update(extract(fetched["html"],
                               base_url=fetched["final_url"]))

    text = payload["text"]
    if max_chars and len(text) > max_chars:
        payload["text"] = text[:max_chars].rstrip()
        payload["truncated"] = True
    payload["char_count"] = len(text)
    return payload


def render(payload: Dict[str, Any]) -> str:
    """The page as the prose a model reads in the transcript.

    Labelled, because an unlabelled wall of text is a page a model will
    later cite by the wrong URL.  The header is four lines and then the
    section list, so the *shape* of the page survives even when
    :func:`core.bounding.bound_result` cuts the middle out of the body.
    """
    if payload.get("error"):
        return (f"COULD NOT READ {payload.get('url', '')}\n"
                f"error: {payload['error']}\n"
                f"{payload.get('message', '')}")
    lines = [
        f"URL: {payload.get('final_url') or payload.get('url', '')}",
        f"Title: {payload.get('title') or '(none)'}",
        f"Fetched at: {payload.get('fetched_at', '')}",
        f"Sections: {len(payload.get('sections') or [])}; "
        f"links: {len(payload.get('links') or [])}; "
        f"characters: {payload.get('char_count', 0)}",
        "",
    ]
    for index, section in enumerate(payload.get("sections") or []):
        heading = section.get("heading") or "(no heading)"
        lines.append(f"[{index}] {heading}")
        if section.get("text"):
            lines.append(section["text"])
        lines.append("")
    links = payload.get("links") or []
    if links:
        lines.append("Links on this page:")
        lines.extend(f"- {item['url']}"
                     + (f" — {item['text']}" if item.get("text") else "")
                     for item in links)
    return "\n".join(lines).strip()


class FetchPageTool(Tool):
    """``fetch_page_content`` — one URL in, one typed page out.

    Returns the bus's four-tuple ``(exit_code, stdout, stderr,
    evidence)``: the rendered page for the transcript, and the payload as
    JSON for :mod:`core.runtime.results`, which keeps it whole so the
    model can read ``sections[3].text`` later instead of asking for a
    bigger cut of the same page.  ``exit_code`` is 1 for every refusal
    and every HTTP error, so a mission's own record of what failed is not
    a piece of prose somebody has to pattern-match.
    """

    name = "fetch_page_content"
    description = (
        "Fetches one http(s) URL and returns its readable text as a typed "
        "page: url, final_url, status, title, fetched_at, sections[] "
        "(heading + text, in document order) and links[]. Read one section "
        "of a long page back through mission_result rather than refetching.")


    def __call__(self, url: Any = "", max_chars: int = 0,
                 timeout: Optional[float] = None, session: Any = None,
                 **_ignored: Any):
        payload = read_page(str(url or ""), timeout=timeout,
                            max_chars=int(max_chars or 0), session=session)
        evidence = json.dumps(payload, ensure_ascii=False)
        if payload["error"]:
            return (1, "", render(payload), evidence)
        return (0, render(payload), "", evidence)
