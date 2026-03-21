"""Edit tool for find-and-replace file editing."""

import logging
import os

from strands import tool

logger = logging.getLogger(__name__)


@tool
def edit(file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> dict:
    """Edit a file by replacing occurrences of old_string with new_string.

    Args:
        file_path: Absolute or relative path to the file to edit.
        old_string: The exact text to find. Must be unique in the file unless
            replace_all is True.
        new_string: The replacement text.
        replace_all: When True, replace all occurrences. When False (default),
            exactly one occurrence must exist.

    Returns:
        A dict with status and a description of the change made.
    """
    logger.debug("file_path=<%s>, replace_all=<%s> | editing file", file_path, replace_all)

    resolved = os.path.abspath(file_path)
    if not os.path.exists(resolved):
        return {"status": "error", "content": [{"text": f"File not found: {file_path}"}]}
    if not os.path.isfile(resolved):
        return {"status": "error", "content": [{"text": f"Path is not a file: {file_path}"}]}

    try:
        with open(resolved, encoding="utf-8") as fh:
            original = fh.read()

        count = original.count(old_string)
        if count == 0:
            return {
                "status": "error",
                "content": [{"text": f"old_string not found in {file_path}"}],
            }
        if not replace_all and count > 1:
            return {
                "status": "error",
                "content": [
                    {
                        "text": (
                            f"old_string appears {count} times in {file_path}. "
                            "Provide a more unique string or set replace_all=True."
                        )
                    }
                ],
            }

        if replace_all:
            updated = original.replace(old_string, new_string)
            replacements = count
        else:
            updated = original.replace(old_string, new_string, 1)
            replacements = 1

        with open(resolved, "w", encoding="utf-8") as fh:
            fh.write(updated)

        return {
            "status": "success",
            "content": [{"text": f"Replaced {replacements} occurrence(s) in {file_path}"}],
        }
    except Exception as exc:
        logger.warning("file_path=<%s>, error=<%s> | error editing file", file_path, exc)
        return {"status": "error", "content": [{"text": str(exc)}]}
