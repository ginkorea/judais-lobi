# tests/test_generic_extractor.py — Tests for regex-based fallback extractor

import pytest

from core.context.symbols.generic_extractor import GenericExtractor
from core.context.symbols.base import SymbolExtractor


@pytest.fixture
def extractor():
    return GenericExtractor()


class TestProtocol:
    def test_implements_symbol_extractor(self):
        assert isinstance(GenericExtractor(), SymbolExtractor)


class TestJavaScript:
    def test_function_declaration(self, extractor):
        src = "function greet(name) {\n  return 'hello ' + name;\n}\n"
        fs = extractor.extract(src, "app.js")
        names = [s.name for s in fs.symbols]
        assert "greet" in names

    def test_class_declaration(self, extractor):
        src = "export class Widget {\n  constructor() {}\n}\n"
        fs = extractor.extract(src, "widget.js")
        classes = [s for s in fs.symbols if s.kind == "class"]
        assert any(s.name == "Widget" for s in classes)

    def test_async_function(self, extractor):
        src = "async function fetchData() {\n  return await fetch(url);\n}\n"
        fs = extractor.extract(src, "api.js")
        assert any(s.name == "fetchData" for s in fs.symbols)


class TestGo:
    def test_func(self, extractor):
        src = "func main() {\n\tfmt.Println(\"hello\")\n}\n"
        fs = extractor.extract(src, "main.go")
        names = [s.name for s in fs.symbols]
        assert "main" in names

    def test_method(self, extractor):
        src = "func (s *Server) Start() error {\n\treturn nil\n}\n"
        fs = extractor.extract(src, "server.go")
        methods = [s for s in fs.symbols if s.kind == "method"]
        assert any(s.name == "Start" for s in methods)


class TestRust:
    def test_pub_fn(self, extractor):
        src = "pub fn process(data: &[u8]) -> Result<()> {\n    Ok(())\n}\n"
        fs = extractor.extract(src, "lib.rs")
        assert any(s.name == "process" for s in fs.symbols)

    def test_struct(self, extractor):
        src = "pub struct Config {\n    pub name: String,\n}\n"
        fs = extractor.extract(src, "config.rs")
        classes = [s for s in fs.symbols if s.kind == "class"]
        assert any(s.name == "Config" for s in classes)

    def test_trait(self, extractor):
        src = "pub trait Handler {\n    fn handle(&self);\n}\n"
        fs = extractor.extract(src, "handler.rs")
        classes = [s for s in fs.symbols if s.kind == "class"]
        assert any(s.name == "Handler" for s in classes)


class TestNoMatches:
    def test_empty_source(self, extractor):
        fs = extractor.extract("", "empty.txt")
        assert fs.symbols == []

    def test_comments_only(self, extractor):
        src = "# This is a comment\n// Another comment\n"
        fs = extractor.extract(src, "comments.py")
        # May or may not match — just shouldn't crash
        assert isinstance(fs.symbols, list)

    def test_no_imports_extracted(self, extractor):
        src = "function foo() {}\n"
        fs = extractor.extract(src, "a.js")
        assert fs.imports == []


class TestDeduplication:
    def test_no_duplicates(self, extractor):
        src = "pub fn process() {}\n"
        fs = extractor.extract(src, "lib.rs")
        names = [s.name for s in fs.symbols]
        assert names.count("process") == 1
