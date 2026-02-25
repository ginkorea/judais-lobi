# core/context/symbols/treesitter_extractor.py — tree-sitter multi-language extractor

"""Optional tree-sitter-based symbol extractor for non-Python languages.

Requires: pip install judais-lobi[treesitter]
    - tree-sitter>=0.21.0
    - tree-sitter-languages>=1.10.0

Falls back to GenericExtractor when tree-sitter is not installed.
"""

from typing import Dict, List, Optional, Set

from core.context.models import FileSymbols, ImportEdge, SymbolDef


# Language name → tree-sitter-languages grammar name
_GRAMMAR_MAP: Dict[str, str] = {
    "c": "c",
    "cpp": "cpp",
    "rust": "rust",
    "go": "go",
    "javascript": "javascript",
    "typescript": "typescript",
    "java": "java",
    "ruby": "ruby",
    "python": "python",
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


class TreeSitterExtractor:
    """Multi-language symbol extractor using tree-sitter.

    Raises ImportError during __init__ if tree-sitter is not installed.
    Raises ValueError if the language has no grammar available.
    """

    def __init__(self, language: str) -> None:
        # Lazy import — fail early if not installed
        try:
            import tree_sitter_languages
        except ImportError:
            raise ImportError(
                "tree-sitter is not installed. Install with: pip install judais-lobi[treesitter]"
            )

        self._language = language
        grammar_name = _GRAMMAR_MAP.get(language)
        if grammar_name is None:
            raise ValueError(f"No tree-sitter grammar available for language: {language}")

        try:
            self._parser = tree_sitter_languages.get_parser(grammar_name)
        except Exception as e:
            raise ValueError(f"Failed to load tree-sitter grammar for {grammar_name}: {e}")

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
        # Look for name/identifier child
        for child in node.children:
            if child.type in ("identifier", "name", "type_identifier", "field_identifier"):
                return source[child.start_byte:child.end_byte].decode("utf-8")
            # For Go type declarations, dig into type_spec
            if child.type == "type_spec":
                return self._extract_name(child, source)
        # For impl blocks in Rust, look for the type
        if node.type == "impl_item":
            for child in node.children:
                if child.type == "type_identifier":
                    return source[child.start_byte:child.end_byte].decode("utf-8")
        return ""

    def _extract_signature(self, node, source: bytes) -> str:
        """Extract the signature (declaration without body)."""
        # Find the body/block node — signature is everything before it
        body_types = {
            "block", "compound_statement", "declaration_list",
            "field_declaration_list", "class_body", "function_body",
            "statement_block", "body",
        }
        for child in node.children:
            if child.type in body_types or child.type.endswith("_body"):
                sig_text = source[node.start_byte:child.start_byte].decode("utf-8").strip()
                # Collapse whitespace
                return " ".join(sig_text.split())

        # No body found — use the full text up to a limit
        text = source[node.start_byte:node.end_byte].decode("utf-8")
        first_line = text.split("\n")[0].strip()
        return first_line[:200]

    def _extract_import(self, node, source: bytes) -> Optional[ImportEdge]:
        """Extract an import from an AST node."""
        text = source[node.start_byte:node.end_byte].decode("utf-8").strip()

        if self._language in ("c", "cpp"):
            # #include "path.h" or #include <path.h>
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
        """Parse #include directive."""
        import re
        match = re.match(r'#include\s+[<"]([^>"]+)[>"]', text)
        if match:
            return ImportEdge(module=match.group(1))
        return None

    def _parse_rust_use(self, text: str) -> Optional[ImportEdge]:
        """Parse use declaration."""
        import re
        match = re.match(r'use\s+([\w:]+)', text)
        if match:
            module = match.group(1)
            return ImportEdge(module=module)
        return None

    def _parse_go_import(self, node, source: bytes) -> Optional[ImportEdge]:
        """Parse Go import (single or group)."""
        text = source[node.start_byte:node.end_byte].decode("utf-8").strip()
        import re
        # Single: import "path"
        match = re.match(r'import\s+"([^"]+)"', text)
        if match:
            return ImportEdge(module=match.group(1))
        # Group: import ( "path1" "path2" ) — extract first
        matches = re.findall(r'"([^"]+)"', text)
        if matches:
            return ImportEdge(module=matches[0], names=matches[1:] if len(matches) > 1 else [])
        return None

    def _parse_js_import(self, text: str) -> Optional[ImportEdge]:
        """Parse JS/TS import statement."""
        import re
        match = re.search(r"""from\s+['"]([^'"]+)['"]""", text)
        if match:
            module = match.group(1)
            # Extract imported names
            names_match = re.match(r'import\s+\{([^}]+)\}', text)
            names = []
            if names_match:
                names = [n.strip() for n in names_match.group(1).split(",")]
            return ImportEdge(module=module, names=names)
        # import "module"
        match = re.search(r"""import\s+['"]([^'"]+)['"]""", text)
        if match:
            return ImportEdge(module=match.group(1))
        return None

    def _parse_java_import(self, text: str) -> Optional[ImportEdge]:
        """Parse Java import."""
        import re
        match = re.match(r'import\s+(?:static\s+)?([\w.]+)', text)
        if match:
            return ImportEdge(module=match.group(1))
        return None
