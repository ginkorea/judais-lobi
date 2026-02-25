# tests/test_python_extractor.py — Tests for AST-based Python symbol extraction

import pytest

from core.context.symbols.python_extractor import PythonExtractor
from core.context.symbols.base import SymbolExtractor


@pytest.fixture
def extractor():
    return PythonExtractor()


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------

class TestProtocol:
    def test_implements_symbol_extractor(self):
        assert isinstance(PythonExtractor(), SymbolExtractor)


# ---------------------------------------------------------------------------
# Function extraction
# ---------------------------------------------------------------------------

class TestFunctions:
    def test_simple_function(self, extractor):
        src = "def hello():\n    pass\n"
        fs = extractor.extract(src, "hello.py")
        assert len(fs.symbols) == 1
        assert fs.symbols[0].name == "hello"
        assert fs.symbols[0].kind == "function"

    def test_function_with_annotations(self, extractor):
        src = "def add(x: int, y: int) -> int:\n    return x + y\n"
        fs = extractor.extract(src, "math.py")
        sym = fs.symbols[0]
        assert "x: int" in sym.signature
        assert "y: int" in sym.signature
        assert "-> int" in sym.signature

    def test_async_function(self, extractor):
        src = "async def fetch(url: str) -> bytes:\n    pass\n"
        fs = extractor.extract(src, "net.py")
        sym = fs.symbols[0]
        assert sym.signature.startswith("async def")
        assert sym.kind == "function"

    def test_function_with_defaults(self, extractor):
        src = 'def greet(name: str = "world") -> str:\n    pass\n'
        fs = extractor.extract(src, "greet.py")
        assert "= " in fs.symbols[0].signature

    def test_function_with_decorators(self, extractor):
        src = "@staticmethod\ndef helper():\n    pass\n"
        fs = extractor.extract(src, "util.py")
        assert fs.symbols[0].decorators == ["staticmethod"]

    def test_function_with_star_args(self, extractor):
        src = "def f(*args, **kwargs):\n    pass\n"
        fs = extractor.extract(src, "f.py")
        assert "*args" in fs.symbols[0].signature
        assert "**kwargs" in fs.symbols[0].signature

    def test_function_with_kwonly(self, extractor):
        src = "def f(a, *, b=1):\n    pass\n"
        fs = extractor.extract(src, "f.py")
        sig = fs.symbols[0].signature
        assert "a" in sig
        assert "b" in sig


# ---------------------------------------------------------------------------
# Class extraction
# ---------------------------------------------------------------------------

class TestClasses:
    def test_simple_class(self, extractor):
        src = "class Foo:\n    pass\n"
        fs = extractor.extract(src, "foo.py")
        sym = fs.symbols[0]
        assert sym.name == "Foo"
        assert sym.kind == "class"
        assert sym.signature == "class Foo"

    def test_class_with_bases(self, extractor):
        src = "class Foo(Bar, Baz):\n    pass\n"
        fs = extractor.extract(src, "foo.py")
        assert "Bar" in fs.symbols[0].signature
        assert "Baz" in fs.symbols[0].signature

    def test_class_with_decorators(self, extractor):
        src = "@dataclass\nclass Point:\n    x: int\n    y: int\n"
        fs = extractor.extract(src, "point.py")
        assert fs.symbols[0].decorators == ["dataclass"]

    def test_class_methods_extracted(self, extractor):
        src = (
            "class Calc:\n"
            "    def add(self, a: int, b: int) -> int:\n"
            "        return a + b\n"
            "    def sub(self, a, b):\n"
            "        return a - b\n"
        )
        fs = extractor.extract(src, "calc.py")
        names = [s.name for s in fs.symbols]
        assert "Calc" in names
        assert "add" in names
        assert "sub" in names
        add_sym = [s for s in fs.symbols if s.name == "add"][0]
        assert add_sym.kind == "method"
        assert add_sym.parent == "Calc"


# ---------------------------------------------------------------------------
# Import extraction
# ---------------------------------------------------------------------------

class TestImports:
    def test_import(self, extractor):
        src = "import os\nimport sys\n"
        fs = extractor.extract(src, "a.py")
        assert len(fs.imports) == 2
        modules = [i.module for i in fs.imports]
        assert "os" in modules
        assert "sys" in modules

    def test_from_import(self, extractor):
        src = "from os.path import join, exists\n"
        fs = extractor.extract(src, "a.py")
        assert len(fs.imports) == 1
        imp = fs.imports[0]
        assert imp.module == "os.path"
        assert "join" in imp.names
        assert "exists" in imp.names

    def test_relative_import(self, extractor):
        src = "from .sibling import helper\n"
        fs = extractor.extract(src, "a.py")
        assert fs.imports[0].is_relative is True
        assert fs.imports[0].module == "sibling"

    def test_import_star(self, extractor):
        src = "from typing import *\n"
        fs = extractor.extract(src, "a.py")
        assert "*" in fs.imports[0].names


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_upper_case_constant(self, extractor):
        src = "MAX_SIZE = 1024\nDEFAULT = 'hello'\n"
        fs = extractor.extract(src, "config.py")
        constants = [s for s in fs.symbols if s.kind == "constant"]
        names = [c.name for c in constants]
        assert "MAX_SIZE" in names
        assert "DEFAULT" in names

    def test_lowercase_not_constant(self, extractor):
        src = "my_var = 42\n"
        fs = extractor.extract(src, "a.py")
        constants = [s for s in fs.symbols if s.kind == "constant"]
        assert len(constants) == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_syntax_error_returns_empty(self, extractor):
        src = "def broken(\n"
        fs = extractor.extract(src, "bad.py")
        assert fs.symbols == []
        assert fs.imports == []
        assert fs.language == "python"

    def test_empty_file(self, extractor):
        fs = extractor.extract("", "empty.py")
        assert fs.symbols == []
        assert fs.imports == []

    def test_line_numbers(self, extractor):
        src = "# comment\n\ndef foo():\n    pass\n"
        fs = extractor.extract(src, "a.py")
        assert fs.symbols[0].line == 3

    def test_language_set(self, extractor):
        fs = extractor.extract("pass", "a.py")
        assert fs.language == "python"
