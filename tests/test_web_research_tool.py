# tests/test_web_research_tool.py

"""`perform_web_research(mode="academic")` — the keyless literature search.

Stubbed at the *source* and not at the transport: what is under test is
the merge, the de-duplication and the shape of the pack, and the three
real indexes (arXiv, Semantic Scholar, OpenAlex) are somebody else's
uptime. The HTTP half of this tool is tested against a real local server
in `tests/test_web_tools.py`.
"""

import json

from core.tools.web_research import WebResearchTool


class DummySource:
    name = "dummy"

    def search(self, query: str, max_results: int = 5):
        return [
            {
                "title": "Paper A",
                "url": "https://example.com/a",
                "pdf_url": "",
                "abstract": "Abstract A",
                "authors": ["Author One"],
                "year": "2024",
                "venue": "TestConf",
                "doi": "10.0000/test",
                "source": "dummy",
            }
        ]


class EmptySource:
    name = "empty"

    def search(self, query: str, max_results: int = 5):
        return []


def _fake_sources(**sources):
    def _get():
        return sources
    return _get


def test_academic_mode_with_stub_sources(monkeypatch):
    monkeypatch.setattr("core.tools.web_research.get_academic_sources",
                        _fake_sources(dummy=DummySource()))
    tool = WebResearchTool()
    code, out, err, evidence = tool("test query", mode="academic")
    assert code == 0
    payload = json.loads(evidence)
    assert payload["search"]["provider"] == "academic"
    assert payload["sources"][0]["source"] == "dummy"
    assert "Paper A" in out


def test_the_pack_records_which_indexes_answered(monkeypatch):
    """A search that reached one of three indexes is not a search of three.

    Reported rather than inferred from the count: two indexes returning
    the same paper and one index returning it alone look identical in
    `sources` and are different facts about the search.
    """
    monkeypatch.setattr("core.tools.web_research.get_academic_sources",
                        _fake_sources(dummy=DummySource(),
                                      empty=EmptySource()))
    payload = json.loads(WebResearchTool()("q", mode="academic")[3])
    assert payload["search"]["sources_reached"] == ["dummy"]


def test_no_records_anywhere_is_not_a_finding_about_the_field(monkeypatch):
    monkeypatch.setattr("core.tools.web_research.get_academic_sources",
                        _fake_sources(empty=EmptySource()))
    code, _out, _err, evidence = WebResearchTool()("q", mode="academic")
    payload = json.loads(evidence)
    assert code == 1
    assert payload["error"] == "no_results"
    assert "not a finding about the field" in payload["message"]


def test_an_openalex_record_with_no_located_source_does_not_crash():
    """The bug this catches took a whole search down for one paper.

    OpenAlex sends `primary_location: null` for a work it cannot place,
    and `item.get("primary_location", {})` returns that null rather than
    the default — so the next `.get` raised AttributeError and every
    result after it was lost.
    """
    from core.tools.research_sources import OpenAlexSource

    class _Response:
        @staticmethod
        def json():
            return {"results": [{"title": "Unlocated",
                                 "id": "https://openalex.org/W1",
                                 "primary_location": None,
                                 "authorships": [],
                                 "publication_year": 2024}]}

    source = OpenAlexSource()
    import core.tools.research_sources as module
    original = module._get
    module._get = lambda *a, **k: _Response()
    try:
        results = source.search("anything")
    finally:
        module._get = original
    assert results[0]["url"] == "https://openalex.org/W1"
