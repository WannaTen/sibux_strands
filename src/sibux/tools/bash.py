"""Bash tool for executing shell commands."""

import logging
import os
import subprocess

from strands import tool

from .truncation import truncate

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 120


@tool
def bash(command: str, timeout: int = _DEFAULT_TIMEOUT_SECONDS, description: str = "") -> dict:
    """Execute a shell command and return its output.

    Args:
        command: The shell command to execute.
        timeout: Maximum execution time in seconds. Defaults to 120.
        description: Optional human-readable description of what the command does.

    Returns:
        A dict with status and combined stdout/stderr output.
    """
    logger.debug("command=<%s>, timeout=<%d> | executing bash command", command, timeout)

    cwd = os.getcwd()
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        output = proc.stdout + proc.stderr
        output = truncate(output)

        if proc.returncode != 0:
            logger.debug(
                "command=<%s>, returncode=<%d> | command exited with non-zero status", command, proc.returncode
            )

        return {
            "status": "success",
            "content": [{"text": output or "(no output)"}],
        }
    except subprocess.TimeoutExpired:
        msg = f"Command timed out after {timeout} seconds: {command}"
        logger.warning("command=<%s>, timeout=<%d> | command timed out", command, timeout)
        return {"status": "error", "content": [{"text": msg}]}
    except Exception as exc:
        logger.warning("command=<%s>, error=<%s> | unexpected error executing command", command, exc)
        return {"status": "error", "content": [{"text": str(exc)}]}
