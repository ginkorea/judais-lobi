# core/context/symbols/treesitter_extractor.py — tree-sitter multi-language extractor

"""Optional tree-sitter-based symbol extractor for non-Python languages.

Requires: pip install judais-lobi[treesitter]
    - tree-sitter>=0.23.0
    - tree-sitter-c, tree-sitter-cpp, tree-sitter-rust, tree-sitter-go,
      tree-sitter-javascript, tree-sitter-typescript, tree-sitter-java

Uses individual grammar packages (modern API). Falls back to GenericExtractor
when tree-sitter is not installed.
"""

import re
from typing import Dict, List, Optional, Set

from core.context.models import FileSymbols, ImportEdge, SymbolDef


# Language name → (grammar_package, grammar_attr)
# Each grammar package exposes a language() function returning the raw language pointer.
_GRAMMAR_PACKAGES: Dict[str, str] = {
    "c": "tree_sitter_c",
    "cpp": "tree_sitter_cpp",
    "rust": "tree_sitter_rust",
    "go": "tree_sitter_go",
    "javascript": "tree_sitter_javascript",
    "typescript": "tree_sitter_typescript",
    "java": "tree_sitter_java",
}

# Node types to extract per language, mapped to symbol kinds
_SYMBOL_QUERIES: Dict[str, Dict[str, str]] = {
    "c": {
        "function_definition": "function",
        "struct_specifier": "class",
        "enum_specifier": "class",
        "type_definition": "class",
    },
    "cpp": {
        "function_definition": "function",
        "class_specifier": "class",
        "struct_specifier": "class",
        "namespace_definition": "class",
        "enum_specifier": "class",
    },
    "rust": {
        "function_item": "function",
        "struct_item": "class",
        "trait_item": "class",
        "impl_item": "class",
        "enum_item": "class",
    },
    "go": {
        "function_declaration": "function",
        "method_declaration": "method",
        "type_declaration": "class",
    },
    "javascript": {
        "function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
    },
    "typescript": {
        "function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
        "interface_declaration": "class",
    },
    "java": {
        "class_declaration": "class",
        "method_declaration": "method",
        "interface_declaration": "class",
    },
}

# Node types for import extraction per language
_IMPORT_QUERIES: Dict[str, Set[str]] = {
    "c": {"preproc_include"},
    "cpp": {"preproc_include"},
    "rust": {"use_declaration"},
    "go": {"import_declaration"},
    "javascript": {"import_statement"},
    "typescript": {"import_statement"},
    "java": {"import_declaration"},
}


def _load_parser(language: str):
    """Load a tree-sitter parser for the given language.

    Uses the modern API: individual grammar packages (tree-sitter-c, etc.)
    with tree_sitter.Language() and tree_sitter.Parser().

    Raises ImportError if tree-sitter core is not installed.
    Raises ValueError if the language grammar package is not available.
    """
    try:
        import tree_sitter
    except ImportError:
        raise ImportError(
            "tree-sitter is not installed. Install with: pip install judais-lobi[treesitter]"
        )

    pkg_name = _GRAMMAR_PACKAGES.get(language)
    if pkg_name is None:
        raise ValueError(f"No tree-sitter grammar available for language: {language}")

    try:
        import importlib
        grammar_mod = importlib.import_module(pkg_name)
    except ImportError:
        raise ValueError(
            f"Grammar package '{pkg_name}' not installed. "
            f"Install with: pip install {pkg_name.replace('_', '-')}"
        )

    # Modern API: grammar_mod.language() returns a capsule,
    # wrap it in tree_sitter.Language, then create Parser with it.
    # Handle both typescript (which may have language_typescript()) and others.
    lang_func = getattr(grammar_mod, "language", None)

    # tree-sitter-typescript exposes language_typescript and language_tsx
    if lang_func is None and language == "typescript":
        lang_func = getattr(grammar_mod, "language_typescript", None)

    if lang_func is None:
        raise ValueError(f"Grammar package '{pkg_name}' has no language() function")

    ts_language = tree_sitter.Language(lang_func())
    parser = tree_sitter.Parser(ts_language)
    return parser


class TreeSitterExtractor:
    """Multi-language symbol extractor using tree-sitter.

    Raises ImportError during __init__ if tree-sitter is not installed.
    Raises ValueError if the language has no grammar available.
    """

    def __init__(self, language: str) -> None:
        self._language = language
        self._parser = _load_parser(language)
        self._symbol_types = _SYMBOL_QUERIES.get(language, {})
        self._import_types = _IMPORT_QUERIES.get(language, set())

    def extract(self, source: str, rel_path: str) -> FileSymbols:
        """Parse source and extract symbols + imports."""
        source_bytes = source.encode("utf-8")
        tree = self._parser.parse(source_bytes)
        root = tree.root_node

        symbols: List[SymbolDef] = []
        imports: List[ImportEdge] = []

        self._walk(root, source_bytes, symbols, imports)

        return FileSymbols(
            rel_path=rel_path,
            language=self._language,
            symbols=symbols,
            imports=imports,
        )

    def _walk(
        self,
        node,
        source: bytes,
        symbols: List[SymbolDef],
        imports: List[ImportEdge],
        parent_name: str = "",
    ) -> None:
        """Recursively walk the AST tree."""
        node_type = node.type

        # Check for symbol definitions
        if node_type in self._symbol_types:
            kind = self._symbol_types[node_type]
            name = self._extract_name(node, source)
            if name:
                sig = self._extract_signature(node, source)
                sym = SymbolDef(
                    name=name,
                    kind=kind,
                    signature=sig,
                    parent=parent_name,
                    line=node.start_point[0] + 1,
                )
                symbols.append(sym)
                # Recurse into class/struct bodies for methods
                if kind == "class":
                    for child in node.children:
                        self._walk(child, source, symbols, imports, parent_name=name)
                    return

        # Check for imports
        if node_type in self._import_types:
            imp = self._extract_import(node, source)
            if imp:
                imports.append(imp)

        # Recurse
        for child in node.children:
            self._walk(child, source, symbols, imports, parent_name=parent_name)

    def _extract_name(self, node, source: bytes) -> str:
        """Extract the name of a symbol from its AST node."""
        # Direct name children
        for child in node.children:
            if child.type in ("identifier", "name", "type_identifier",
                              "field_identifier", "namespace_identifier"):
                return source[child.start_byte:child.end_byte].decode("utf-8")
            # Go type_spec wraps the identifier
            if child.type == "type_spec":
                return self._extract_name(child, source)
            # C/C++: function_declarator wraps the identifier
            if child.type in ("function_declarator", "declarator",
                              "pointer_declarator", "reference_declarator"):
                name = self._extract_name(child, source)
                if name:
                    return name
        # Rust impl blocks
        if node.type == "impl_item":
            for child in node.children:
                if child.type == "type_identifier":
                    return source[child.start_byte:child.end_byte].decode("utf-8")
        return ""

    def _extract_signature(self, node, source: bytes) -> str:
        """Extract the signature (declaration without body)."""
        body_types = {
            "block", "compound_statement", "declaration_list",
            "field_declaration_list", "class_body", "function_body",
            "statement_block", "body",
        }
        for child in node.children:
            if child.type in body_types or child.type.endswith("_body"):
                sig_text = source[node.start_byte:child.start_byte].decode("utf-8").strip()
                return " ".join(sig_text.split())

        text = source[node.start_byte:node.end_byte].decode("utf-8")
        first_line = text.split("\n")[0].strip()
        return first_line[:200]

    def _extract_import(self, node, source: bytes) -> Optional[ImportEdge]:
        """Extract an import from an AST node."""
        text = source[node.start_byte:node.end_byte].decode("utf-8").strip()

        if self._language in ("c", "cpp"):
            return self._parse_c_include(text)
        elif self._language == "rust":
            return self._parse_rust_use(text)
        elif self._language == "go":
            return self._parse_go_import(node, source)
        elif self._language in ("javascript", "typescript"):
            return self._parse_js_import(text)
        elif self._language == "java":
            return self._parse_java_import(text)
        return None

    def _parse_c_include(self, text: str) -> Optional[ImportEdge]:
        match = re.match(r'#include\s+[<"]([^>"]+)[>"]', text)
        if match:
            return ImportEdge(module=match.group(1))
        return None

    def _parse_rust_use(self, text: str) -> Optional[ImportEdge]:
        match = re.match(r'use\s+([\w:]+)', text)
        if match:
            return ImportEdge(module=match.group(1))
        return None

    def _parse_go_import(self, node, source: bytes) -> Optional[ImportEdge]:
        text = source[node.start_byte:node.end_byte].decode("utf-8").strip()
        match = re.match(r'import\s+"([^"]+)"', text)
        if match:
            return ImportEdge(module=match.group(1))
        matches = re.findall(r'"([^"]+)"', text)
        if matches:
            return ImportEdge(module=matches[0], names=matches[1:] if len(matches) > 1 else [])
        return None

    def _parse_js_import(self, text: str) -> Optional[ImportEdge]:
        match = re.search(r"""from\s+['"]([^'"]+)['"]""", text)
        if match:
            module = match.group(1)
            names_match = re.match(r'import\s+\{([^}]+)\}', text)
            names = []
            if names_match:
                names = [n.strip() for n in names_match.group(1).split(",")]
            return ImportEdge(module=module, names=names)
        match = re.search(r"""import\s+['"]([^'"]+)['"]""", text)
        if match:
            return ImportEdge(module=match.group(1))
        return None

    def _parse_java_import(self, text: str) -> Optional[ImportEdge]:
        match = re.match(r'import\s+(?:static\s+)?([\w.]+)', text)
        if match:
            return ImportEdge(module=match.group(1))
        return None
