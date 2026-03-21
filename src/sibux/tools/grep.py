"""Grep tool for searching file contents."""

import logging
import os
import re
import subprocess

from strands import tool

from .truncation import truncate

logger = logging.getLogger(__name__)


@tool
def grep(pattern: str, path: str = "", include: str = "") -> dict:
    """Search for a regex pattern across files.

    Delegates to ripgrep (rg) when available for performance; falls back to
    Python's re module otherwise.

    Args:
        pattern: Regular expression pattern to search for.
        path: File or directory to search in. Defaults to current working directory.
        include: Glob pattern to restrict which files are searched (e.g., "*.py").
            Only used with ripgrep. Defaults to all files.

    Returns:
        A dict with status and matching lines in "file:line:content" format.
    """
    search_path = os.path.abspath(path) if path else os.getcwd()
    logger.debug("pattern=<%s>, path=<%s>, include=<%s> | running grep", pattern, search_path, include)

    # prefer ripgrep when available
    rg_path = _find_rg()
    if rg_path:
        return _grep_rg(rg_path, pattern, search_path, include)
    return _grep_python(pattern, search_path, include)


def _find_rg() -> str:
    """Return the path to the rg binary, or empty string if not found."""
    try:
        result = subprocess.run(["which", "rg"], capture_output=True, text=True, timeout=5)
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _grep_rg(rg: str, pattern: str, path: str, include: str) -> dict:
    """Run ripgrep."""
    cmd = [rg, "--line-number", "--no-heading", "--color=never", pattern, path]
    if include:
        cmd += ["--glob", include]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        output = result.stdout + result.stderr
        if not output.strip():
            return {"status": "success", "content": [{"text": "(no matches)"}]}
        return {"status": "success", "content": [{"text": truncate(output)}]}
    except subprocess.TimeoutExpired:
        return {"status": "error", "content": [{"text": "grep timed out"}]}
    except Exception as exc:
        return {"status": "error", "content": [{"text": str(exc)}]}


def _grep_python(pattern: str, path: str, include: str) -> dict:
    """Pure-Python fallback grep."""
    import fnmatch

    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return {"status": "error", "content": [{"text": f"Invalid regex: {exc}"}]}

    lines: list[str] = []
    try:
        if os.path.isfile(path):
            files = [path]
        else:
            files = []
            for root, _, filenames in os.walk(path):
                for fn in filenames:
                    fp = os.path.join(root, fn)
                    if not include or fnmatch.fnmatch(fn, include):
                        files.append(fp)

        for fp in sorted(files):
            try:
                with open(fp, encoding="utf-8", errors="replace") as fh:
                    for lineno, line in enumerate(fh, 1):
                        if compiled.search(line):
                            lines.append(f"{fp}:{lineno}:{line.rstrip()}")
            except Exception:
                continue

        if not lines:
            return {"status": "success", "content": [{"text": "(no matches)"}]}
        return {"status": "success", "content": [{"text": truncate("\n".join(lines))}]}
    except Exception as exc:
        logger.warning("pattern=<%s>, error=<%s> | python grep error", pattern, exc)
        return {"status": "error", "content": [{"text": str(exc)}]}
