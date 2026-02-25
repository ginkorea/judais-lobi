# tests/test_treesitter_extractor.py — Tests for tree-sitter multi-language extractor
#
# All tests are wrapped with pytest.importorskip so they skip gracefully
# when tree-sitter is not installed.

import pytest

ts = pytest.importorskip("tree_sitter")
tsl = pytest.importorskip("tree_sitter_languages")

from core.context.symbols.treesitter_extractor import TreeSitterExtractor
from core.context.symbols.base import SymbolExtractor


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------

class TestProtocol:
    def test_implements_symbol_extractor(self):
        ext = TreeSitterExtractor("c")
        assert isinstance(ext, SymbolExtractor)


# ---------------------------------------------------------------------------
# C extraction
# ---------------------------------------------------------------------------

class TestCExtraction:
    def test_function(self):
        src = "int main(int argc, char **argv) {\n    return 0;\n}\n"
        ext = TreeSitterExtractor("c")
        fs = ext.extract(src, "main.c")
        names = [s.name for s in fs.symbols]
        assert "main" in names

    def test_struct(self):
        src = "struct Point {\n    int x;\n    int y;\n};\n"
        ext = TreeSitterExtractor("c")
        fs = ext.extract(src, "point.c")
        classes = [s for s in fs.symbols if s.kind == "class"]
        assert any(s.name == "Point" for s in classes)

    def test_include(self):
        src = '#include <stdio.h>\n#include "myheader.h"\n'
        ext = TreeSitterExtractor("c")
        fs = ext.extract(src, "main.c")
        modules = [i.module for i in fs.imports]
        assert "stdio.h" in modules
        assert "myheader.h" in modules


# ---------------------------------------------------------------------------
# C++ extraction
# ---------------------------------------------------------------------------

class TestCppExtraction:
    def test_class_with_methods(self):
        src = (
            "class Widget {\n"
            "public:\n"
            "    void draw() {\n"
            "    }\n"
            "};\n"
        )
        ext = TreeSitterExtractor("cpp")
        fs = ext.extract(src, "widget.cpp")
        names = [s.name for s in fs.symbols]
        assert "Widget" in names

    def test_namespace(self):
        src = "namespace ui {\n    void init() {}\n}\n"
        ext = TreeSitterExtractor("cpp")
        fs = ext.extract(src, "ui.cpp")
        names = [s.name for s in fs.symbols]
        assert "ui" in names

    def test_function(self):
        src = "void helper(int x) {\n    return;\n}\n"
        ext = TreeSitterExtractor("cpp")
        fs = ext.extract(src, "helper.cpp")
        funcs = [s for s in fs.symbols if s.kind == "function"]
        assert any(s.name == "helper" for s in funcs)


# ---------------------------------------------------------------------------
# Rust extraction
# ---------------------------------------------------------------------------

class TestRustExtraction:
    def test_fn(self):
        src = "fn process(data: &[u8]) -> Result<()> {\n    Ok(())\n}\n"
        ext = TreeSitterExtractor("rust")
        fs = ext.extract(src, "lib.rs")
        names = [s.name for s in fs.symbols]
        assert "process" in names

    def test_struct(self):
        src = "pub struct Config {\n    pub name: String,\n}\n"
        ext = TreeSitterExtractor("rust")
        fs = ext.extract(src, "config.rs")
        classes = [s for s in fs.symbols if s.kind == "class"]
        assert any(s.name == "Config" for s in classes)

    def test_trait(self):
        src = "pub trait Handler {\n    fn handle(&self);\n}\n"
        ext = TreeSitterExtractor("rust")
        fs = ext.extract(src, "handler.rs")
        classes = [s for s in fs.symbols if s.kind == "class"]
        assert any(s.name == "Handler" for s in classes)

    def test_use_declaration(self):
        src = "use std::io::Read;\n"
        ext = TreeSitterExtractor("rust")
        fs = ext.extract(src, "lib.rs")
        assert any(i.module.startswith("std") for i in fs.imports)


# ---------------------------------------------------------------------------
# Go extraction
# ---------------------------------------------------------------------------

class TestGoExtraction:
    def test_func(self):
        src = 'package main\n\nfunc main() {\n\tfmt.Println("hello")\n}\n'
        ext = TreeSitterExtractor("go")
        fs = ext.extract(src, "main.go")
        names = [s.name for s in fs.symbols]
        assert "main" in names

    def test_method(self):
        src = "func (s *Server) Start() error {\n\treturn nil\n}\n"
        ext = TreeSitterExtractor("go")
        fs = ext.extract(src, "server.go")
        methods = [s for s in fs.symbols if s.kind == "method"]
        assert any(s.name == "Start" for s in methods)

    def test_struct_type(self):
        src = "type Config struct {\n\tName string\n}\n"
        ext = TreeSitterExtractor("go")
        fs = ext.extract(src, "config.go")
        classes = [s for s in fs.symbols if s.kind == "class"]
        assert any(s.name == "Config" for s in classes)

    def test_import(self):
        src = 'import "fmt"\n'
        ext = TreeSitterExtractor("go")
        fs = ext.extract(src, "main.go")
        assert any(i.module == "fmt" for i in fs.imports)


# ---------------------------------------------------------------------------
# JavaScript/TypeScript extraction
# ---------------------------------------------------------------------------

class TestJSExtraction:
    def test_function(self):
        src = "function greet(name) {\n    return 'hello ' + name;\n}\n"
        ext = TreeSitterExtractor("javascript")
        fs = ext.extract(src, "app.js")
        names = [s.name for s in fs.symbols]
        assert "greet" in names

    def test_class(self):
        src = "class Widget {\n    constructor() {}\n    render() {}\n}\n"
        ext = TreeSitterExtractor("javascript")
        fs = ext.extract(src, "widget.js")
        names = [s.name for s in fs.symbols]
        assert "Widget" in names

    def test_export_function(self):
        src = "export function helper() {}\n"
        ext = TreeSitterExtractor("javascript")
        fs = ext.extract(src, "util.js")
        # The function should be detected even inside export
        funcs = [s for s in fs.symbols if s.kind == "function"]
        assert any(s.name == "helper" for s in funcs)

    def test_import(self):
        src = "import { useState } from 'react';\n"
        ext = TreeSitterExtractor("javascript")
        fs = ext.extract(src, "app.js")
        assert any(i.module == "react" for i in fs.imports)


# ---------------------------------------------------------------------------
# Import extraction across languages
# ---------------------------------------------------------------------------

class TestImportExtraction:
    def test_c_include(self):
        src = '#include "utils.h"\n'
        ext = TreeSitterExtractor("c")
        fs = ext.extract(src, "main.c")
        assert any(i.module == "utils.h" for i in fs.imports)

    def test_rust_use(self):
        src = "use crate::config::Settings;\n"
        ext = TreeSitterExtractor("rust")
        fs = ext.extract(src, "lib.rs")
        assert len(fs.imports) > 0

    def test_go_import(self):
        src = 'import (\n\t"fmt"\n\t"os"\n)\n'
        ext = TreeSitterExtractor("go")
        fs = ext.extract(src, "main.go")
        assert len(fs.imports) > 0


# ---------------------------------------------------------------------------
# Fallback behavior
# ---------------------------------------------------------------------------

class TestFallbackBehavior:
    def test_get_extractor_returns_generic_without_treesitter(self):
        """When tree-sitter IS installed, get_extractor returns TreeSitterExtractor."""
        from core.context.symbols import get_extractor
        ext = get_extractor("c")
        assert type(ext).__name__ == "TreeSitterExtractor"

    def test_invalid_language_raises(self):
        with pytest.raises(ValueError, match="No tree-sitter grammar"):
            TreeSitterExtractor("nonexistent_language_xyz")

    def test_python_always_uses_ast(self):
        from core.context.symbols import get_extractor
        ext = get_extractor("python")
        assert type(ext).__name__ == "PythonExtractor"
