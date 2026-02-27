# tests/test_web_research_tool.py

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


def test_academic_mode_with_stub_sources(monkeypatch):
    def _fake_sources():
        return {"dummy": DummySource()}

    monkeypatch.setattr("core.tools.web_research.get_academic_sources", _fake_sources)
    tool = WebResearchTool()
    raw = tool("test query", mode="academic", return_format="json")
    payload = json.loads(raw)
    assert payload["source"] == "academic"
    assert payload["results"][0]["source"] == "dummy"

