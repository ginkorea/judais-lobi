# tests/test_web_tools.py — the three research tools, against a real local web

"""``fetch_page_content``, ``perform_web_research`` and ``perform_web_search``.

Every fetch in this file is a real HTTP request over a real socket to a
real server — ``tests/research_fixture_server.py``, on ``127.0.0.1`` with
an ephemeral port.  Nothing is mocked at the transport, because the bugs
these tools had were transport-shaped: a 404 that came back as prose with
exit code 0, a redirect whose destination was never recorded, a page cut
at 8 000 characters with nothing saying so.  A mocked ``requests.get``
would have passed every one of them.

Nothing leaves the machine.  No key, no provider, no route off localhost:
the base path of research — *here is a URL, read it* — is required to
work on a bare install and is tested as though it does.

The search tests are the exception and are deliberately hermetic: a test
that asked DuckDuckGo a question would be a test whose result depends on
somebody else's rate limiter.  What is asserted there is the *provider
contract* — selection, the refusal, the registration hook — with a
provider registered in the test.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest

from core.tools.descriptors import (FETCH_PAGE_DESCRIPTOR,
                                    WEB_RESEARCH_DESCRIPTOR,
                                    WEB_SEARCH_DESCRIPTOR)
from core.tools.fetch_page import (ALLOWED_HOSTS_ENV, MAX_PAGE_BYTES_ENV,
                                   FetchPageTool, PageRefused, check_url,
                                   extract, host_allowed, read_page)
from core.tools.web_research import WebResearchTool, research
from core.tools.web_search import (PROVIDER_ENV, SEARXNG_URL_ENV,
                                   PROVIDERS, SearchUnavailable,
                                   WebSearchTool, register_provider, search)
from tests.research_fixture_server import serving


@pytest.fixture(scope="module")
def site():
    with serving() as base:
        yield base


@pytest.fixture(autouse=True)
def _no_inherited_configuration(monkeypatch):
    """Every test starts from an unconfigured process.

    These tools read four environment variables, and a developer who has
    one of them set in their shell would otherwise get different results
    from CI. The allow-list especially: with it set to something else,
    every fetch below would be refused and the failures would all read as
    the wrong bug.
    """
    for name in (ALLOWED_HOSTS_ENV, MAX_PAGE_BYTES_ENV, PROVIDER_ENV,
                 SEARXNG_URL_ENV, "RESEARCH_TIMEOUT_S"):
        monkeypatch.delenv(name, raising=False)


def payload_of(result) -> dict:
    """The typed payload out of the bus's four-tuple."""
    assert isinstance(result, tuple) and len(result) == 4, result
    return json.loads(result[3])


# ── the page, as something citable ──────────────────────────────────────────

class TestOnePageComesBackCitable:
    """A page a mission can quote and a reader can check.

    The old tool returned the concatenated `<p>` text and nothing else.
    Every assertion here is a field an answer needs and did not have.
    """

    def test_the_url_title_and_text_are_all_there(self, site):
        page = read_page(f"{site}/solar-array.html")
        assert page["error"] == ""
        assert page["status"] == 200
        assert page["title"] == "Solar Array Annual Report 2025"
        assert page["final_url"] == f"{site}/solar-array.html"
        assert "1482 MWh" in page["text"]
        assert page["fetched_at"].endswith("Z")

    def test_the_page_arrives_as_sections_in_document_order(self, site):
        page = read_page(f"{site}/solar-array.html")
        headings = [s["heading"] for s in page["sections"]]
        assert headings == ["Solar Array Annual Report 2025", "Headline",
                            "Fleet", "What this report does not state"]
        assert "1482" in page["sections"][1]["text"]

    def test_chrome_is_not_content(self, site):
        """A nav bar in the extracted text is a nav bar in the quotation."""
        page = read_page(f"{site}/solar-array.html")
        assert "back to the archive" not in page["text"]
        assert "must never reach the extracted text" not in page["text"]

    def test_links_come_back_absolute(self, site):
        """A relative href is a URL the model has to resolve in its head."""
        page = read_page(f"{site}/wind-farm.html")
        urls = [link["url"] for link in page["links"]]
        assert f"{site}/turbine-log.html" in urls

    def test_a_redirect_reports_where_it_landed(self, site):
        page = read_page(f"{site}/moved.html")
        assert page["error"] == ""
        assert page["redirected"] is True
        assert page["url"] == f"{site}/moved.html"
        assert page["final_url"] == f"{site}/solar-array.html"

    def test_the_clock_donates_no_figures_to_the_evidence(self, site):
        """`fetched_at` is ISO 8601 BASIC, and that is not cosmetic.

        A tool result is evidence, and the figure check reads every number
        out of it. `2026-08-18T01:52:07+00:00` offers a two-digit minute
        and second, each preceded by a colon — so every fetch used to
        donate two arbitrary numbers under 60 to the evidence set, and an
        answer that invented "52 hours" was reported grounded whenever the
        clock agreed. Found as a test that failed one run in six.
        """
        from core.runtime.grounding import NumericGroundingCheck
        from core.tools.fetch_page import stamp

        for hour, minute, second in ((1, 52, 7), (23, 0, 59), (9, 41, 41)):
            when = datetime(2026, 8, 18, hour, minute, second,
                            tzinfo=timezone.utc)
            assert NumericGroundingCheck.FIGURE.findall(stamp(when)) == [], \
                stamp(when)

        page = read_page(f"{site}/solar-array.html")
        figures = NumericGroundingCheck.FIGURE.findall(page["fetched_at"])
        assert figures == [], page["fetched_at"]

    def test_plain_text_is_read_as_itself(self, site):
        page = read_page(f"{site}/plain.txt")
        assert page["error"] == ""
        assert "71 units" in page["text"]


# ── the failures, each with its own name ────────────────────────────────────

class TestEveryFailureSaysWhichFailureItWas:
    """Four ways of not reading a page, and four different answers.

    They were one string — `"Failed to fetch or parse: …"` at exit code 0
    — and a mission cannot tell "the page is gone" from "the tool broke"
    from "you may not read that" when they arrive spelled the same way.
    """

    def test_a_404_is_a_result_and_not_an_exception(self, site):
        page = read_page(f"{site}/retired.html")
        assert page["status"] == 404
        assert page["error"] == "http_404"
        assert "404" in page["message"]
        assert page["text"] == ""

    def test_a_404_exits_nonzero_through_the_tool(self, site):
        code, out, err, evidence = FetchPageTool()(f"{site}/retired.html")
        assert code == 1
        assert out == ""
        assert "COULD NOT READ" in err
        assert json.loads(evidence)["status"] == 404

    def test_a_timeout_says_so(self, site):
        page = read_page(f"{site}/slow.html", timeout=0.5)
        assert page["error"] == "timeout"
        assert "/slow.html" in page["message"]

    def test_a_non_text_body_is_refused_by_content_type(self, site):
        page = read_page(f"{site}/binary.bin")
        assert page["error"] == "not_text"
        assert "octet-stream" in page["message"]

    def test_a_body_past_the_ceiling_is_not_read(self, site, monkeypatch):
        monkeypatch.setenv(MAX_PAGE_BYTES_ENV, "50000")
        page = read_page(f"{site}/huge.html")
        assert page["error"] == "too_large"
        assert MAX_PAGE_BYTES_ENV in page["message"]

    def test_the_same_body_under_the_default_ceiling_is_read(self, site):
        """The ceiling is a ceiling and not a refusal of large pages."""
        page = read_page(f"{site}/huge.html")
        assert page["error"] == ""
        assert page["title"] == "Huge"


class TestWhatItWillNotEvenTry:
    """Rules settled before a socket is opened."""

    def test_a_file_url_is_a_filesystem_read_wearing_a_scheme(self):
        with pytest.raises(PageRefused) as exc:
            check_url("file:///etc/passwd")
        assert exc.value.error == "bad_scheme"
        assert "http.read" in str(exc.value)

    def test_a_file_url_through_the_tool_is_a_refusal_not_a_read(self, tmp_path):
        secret = tmp_path / "secret.txt"
        secret.write_text("the figure is 999", encoding="utf-8")
        page = read_page(f"file://{secret}")
        assert page["error"] == "bad_scheme"
        assert "999" not in json.dumps(page)

    def test_a_host_outside_the_allow_list_is_refused_by_name(
            self, site, monkeypatch):
        monkeypatch.setenv(ALLOWED_HOSTS_ENV, "example.org")
        page = read_page(f"{site}/solar-array.html")
        assert page["error"] == "host_not_allowed"
        assert ALLOWED_HOSTS_ENV in page["message"]
        assert "do not retry" in page["message"]

    def test_the_allow_list_lets_the_named_host_through(self, site, monkeypatch):
        monkeypatch.setenv(ALLOWED_HOSTS_ENV, "127.0.0.1, example.org")
        page = read_page(f"{site}/solar-array.html")
        assert page["error"] == ""

    def test_a_leading_dot_covers_subdomains_and_nothing_else(self):
        hosts = (".example.org",)
        assert host_allowed("https://docs.example.org/a", hosts)
        assert host_allowed("https://example.org/a", hosts)
        assert not host_allowed("https://notexample.org/a", hosts)

    def test_an_unset_allow_list_allows(self, site):
        assert host_allowed(f"{site}/x", ())


# ── the extractor on its own ────────────────────────────────────────────────

class TestTheExtractor:
    def test_nested_blocks_are_counted_once(self):
        """A `<p>` inside an `<li>` inside a `<td>` is one piece of text."""
        html = ("<html><body><main><h1>H</h1>"
                "<table><tr><td><ul><li><p>only once</p></li></ul></td></tr>"
                "</table></main></body></html>")
        section = extract(html)["sections"][0]
        assert section["text"].count("only once") == 1

    def test_a_page_with_no_block_markup_still_yields_its_text(self):
        html = "<html><body>a bare sentence with the figure 12</body></html>"
        assert "12" in extract(html)["text"]

    def test_chrome_inside_the_main_content_is_stripped_too(self):
        """The tag list, not the `<main>` selector, is what does this.

        `test_chrome_is_not_content` above passes on the fixture site
        whether or not `_NOT_CONTENT` exists, because that site puts its
        nav outside `<main>`. Plenty of real pages do not, and a menu
        quoted as if it were the article is a citation to nothing.
        """
        html = ("<html><body><main><h1>H</h1>"
                "<nav><a href=\"/menu\">menu noise</a></nav>"
                "<script>var leak = 'script noise';</script>"
                "<footer>footer noise</footer>"
                "<p>the real text</p></main></body></html>")
        out = extract(html, base_url="http://h/")
        assert "the real text" in out["text"]
        for noise in ("menu noise", "script noise", "footer noise"):
            assert noise not in out["text"], noise
        assert out["links"] == [], "a nav link is not a link on the article"

    def test_a_title_falls_back_to_the_first_h1(self):
        html = "<html><body><main><h1>The Heading</h1><p>x</p></main></body></html>"
        assert extract(html)["title"] == "The Heading"

    def test_fragment_and_javascript_hrefs_are_not_links(self):
        html = ('<html><body><main><a href="#top">t</a>'
                '<a href="javascript:void(0)">j</a>'
                '<a href="/real.html">r</a></main></body></html>')
        links = extract(html, base_url="http://h/")["links"]
        assert [link["url"] for link in links] == ["http://h/real.html"]


# ── the research pack ───────────────────────────────────────────────────────

class TestResearchWithoutASearchEngine:
    """The claim the pack rests on: given URLs, this needs nothing configured."""

    def test_given_urls_are_read_into_one_pack(self, site):
        pack = research(urls=[f"{site}/solar-array.html",
                              f"{site}/wind-farm.html"])
        assert pack["error"] == ""
        assert pack["counts"] == {"sources": 2, "failed": 0}
        assert [s["title"] for s in pack["sources"]] == [
            "Solar Array Annual Report 2025", "Wind Farm Annual Report 2025"]

    def test_a_page_that_failed_is_in_the_pack_as_a_failure(self, site):
        """Silently dropping it lets an answer say it read three of three."""
        pack = research(urls=[f"{site}/solar-array.html",
                              f"{site}/retired.html"])
        assert pack["counts"] == {"sources": 1, "failed": 1}
        assert pack["failed"][0]["error"] == "http_404"
        assert pack["failed"][0]["url"].endswith("/retired.html")

    def test_follow_links_reaches_the_page_the_first_one_named(self, site):
        pack = research(urls=[f"{site}/wind-farm.html"], follow_links=2)
        read = [s["final_url"] for s in pack["sources"]]
        assert f"{site}/turbine-log.html" in read
        assert any("37 hours" in s["text"] for s in pack["sources"])

    def test_nothing_is_followed_by_default(self, site):
        pack = research(urls=[f"{site}/wind-farm.html"])
        assert pack["counts"]["sources"] == 1

    def test_max_pages_is_a_ceiling(self, site):
        pack = research(urls=[f"{site}/solar-array.html",
                              f"{site}/wind-farm.html",
                              f"{site}/thermal.html"], max_pages=2)
        assert pack["counts"]["sources"] == 2

    def test_no_urls_and_no_query_says_so_rather_than_searching(self):
        pack = research()
        assert pack["error"] == "nothing_to_read"

    def test_the_tool_returns_the_pack_as_typed_evidence(self, site):
        result = WebResearchTool()(urls=[f"{site}/thermal.html"])
        assert result[0] == 0
        pack = payload_of(result)
        assert pack["sources"][0]["title"] == "District Heat Report 2025"
        assert "9600 GJ" in pack["sources"][0]["text"]


class TestSearchIsAProviderAndSaysWhichOne:
    """A search engine is somebody else's service, and this framework has none.

    The failure being tested for is the old tool's `"No results found."`:
    a scrape that broke and an empty web spelled identically, which are
    opposite findings for a research answer.
    """

    def test_an_unknown_provider_names_what_there_is(self, monkeypatch):
        monkeypatch.setenv(PROVIDER_ENV, "nosuchengine")
        found = search("anything")
        assert found["error"] == "unknown_provider"
        assert "duckduckgo" in found["message"]
        assert found["results"] == []

    def test_a_provider_that_cannot_answer_refuses_by_name(self, monkeypatch):
        def _broken(query, max_results, timeout):
            raise SearchUnavailable("the `stub` provider is switched off")

        monkeypatch.setitem(PROVIDERS, "stub", _broken)
        monkeypatch.setenv(PROVIDER_ENV, "stub")
        found = search("anything")
        assert found["error"] == "provider_unavailable"
        assert "`stub`" in found["message"]

    def test_a_refusal_is_rendered_as_the_engine_failing_not_an_empty_web(
            self, monkeypatch):
        from core.tools.web_search import render

        def _broken(query, max_results, timeout):
            raise SearchUnavailable("off")

        monkeypatch.setitem(PROVIDERS, "stub", _broken)
        monkeypatch.setenv(PROVIDER_ENV, "stub")
        text = render(search("anything"))
        assert "NOT an empty web" in text

    def test_an_empty_result_list_is_a_finding_and_not_a_refusal(
            self, monkeypatch):
        monkeypatch.setitem(PROVIDERS, "stub", lambda q, n, t: [])
        monkeypatch.setenv(PROVIDER_ENV, "stub")
        found = search("anything")
        assert found["error"] == ""
        assert found["count"] == 0

    def test_a_registered_provider_answers(self, monkeypatch, site):
        """THE HOOK: a platform's keyed API is one function in its own repo."""
        monkeypatch.setitem(
            PROVIDERS, "stub",
            lambda q, n, t: [{"title": "Solar", "snippet": "s",
                              "url": f"{site}/solar-array.html"}])
        monkeypatch.setenv(PROVIDER_ENV, "stub")
        found = search("solar")
        assert found["provider"] == "stub"
        assert found["results"][0]["url"].endswith("/solar-array.html")

    def test_register_provider_refuses_a_non_callable(self):
        with pytest.raises(ValueError):
            register_provider("bad", "not a function")

    def test_searxng_without_an_instance_names_the_variable(self, monkeypatch):
        monkeypatch.setenv(PROVIDER_ENV, "searxng")
        found = search("anything")
        assert found["error"] == "provider_unavailable"
        assert SEARXNG_URL_ENV in found["message"]

    def test_the_tool_exits_nonzero_when_search_did_not_run(self, monkeypatch):
        monkeypatch.setenv(PROVIDER_ENV, "nosuchengine")
        result = WebSearchTool()(query="anything")
        assert result[0] == 1
        assert payload_of(result)["error"] == "unknown_provider"

    def test_research_by_query_carries_the_search_refusal_through(
            self, monkeypatch):
        """No invented sources when the engine did not run."""
        monkeypatch.setenv(PROVIDER_ENV, "nosuchengine")
        pack = research("some question")
        assert pack["error"] == "unknown_provider"
        assert pack["sources"] == []


# ── the descriptors these tools are dispatched under ────────────────────────

class TestTheDescriptorsMatchTheTools:
    """A catalogue that names an argument the tool does not take costs a turn."""

    @pytest.mark.parametrize("descriptor", [FETCH_PAGE_DESCRIPTOR,
                                            WEB_RESEARCH_DESCRIPTOR,
                                            WEB_SEARCH_DESCRIPTOR])
    def test_every_research_descriptor_publishes_its_arguments(self, descriptor):
        assert descriptor.input_schema.get("properties")

    @pytest.mark.parametrize("descriptor,tool", [
        (FETCH_PAGE_DESCRIPTOR, FetchPageTool()),
        (WEB_RESEARCH_DESCRIPTOR, WebResearchTool()),
        (WEB_SEARCH_DESCRIPTOR, WebSearchTool()),
    ])
    def test_every_published_argument_is_one_the_tool_accepts(
            self, descriptor, tool):
        import inspect

        accepted = set(inspect.signature(tool.__call__).parameters)
        for name in descriptor.input_schema["properties"]:
            assert name in accepted, f"{descriptor.tool_name} has no {name!r}"

    def test_they_all_ask_for_http_read_and_nothing_else(self):
        for descriptor in (FETCH_PAGE_DESCRIPTOR, WEB_RESEARCH_DESCRIPTOR,
                           WEB_SEARCH_DESCRIPTOR):
            assert descriptor.required_scopes == ["http.read"]
            assert descriptor.requires_network is True


class TestTheToolsRunUnderTheResearchProfileAndNotBelowIt:
    """The 0.9.0 residual, asserted where it bites: on the bus.

    `http.read` was an OPS scope, so an agent that had to read three
    public pages was handed the profile that can also push and install.
    """

    @staticmethod
    def _bus(profile):
        from core.contracts.schemas import ProfileMode
        from core.tools.bus import ToolBus
        from core.tools.capability import CapabilityEngine
        from core.tools.fetch_page import FetchPageTool

        engine = CapabilityEngine()
        engine.set_profile(getattr(ProfileMode, profile))
        bus = ToolBus(capability_engine=engine, audit=None)
        bus.register(FETCH_PAGE_DESCRIPTOR, FetchPageTool())
        return bus

    def test_dev_is_denied_and_the_refusal_names_research(self, site):
        result = self._bus("DEV").dispatch("fetch_page_content",
                                           f"{site}/solar-array.html")
        assert result.exit_code == -1
        assert "http.read" in result.stderr

    def test_research_may_read_the_page(self, site):
        result = self._bus("RESEARCH").dispatch("fetch_page_content",
                                                f"{site}/solar-array.html")
        assert result.exit_code == 0
        assert "1482 MWh" in result.stdout
        assert json.loads(result.evidence)["title"].startswith("Solar Array")

    def test_research_still_cannot_push_or_install(self):
        from core.policy.profiles import PROFILE_SCOPES
        from core.contracts.schemas import ProfileMode

        granted = set()
        for level in ProfileMode:
            granted |= set(PROFILE_SCOPES[level])
            if level is ProfileMode.RESEARCH:
                break
        assert "http.read" in granted
        assert {"git.push", "pip.install", "fs.delete"} & granted == set()
