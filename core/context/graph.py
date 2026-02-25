# core/context/graph.py — Dependency graph and relevance ranking

from collections import defaultdict, deque
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from core.context.models import RepoMapData


class DependencyGraph:
    """Import-based dependency graph for relevance ranking.

    Built from RepoMapData. Nodes are relative file paths.
    Edges represent import relationships (A imports B → edge A→B).
    Third-party imports (unresolvable to file paths) are silently ignored.
    """

    def __init__(self, data: RepoMapData) -> None:
        self._known_files: Set[str] = set(data.files.keys())
        # Forward edges: file → set of files it imports
        self._deps: Dict[str, Set[str]] = defaultdict(set)
        # Reverse edges: file → set of files that import it
        self._rdeps: Dict[str, Set[str]] = defaultdict(set)
        self._build(data)

    def _build(self, data: RepoMapData) -> None:
        """Build adjacency lists from import edges."""
        for rel_path, fs in data.files.items():
            lang = fs.language
            for imp in fs.imports:
                resolved = self._resolve_module_to_file(
                    imp.module, language=lang, source_file=rel_path,
                )
                if resolved and resolved != rel_path:
                    self._deps[rel_path].add(resolved)
                    self._rdeps[resolved].add(rel_path)

    def _resolve_module_to_file(
        self,
        module: str,
        language: str = "",
        source_file: str = "",
    ) -> Optional[str]:
        """Convert a module/import path to a relative file path.

        Supports multi-language resolution:
        - Python: 'core.kernel.state' → 'core/kernel/state.py'
        - C/C++: 'path/header.h' → direct match
        - Rust: 'crate::module::item' → 'src/module.rs' or 'src/module/mod.rs'
        - Go: 'package/name' → directory match
        - JS/TS: './path' → 'path.js' / 'path.ts' / 'path/index.js' etc.

        Returns None if not resolvable to a known file.
        """
        if not module:
            return None

        # C/C++ includes: direct path match
        if language in ("c", "cpp"):
            return self._resolve_c_include(module)

        # Rust: crate::module::item → src/module.rs
        if language == "rust":
            return self._resolve_rust_use(module)

        # Go: package path → directory match
        if language == "go":
            return self._resolve_go_import(module)

        # JS/TS: relative paths with extension guessing
        if language in ("javascript", "typescript"):
            return self._resolve_js_import(module, source_file)

        # Python (default): dotted module path
        return self._resolve_python_module(module)

    def _resolve_python_module(self, module: str) -> Optional[str]:
        """Resolve a Python module to a file path."""
        path = module.replace(".", "/") + ".py"
        if path in self._known_files:
            return path
        init_path = module.replace(".", "/") + "/__init__.py"
        if init_path in self._known_files:
            return init_path
        return None

    def _resolve_c_include(self, module: str) -> Optional[str]:
        """Resolve C/C++ #include paths."""
        # Direct match
        if module in self._known_files:
            return module
        # Try common prefix patterns
        for prefix in ("include/", "src/", ""):
            candidate = prefix + module
            if candidate in self._known_files:
                return candidate
        return None

    def _resolve_rust_use(self, module: str) -> Optional[str]:
        """Resolve Rust 'use' declarations.

        'crate::module::item' → 'src/module.rs' or 'src/module/mod.rs'
        'std::...' → None (external)
        """
        # Strip 'crate::' prefix
        if module.startswith("crate::"):
            module = module[len("crate::"):]
        elif "::" in module and not module.startswith("self::") and not module.startswith("super::"):
            # External crate — unresolvable
            return None

        if module.startswith("self::"):
            module = module[len("self::"):]
        if module.startswith("super::"):
            module = module[len("super::"):]

        parts = module.split("::")
        # Try src/part1/part2.rs
        path = "src/" + "/".join(parts) + ".rs"
        if path in self._known_files:
            return path
        # Try src/part1/part2/mod.rs
        mod_path = "src/" + "/".join(parts) + "/mod.rs"
        if mod_path in self._known_files:
            return mod_path
        # Try without src/ prefix
        path_nosrc = "/".join(parts) + ".rs"
        if path_nosrc in self._known_files:
            return path_nosrc
        return None

    def _resolve_go_import(self, module: str) -> Optional[str]:
        """Resolve Go import paths to directories.

        Go imports are package paths. Match any .go file in a matching directory.
        """
        # Standard library — unresolvable
        if not "/" in module and not module.startswith("."):
            return None
        # Try finding any .go file in a directory matching the last component
        parts = module.rstrip("/").split("/")
        pkg_name = parts[-1]
        for f in self._known_files:
            if f.endswith(".go") and f.rsplit("/", 1)[0].endswith(pkg_name):
                return f
        return None

    def _resolve_js_import(self, module: str, source_file: str = "") -> Optional[str]:
        """Resolve JS/TS import paths with extension guessing.

        './foo' → 'foo.js', 'foo.ts', 'foo.tsx', 'foo/index.js', etc.
        Resolution is relative to the importing file's directory.
        """
        # Non-relative imports are typically node_modules — skip
        if not module.startswith(".") and not module.startswith("/"):
            return None

        # Resolve relative to source file directory
        import posixpath
        if source_file:
            src_dir = posixpath.dirname(source_file)
            clean = posixpath.normpath(posixpath.join(src_dir, module))
        else:
            clean = module.lstrip("./")

        # Direct match
        if clean in self._known_files:
            return clean

        # Try common extensions
        for ext in (".js", ".ts", ".tsx", ".jsx"):
            candidate = clean + ext
            if candidate in self._known_files:
                return candidate

        # Try index files
        for ext in ("/index.js", "/index.ts", "/index.tsx"):
            candidate = clean + ext
            if candidate in self._known_files:
                return candidate

        return None

    @property
    def files(self) -> FrozenSet[str]:
        """All known files in the graph."""
        return frozenset(self._known_files)

    @property
    def edges(self) -> List[Tuple[str, str]]:
        """All directed edges (source, target) where source imports target."""
        result = []
        for src, targets in sorted(self._deps.items()):
            for tgt in sorted(targets):
                result.append((src, tgt))
        return result

    def dependencies_of(self, file: str) -> Set[str]:
        """Files that the given file imports (direct forward dependencies)."""
        return set(self._deps.get(file, set()))

    def dependents_of(self, file: str) -> Set[str]:
        """Files that import the given file (direct reverse dependencies)."""
        return set(self._rdeps.get(file, set()))

    def dependency_closure(
        self,
        files: List[str],
        max_depth: int = 2,
    ) -> Set[str]:
        """BFS outward from files up to max_depth hops (both directions)."""
        visited: Set[str] = set()
        queue: deque = deque()

        for f in files:
            if f in self._known_files:
                queue.append((f, 0))
                visited.add(f)

        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            # Expand in both directions
            neighbors = self._deps.get(current, set()) | self._rdeps.get(current, set())
            for neighbor in neighbors:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))

        return visited

    def rank_by_relevance(
        self,
        target_files: List[str],
        max_depth: int = 2,
    ) -> List[Tuple[str, float]]:
        """Rank all files by relevance to target_files.

        Scoring:
        - Target file itself: 1.0
        - Direct dependency (target imports it): 0.8
        - Direct dependent (imports the target): 0.6
        - 2-hop neighbor: 0.4
        - All other files: 0.1
        """
        scores: Dict[str, float] = {f: 0.1 for f in self._known_files}
        target_set = set(target_files) & self._known_files

        # Score targets
        for f in target_set:
            scores[f] = 1.0

        # Score direct dependencies and dependents
        for f in target_set:
            for dep in self._deps.get(f, set()):
                scores[dep] = max(scores.get(dep, 0.1), 0.8)
            for rdep in self._rdeps.get(f, set()):
                scores[rdep] = max(scores.get(rdep, 0.1), 0.6)

        # Score 2-hop neighbors
        if max_depth >= 2:
            hop1 = set()
            for f in target_set:
                hop1 |= self._deps.get(f, set())
                hop1 |= self._rdeps.get(f, set())
            hop1 -= target_set

            for f in hop1:
                neighbors = self._deps.get(f, set()) | self._rdeps.get(f, set())
                for n in neighbors:
                    if n not in target_set and n not in hop1:
                        scores[n] = max(scores.get(n, 0.1), 0.4)

        ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
        return ranked

    def rank_by_centrality(self) -> List[Tuple[str, float]]:
        """Rank files by graph centrality (in-degree + out-degree).

        Used for overview mode (no target files).
        """
        scores: Dict[str, float] = {}
        for f in self._known_files:
            in_deg = len(self._rdeps.get(f, set()))
            out_deg = len(self._deps.get(f, set()))
            scores[f] = float(in_deg + out_deg)
        # Normalize
        max_score = max(scores.values()) if scores else 1.0
        if max_score > 0:
            scores = {f: s / max_score for f, s in scores.items()}
        ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
        return ranked
