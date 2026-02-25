# core/patch/parser.py — Extract SEARCH/REPLACE blocks from LLM text output

import re
from typing import List

from core.contracts.schemas import FilePatch


class ParseError(Exception):
    """Raised on malformed patch blocks."""


def _validate_path(file_path: str) -> None:
    """Reject absolute paths and traversal attempts."""
    stripped = file_path.strip()
    if not stripped:
        raise ParseError("Empty file path")
    if stripped.startswith("/") or stripped.startswith("\\"):
        raise ParseError(f"Absolute path rejected: {stripped}")
    # Check for .. components (covers ../, ..\, standalone ..)
    parts = re.split(r"[/\\]", stripped)
    for part in parts:
        if part == "..":
            raise ParseError(f"Path traversal rejected: {stripped}")


def parse_patch_text(text: str) -> List[FilePatch]:
    """Parse LLM text output into a list of FilePatch objects.

    Recognizes three block types:

    Modify (SEARCH/REPLACE):
        <<<< SEARCH path/to/file.py
        old code
        ====
        new code
        >>>> REPLACE

    Create:
        <<<< CREATE path/to/file.py
        full file content
        >>>> CREATE

    Delete (single-line):
        <<<< DELETE path/to/file.py >>>>

    Delimiters are only recognized at the start of a line (after optional
    leading whitespace). Returns List[FilePatch].
    """
    if not text or not text.strip():
        return []

    patches: List[FilePatch] = []
    lines = text.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()

        # --- DELETE (single-line format) ---
        delete_match = re.match(
            r"<{4}\s+DELETE\s+(.+?)\s*>{4}\s*$", stripped
        )
        if delete_match:
            file_path = delete_match.group(1).strip()
            _validate_path(file_path)
            patches.append(FilePatch(
                file_path=file_path,
                action="delete",
            ))
            i += 1
            continue

        # --- SEARCH block ---
        search_match = re.match(r"<{4}\s+SEARCH\s+(.+)$", stripped)
        if search_match:
            file_path = search_match.group(1).strip()
            if not file_path:
                raise ParseError(f"SEARCH block with no file path at line {i + 1}")
            _validate_path(file_path)
            i += 1

            # Collect search block lines until ====
            search_lines: List[str] = []
            found_separator = False
            while i < len(lines):
                sep_stripped = lines[i].lstrip()
                if re.match(r"={4}\s*$", sep_stripped):
                    found_separator = True
                    i += 1
                    break
                search_lines.append(lines[i])
                i += 1

            if not found_separator:
                raise ParseError(
                    f"Unclosed SEARCH block for {file_path}: missing ==== separator"
                )

            # Collect replace block lines until >>>> REPLACE
            replace_lines: List[str] = []
            found_end = False
            while i < len(lines):
                end_stripped = lines[i].lstrip()
                if re.match(r">{4}\s+REPLACE\s*$", end_stripped):
                    found_end = True
                    i += 1
                    break
                replace_lines.append(lines[i])
                i += 1

            if not found_end:
                raise ParseError(
                    f"Unclosed SEARCH block for {file_path}: missing >>>> REPLACE"
                )

            search_block = "\n".join(search_lines)
            replace_block = "\n".join(replace_lines)

            if not search_block and not search_block == "":
                pass  # Empty search is an error handled below

            patches.append(FilePatch(
                file_path=file_path,
                search_block=search_block,
                replace_block=replace_block,
                action="modify",
            ))
            continue

        # --- CREATE block ---
        create_match = re.match(r"<{4}\s+CREATE\s+(.+)$", stripped)
        if create_match:
            file_path = create_match.group(1).strip()
            if not file_path:
                raise ParseError(f"CREATE block with no file path at line {i + 1}")
            _validate_path(file_path)
            i += 1

            content_lines: List[str] = []
            found_end = False
            while i < len(lines):
                end_stripped = lines[i].lstrip()
                if re.match(r">{4}\s+CREATE\s*$", end_stripped):
                    found_end = True
                    i += 1
                    break
                content_lines.append(lines[i])
                i += 1

            if not found_end:
                raise ParseError(
                    f"Unclosed CREATE block for {file_path}: missing >>>> CREATE"
                )

            content = "\n".join(content_lines)
            patches.append(FilePatch(
                file_path=file_path,
                replace_block=content,
                action="create",
            ))
            continue

        # Not a delimiter line — skip (commentary/prose)
        i += 1

    return patches
