"""Output truncation utilities.

Prevents oversized tool outputs from consuming excessive LLM context tokens.
"""

MAX_LINES = 2000
MAX_BYTES = 50 * 1024  # 50 KB


def truncate(text: str) -> str:
    """Truncate text if it exceeds line or byte limits.

    Args:
        text: The raw tool output string.

    Returns:
        The original text if within limits, otherwise a truncated version with
        a trailing notice indicating how many lines were omitted.
    """
    lines = text.splitlines()
    within_lines = len(lines) <= MAX_LINES
    within_bytes = len(text.encode()) <= MAX_BYTES

    if within_lines and within_bytes:
        return text

    kept = lines[:MAX_LINES]
    omitted = len(lines) - len(kept)
    suffix = f"\n[Output truncated: showing first {len(kept)} of {len(lines)} lines ({omitted} lines omitted)]"
    return "\n".join(kept) + suffix
