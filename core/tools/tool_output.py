# core/tools/tool_output.py — Tool output handling + log persistence

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Tuple


@dataclass(frozen=True)
class ToolOutputRecord:
    summary: str
    output_bytes: int
    stored_path: Optional[Path] = None


def build_tool_output_record(
    tool_name: str,
    result: Any,
    max_bytes: int,
    log_root: Optional[Path] = None,
) -> ToolOutputRecord:
    rc, stdout, stderr = _normalize_result(result)
    output = _combine_output(stdout, stderr)
    size = len(output.encode("utf-8", errors="ignore"))

    if size > max_bytes:
        path = _write_log(output, tool_name, log_root)
        summary = (
            f"(Tool used: {tool_name})\n"
            f"Exit code: {rc}\n"
            f"Output exceeded budget ({size} bytes).\n"
            f"Full log at: {path}\n"
            "Use targeted retrieval (grep, tail, symbol lookup) to inspect details."
        )
        return ToolOutputRecord(summary=summary, output_bytes=size, stored_path=path)

    summary = (
        f"(Tool used: {tool_name})\n"
        f"Exit code: {rc}\n"
        f"Output ({size} bytes):\n{output}"
    )
    return ToolOutputRecord(summary=summary, output_bytes=size)


def _normalize_result(result: Any) -> Tuple[int, str, str]:
    if isinstance(result, tuple) and len(result) == 3:
        rc, out, err = result
        return int(rc), str(out or ""), str(err or "")
    return 0, str(result or ""), ""


def _combine_output(stdout: str, stderr: str) -> str:
    if stderr and stdout:
        return f"{stdout}\n\n[stderr]\n{stderr}"
    if stderr:
        return f"[stderr]\n{stderr}"
    return stdout


def _write_log(output: str, tool_name: str, log_root: Optional[Path]) -> Path:
    root = log_root or (Path.cwd() / ".judais-lobi" / "tool_logs")
    root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"{stamp}_{tool_name}.log"
    path = root / filename
    path.write_text(output, encoding="utf-8")
    return path
