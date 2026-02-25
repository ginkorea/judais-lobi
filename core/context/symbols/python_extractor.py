# core/context/symbols/python_extractor.py — AST-based Python symbol extractor

import ast
from typing import List

from core.context.models import FileSymbols, ImportEdge, SymbolDef


def _format_annotation(node: ast.expr) -> str:
    """Format an annotation AST node to string."""
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _format_args(args: ast.arguments) -> str:
    """Format function arguments to a signature string."""
    parts: List[str] = []

    # Positional-only args (before /)
    all_pos = args.posonlyargs + args.args
    # Defaults: right-aligned to all_pos
    defaults = args.defaults
    n_defaults = len(defaults)
    n_all = len(all_pos)

    for i, arg in enumerate(all_pos):
        s = arg.arg
        if arg.annotation:
            s += f": {_format_annotation(arg.annotation)}"
        # Check if this arg has a default
        default_idx = i - (n_all - n_defaults)
        if default_idx >= 0:
            try:
                s += f" = {ast.unparse(defaults[default_idx])}"
            except Exception:
                s += " = ..."
        parts.append(s)

    # Insert / separator for positional-only
    if args.posonlyargs:
        parts.insert(len(args.posonlyargs), "/")

    # *args
    if args.vararg:
        s = f"*{args.vararg.arg}"
        if args.vararg.annotation:
            s += f": {_format_annotation(args.vararg.annotation)}"
        parts.append(s)
    elif args.kwonlyargs:
        parts.append("*")

    # Keyword-only args
    kw_defaults = args.kw_defaults
    for i, arg in enumerate(args.kwonlyargs):
        s = arg.arg
        if arg.annotation:
            s += f": {_format_annotation(arg.annotation)}"
        if kw_defaults[i] is not None:
            try:
                s += f" = {ast.unparse(kw_defaults[i])}"
            except Exception:
                s += " = ..."
        parts.append(s)

    # **kwargs
    if args.kwarg:
        s = f"**{args.kwarg.arg}"
        if args.kwarg.annotation:
            s += f": {_format_annotation(args.kwarg.annotation)}"
        parts.append(s)

    return ", ".join(parts)


def _get_decorators(node) -> List[str]:
    """Extract decorator names from a class or function definition."""
    decorators = []
    for dec in node.decorator_list:
        try:
            decorators.append(ast.unparse(dec))
        except Exception:
            decorators.append("?")
    return decorators


class PythonExtractor:
    """Extracts symbols and imports from Python source using the ast module."""

    def extract(self, source: str, rel_path: str) -> FileSymbols:
        """Parse source and extract symbols + imports."""
        try:
            tree = ast.parse(source, filename=rel_path)
        except SyntaxError:
            return FileSymbols(rel_path=rel_path, language="python")

        symbols: List[SymbolDef] = []
        imports: List[ImportEdge] = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                self._extract_class(node, symbols)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._extract_function(node, symbols)
            elif isinstance(node, ast.Import):
                self._extract_import(node, imports)
            elif isinstance(node, ast.ImportFrom):
                self._extract_import_from(node, imports)
            elif isinstance(node, ast.Assign):
                self._extract_constant(node, symbols)

        return FileSymbols(
            rel_path=rel_path,
            language="python",
            symbols=symbols,
            imports=imports,
        )

    def _extract_class(self, node: ast.ClassDef, symbols: List[SymbolDef]) -> None:
        """Extract class definition and its methods."""
        bases = []
        for base in node.bases:
            try:
                bases.append(ast.unparse(base))
            except Exception:
                bases.append("?")
        base_str = f"({', '.join(bases)})" if bases else ""
        sig = f"class {node.name}{base_str}"
        symbols.append(SymbolDef(
            name=node.name,
            kind="class",
            signature=sig,
            decorators=_get_decorators(node),
            line=node.lineno,
        ))
        # Extract methods
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._extract_function(child, symbols, parent=node.name)

    def _extract_function(
        self,
        node,
        symbols: List[SymbolDef],
        parent: str = "",
    ) -> None:
        """Extract function/method definition."""
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        args_str = _format_args(node.args)
        ret = f" -> {_format_annotation(node.returns)}" if node.returns else ""
        sig = f"{prefix} {node.name}({args_str}){ret}"

        kind = "method" if parent else "function"
        symbols.append(SymbolDef(
            name=node.name,
            kind=kind,
            signature=sig,
            parent=parent,
            decorators=_get_decorators(node),
            line=node.lineno,
        ))

    def _extract_import(self, node: ast.Import, imports: List[ImportEdge]) -> None:
        """Extract 'import X' statements."""
        for alias in node.names:
            imports.append(ImportEdge(module=alias.name))

    def _extract_import_from(self, node: ast.ImportFrom, imports: List[ImportEdge]) -> None:
        """Extract 'from X import Y' statements."""
        module = node.module or ""
        names = [alias.name for alias in (node.names or [])]
        imports.append(ImportEdge(
            module=module,
            names=names,
            is_relative=bool(node.level and node.level > 0),
        ))

    def _extract_constant(self, node: ast.Assign, symbols: List[SymbolDef]) -> None:
        """Extract top-level UPPER_CASE constants."""
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id.isupper():
                symbols.append(SymbolDef(
                    name=target.id,
                    kind="constant",
                    line=node.lineno,
                ))
