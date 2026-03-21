"""Write tool for creating or overwriting files."""

import logging
import os

from strands import tool

logger = logging.getLogger(__name__)


@tool
def write(file_path: str, content: str) -> dict:
    """Write content to a file, creating it and any missing parent directories.

    Args:
        file_path: Absolute or relative path to the file to write.
        content: The full content to write to the file.

    Returns:
        A dict with status and the path of the written file.
    """
    logger.debug("file_path=<%s> | writing file", file_path)

    resolved = os.path.abspath(file_path)
    try:
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as fh:
            fh.write(content)
        return {
            "status": "success",
            "content": [{"text": f"Written to {file_path}"}],
        }
    except Exception as exc:
        logger.warning("file_path=<%s>, error=<%s> | error writing file", file_path, exc)
        return {"status": "error", "content": [{"text": str(exc)}]}
