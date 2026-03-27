"""Best-effort MCP instrumentation hooks."""

import logging

logger = logging.getLogger(__name__)

_IS_INSTRUMENTED = False


def mcp_instrumentation() -> None:
    """Initialize MCP instrumentation if available.

    The SDK should remain importable even when optional MCP telemetry helpers are
    not installed, so this is intentionally a no-op placeholder.
    """
    global _IS_INSTRUMENTED

    if _IS_INSTRUMENTED:
        return

    logger.debug("MCP instrumentation unavailable or not configured")
    _IS_INSTRUMENTED = True
