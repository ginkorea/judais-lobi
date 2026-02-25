# core/context/file_discovery.py — File discovery and language classification

from pathlib import Path
from typing import Callable, List, Optional, Set, Tuple

from core.tools.executor import run_subprocess


# ---------------------------------------------------------------------------
# Language classification
# ---------------------------------------------------------------------------

LANGUAGE_MAP = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".hh": "cpp",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".lua": "lua",
    ".pl": "perl",
    ".pm": "perl",
    ".r": "r",
    ".R": "r",
    ".scala": "scala",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".swift": "swift",
    ".m": "objc",
    ".mm": "objc",
    ".cs": "csharp",
    ".fs": "fsharp",
    ".hs": "haskell",
    ".ml": "ocaml",
    ".mli": "ocaml",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".clj": "clojure",
    ".zig": "zig",
    ".nim": "nim",
    ".d": "d",
    ".v": "verilog",
    ".sv": "systemverilog",
    ".sql": "sql",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".json": "json",
    ".xml": "xml",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".less": "less",
    ".md": "markdown",
    ".rst": "rst",
    ".txt": "text",
    ".cmake": "cmake",
    ".Makefile": "makefile",
}

# Extensions to always skip (binary or non-source)
BINARY_EXTENSIONS: Set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".flac", ".ogg",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".whl", ".egg", ".pyc", ".pyo", ".so", ".dll", ".dylib", ".a", ".o", ".obj",
    ".class", ".jar",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    ".db", ".sqlite", ".sqlite3",
    ".bin", ".dat", ".exe", ".msi",
    ".lock",
}

# Directories to skip during pathlib walk
DEFAULT_IGNORE_PATTERNS: Set[str] = {
    "__pycache__", ".git", ".hg", ".svn",
    "node_modules", "vendor", ".venv", "venv", "env",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build", ".eggs", "*.egg-info",
    ".judais-lobi", ".claude",
    "target",  # Rust / Java
}


def classify_language(path: str) -> str:
    """Classify a file path to a language string. Returns '' for unknown."""
    p = Path(path)
    # Check for Makefile (no extension)
    if p.name in ("Makefile", "makefile", "GNUmakefile"):
        return "makefile"
    if p.name in ("Dockerfile",):
        return "dockerfile"
    return LANGUAGE_MAP.get(p.suffix, "")


def _is_binary(path: str) -> bool:
    """Check if a file is binary based on extension."""
    return Path(path).suffix.lower() in BINARY_EXTENSIONS


def _should_ignore_dir(name: str) -> bool:
    """Check if a directory name matches ignore patterns."""
    return name in DEFAULT_IGNORE_PATTERNS or name.endswith(".egg-info")


# ---------------------------------------------------------------------------
# Git-based discovery
# ---------------------------------------------------------------------------

def discover_files_git(
    repo_path: str,
    subprocess_runner: Optional[Callable] = None,
) -> List[str]:
    """Discover tracked files via git ls-files. Raises RuntimeError on failure."""
    cmd = f"cd {_quote(repo_path)} && git ls-files"
    rc, stdout, stderr = run_subprocess(
        cmd, shell=True, timeout=30,
        subprocess_runner=subprocess_runner,
    )
    if rc != 0:
        raise RuntimeError(f"git ls-files failed (rc={rc}): {stderr}")
    files = [f for f in stdout.splitlines() if f.strip() and not _is_binary(f)]
    return sorted(files)


# ---------------------------------------------------------------------------
# Pathlib fallback discovery
# ---------------------------------------------------------------------------

def discover_files_walk(
    root: str,
    ignore_patterns: Optional[Set[str]] = None,
) -> List[str]:
    """Discover files via pathlib walk, respecting ignore patterns."""
    ignore = ignore_patterns if ignore_patterns is not None else DEFAULT_IGNORE_PATTERNS
    root_path = Path(root)
    results: List[str] = []

    def _walk(directory: Path) -> None:
        try:
            entries = sorted(directory.iterdir())
        except PermissionError:
            return
        for entry in entries:
            if entry.is_dir():
                if not _should_ignore_dir(entry.name):
                    _walk(entry)
            elif entry.is_file():
                if not _is_binary(str(entry)):
                    try:
                        rel = str(entry.relative_to(root_path))
                        results.append(rel)
                    except ValueError:
                        pass

    _walk(root_path)
    return sorted(results)


# ---------------------------------------------------------------------------
# Unified discovery
# ---------------------------------------------------------------------------

def discover_files(
    repo_path: str,
    subprocess_runner: Optional[Callable] = None,
) -> List[str]:
    """Discover files: try git ls-files first, fall back to pathlib walk."""
    try:
        return discover_files_git(repo_path, subprocess_runner)
    except (RuntimeError, Exception):
        return discover_files_walk(repo_path)


def _quote(s: str) -> str:
    """Simple shell quoting."""
    import shlex
    return shlex.quote(s)
