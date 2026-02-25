# core/context/cache.py — Git-commit-keyed persistent cache for RepoMapData

import json
from pathlib import Path
from typing import Callable, Dict, List, Optional

from core.context.models import FileSymbols, ImportEdge, RepoMapData, SymbolDef
from core.tools.executor import run_subprocess


def get_commit_hash(
    repo_path: str,
    subprocess_runner: Optional[Callable] = None,
) -> Optional[str]:
    """Get the current HEAD commit hash. Returns None if not a git repo."""
    cmd = f"cd {_quote(repo_path)} && git rev-parse HEAD"
    rc, stdout, stderr = run_subprocess(
        cmd, shell=True, timeout=10,
        subprocess_runner=subprocess_runner,
    )
    if rc != 0:
        return None
    return stdout.strip()


def get_dirty_files(
    repo_path: str,
    subprocess_runner: Optional[Callable] = None,
) -> List[str]:
    """Get list of modified/untracked files (relative paths)."""
    cmd = f"cd {_quote(repo_path)} && git status --porcelain"
    rc, stdout, stderr = run_subprocess(
        cmd, shell=True, timeout=10,
        subprocess_runner=subprocess_runner,
    )
    if rc != 0:
        return []
    result = []
    for line in stdout.splitlines():
        if not line or len(line) < 4:
            continue
        # Git porcelain format: "XY <path>" — first 2 chars are status, then space, then path
        path = line[3:]
        # Handle renames: "old -> new"
        if " -> " in path:
            path = path.split(" -> ")[-1]
        path = path.strip()
        if path:
            result.append(path)
    return result


class RepoMapCache:
    """Persistent cache for RepoMapData, keyed by git commit hash.

    Cache directory: <repo_root>/.judais-lobi/cache/repo_map/
    """

    def __init__(self, repo_root: str) -> None:
        self._cache_dir = Path(repo_root) / ".judais-lobi" / "cache" / "repo_map"

    def load(self, commit_hash: str) -> Optional[RepoMapData]:
        """Load cached RepoMapData for a commit. Returns None if not found."""
        path = self._cache_dir / f"{commit_hash}.json"
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return self._deserialize(raw)
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def save(self, commit_hash: str, data: RepoMapData) -> Path:
        """Save RepoMapData to cache. Returns the cache file path."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._cache_dir / f"{commit_hash}.json"
        raw = self._serialize(data)
        path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        return path

    def _serialize(self, data: RepoMapData) -> dict:
        """Convert RepoMapData to a JSON-serializable dict."""
        files = {}
        for rel_path, fs in data.files.items():
            files[rel_path] = {
                "rel_path": fs.rel_path,
                "language": fs.language,
                "symbols": [
                    {
                        "name": s.name,
                        "kind": s.kind,
                        "signature": s.signature,
                        "parent": s.parent,
                        "decorators": s.decorators,
                        "line": s.line,
                    }
                    for s in fs.symbols
                ],
                "imports": [
                    {
                        "module": i.module,
                        "names": i.names,
                        "is_relative": i.is_relative,
                    }
                    for i in fs.imports
                ],
            }
        return {
            "repo_root": data.repo_root,
            "commit_hash": data.commit_hash,
            "files": files,
        }

    def _deserialize(self, raw: dict) -> RepoMapData:
        """Convert a JSON dict back to RepoMapData."""
        files: Dict[str, FileSymbols] = {}
        for rel_path, fs_raw in raw["files"].items():
            symbols = [
                SymbolDef(
                    name=s["name"],
                    kind=s["kind"],
                    signature=s.get("signature", ""),
                    parent=s.get("parent", ""),
                    decorators=s.get("decorators", []),
                    line=s.get("line", 0),
                )
                for s in fs_raw["symbols"]
            ]
            imports = [
                ImportEdge(
                    module=i["module"],
                    names=i.get("names", []),
                    is_relative=i.get("is_relative", False),
                )
                for i in fs_raw["imports"]
            ]
            files[rel_path] = FileSymbols(
                rel_path=fs_raw["rel_path"],
                language=fs_raw.get("language", ""),
                symbols=symbols,
                imports=imports,
            )
        return RepoMapData(
            repo_root=raw["repo_root"],
            files=files,
            commit_hash=raw.get("commit_hash", ""),
        )


def _quote(s: str) -> str:
    import shlex
    return shlex.quote(s)
