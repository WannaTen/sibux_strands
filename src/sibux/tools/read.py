"""Read tool for reading file contents."""

import logging
import os

from strands import tool

from .truncation import truncate

logger = logging.getLogger(__name__)


@tool
def read(file_path: str, offset: int = 0, limit: int = 0) -> dict:
    """Read the contents of a file.

    Args:
        file_path: Absolute or relative path to the file.
        offset: Line number to start reading from (0-based). Defaults to 0.
        limit: Maximum number of lines to read. 0 means read all. Defaults to 0.

    Returns:
        A dict with status and the file contents.
    """
    logger.debug("file_path=<%s>, offset=<%d>, limit=<%d> | reading file", file_path, offset, limit)

    resolved = os.path.abspath(file_path)
    if not os.path.exists(resolved):
        return {"status": "error", "content": [{"text": f"File not found: {file_path}"}]}
    if not os.path.isfile(resolved):
        return {"status": "error", "content": [{"text": f"Path is not a file: {file_path}"}]}

    try:
        with open(resolved, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()

        sliced = lines[offset:] if limit == 0 else lines[offset : offset + limit]
        content = "".join(sliced)
        content = truncate(content)

        return {"status": "success", "content": [{"text": content}]}
    except Exception as exc:
        logger.warning("file_path=<%s>, error=<%s> | error reading file", file_path, exc)
        return {"status": "error", "content": [{"text": str(exc)}]}
