"""Glob tool for finding files by path pattern."""

import glob
import logging
import os

from strands import tool

from .truncation import truncate

logger = logging.getLogger(__name__)


@tool
def glob_tool(pattern: str, path: str = "") -> dict:
    """Find files matching a glob pattern.

    Args:
        pattern: Glob pattern to match file paths (e.g., "**/*.py", "src/*.ts").
        path: Directory to search in. Defaults to the current working directory.

    Returns:
        A dict with status and a newline-separated list of matching file paths.
    """
    search_root = os.path.abspath(path) if path else os.getcwd()
    full_pattern = os.path.join(search_root, pattern)
    logger.debug("pattern=<%s>, root=<%s> | running glob", pattern, search_root)

    try:
        matches = glob.glob(full_pattern, recursive=True)
        matches.sort()

        if not matches:
            return {"status": "success", "content": [{"text": "(no matches)"}]}

        result = truncate("\n".join(matches))
        return {"status": "success", "content": [{"text": result}]}
    except Exception as exc:
        logger.warning("pattern=<%s>, error=<%s> | error running glob", pattern, exc)
        return {"status": "error", "content": [{"text": str(exc)}]}
