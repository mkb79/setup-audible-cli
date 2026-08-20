"""Helpers for the file commands a GitHub Actions runner exposes.

The ``name<<delimiter`` form used by ``GITHUB_ENV`` and ``GITHUB_OUTPUT`` is
easy to get subtly wrong, and both helper scripts need it, so it lives here
rather than being written out twice.
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path


class GitHubFileError(Exception):
    """A value could not be encoded for a runner file command."""


def format_key_value(name: str, value: str) -> str:
    """Render one ``GITHUB_ENV`` / ``GITHUB_OUTPUT`` entry.

    The delimited form is used even for single-line values, so that a value
    containing ``=`` or a newline can never be mis-parsed by the runner.
    """
    delimiter = f"setup-audible-cli-{secrets.token_hex(16)}"
    if delimiter in value:
        raise GitHubFileError(f"could not encode a value for {name!r}")
    return f"{name}<<{delimiter}\n{value}\n{delimiter}\n"


def append_to_file(env_var: str, text: str) -> bool:
    """Append ``text`` to the runner file named by ``env_var``.

    Returns ``False`` when the variable is unset, which is the normal case
    outside of a runner (for example while running the unit tests).
    """
    path = os.environ.get(env_var)
    if not path:
        return False
    # newline="\n" keeps the runner files LF-terminated on Windows too, so the
    # written bytes do not depend on the platform the action happens to run on.
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return True


def set_output(name: str, value: str) -> bool:
    """Publish a step output."""
    return append_to_file("GITHUB_OUTPUT", format_key_value(name, value))


def set_env(name: str, value: str) -> bool:
    """Export an environment variable to all following workflow steps."""
    return append_to_file("GITHUB_ENV", format_key_value(name, value))


def add_path(directory: Path | str) -> bool:
    """Prepend a directory to ``PATH`` for all following workflow steps."""
    text = str(directory)
    if "\n" in text or "\r" in text:
        raise GitHubFileError("a PATH entry must not contain a line break")
    return append_to_file("GITHUB_PATH", f"{text}\n")


def error(message: str) -> None:
    """Emit a failure annotation. Never called with a credential value."""
    print(f"::error::{message}", file=sys.stdout, flush=True)


def notice(message: str) -> None:
    """Emit an informational annotation."""
    print(f"::notice::{message}", file=sys.stdout, flush=True)
