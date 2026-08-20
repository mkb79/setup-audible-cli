"""Install audible-cli with the requested crypto backend.

Run as a composite-action step by ``action.yml``, using the interpreter that
``actions/setup-python`` selected. pip is invoked through an argument list, so
no action input is ever interpreted as shell code.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import sysconfig
from collections.abc import Mapping
from pathlib import Path

import _github as github

DISTRIBUTION = "audible-cli"
EXECUTABLE = "audible"
LATEST = "latest"

DEFAULT_BACKEND = "cryptography"

# The Python range audible-cli supports. Checked before pip runs so that an
# unsupported python-version input fails with a clear message instead of an
# opaque resolution error.
MIN_PYTHON = (3, 11)
MAX_PYTHON_EXCLUSIVE = (3, 15)

# The module each accelerated backend actually provides. audible selects its
# crypto provider at runtime and silently falls back to a pure-Python
# implementation when the requested one is missing, so the install is confirmed
# by importing this rather than by trusting that pip resolved the extra.
BACKEND_MODULES = {
    "cryptography": "cryptography",
    "pycryptodome": "Crypto",
}

# "none" installs audible-cli without any crypto extra. audible then has nothing
# to accelerate with and uses its pure-Python implementation -- unless one of the
# libraries is already in the environment, which is why the provider it settled
# on is reported either way.
NO_BACKEND = "none"
SUPPORTED_BACKENDS = (NO_BACKEND, *BACKEND_MODULES)

# Installing from a ref instead of PyPI. Only GitHub owner/name is accepted, so
# the input cannot turn into an arbitrary URL or a local path.
GIT_HOST = "https://github.com"
DEFAULT_GIT_REPOSITORY = "mkb79/audible-cli"

# A branch, tag or commit. The excluded characters are the ones that carry
# meaning in a PEP 508 direct reference -- "@" separates the ref and "#" starts a
# fragment -- so a ref cannot reshape the requirement into something else.
GIT_REF_RE = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._/-]*$")
GIT_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")

VERSION_OUTPUT = "audible-version"
PATH_OUTPUT = "audible-path"

# ``latest`` or one exact PEP 440 release. Deliberately not a general pip
# requirement expression: accepting ">=0.5" or "audible-cli @ git+..." through
# this input would give it surprising semantics.
_NUMBER = r"(?:0|[1-9][0-9]*)"
VERSION_RE = re.compile(
    rf"^v?"
    rf"(?:{_NUMBER}!)?"
    rf"{_NUMBER}(?:\.{_NUMBER})*"
    rf"(?:(?:a|b|rc){_NUMBER})?"
    rf"(?:\.post{_NUMBER})?"
    rf"(?:\.dev{_NUMBER})?$"
)


class InstallError(Exception):
    """An input or installation problem to report to the workflow."""


def check_python_version(version_info: tuple[int, int] | None = None) -> None:
    """Reject an interpreter audible-cli does not support."""
    info = tuple(version_info) if version_info else sys.version_info[:2]
    if not MIN_PYTHON <= info < MAX_PYTHON_EXCLUSIVE:
        supported = (
            f">={MIN_PYTHON[0]}.{MIN_PYTHON[1]},"
            f"<{MAX_PYTHON_EXCLUSIVE[0]}.{MAX_PYTHON_EXCLUSIVE[1]}"
        )
        raise InstallError(
            f"{DISTRIBUTION} requires Python {supported}, but the selected "
            f"interpreter is {info[0]}.{info[1]}. Adjust the python-version input."
        )


def normalize_backend(value: str | None) -> str:
    """Validate the crypto-backend input."""
    backend = (value or DEFAULT_BACKEND).strip().lower()
    if backend not in SUPPORTED_BACKENDS:
        supported = ", ".join(sorted(SUPPORTED_BACKENDS))
        raise InstallError(
            f"crypto-backend must be one of: {supported}. Got: {backend!r}."
        )
    return backend


def normalize_version(value: str | None) -> str:
    """Validate the version input and return ``latest`` or an exact version."""
    version = (value or LATEST).strip()
    if version.lower() == LATEST:
        return LATEST
    if not VERSION_RE.match(version):
        raise InstallError(
            f"version must be {LATEST!r} or an exact {DISTRIBUTION} version "
            f"such as '0.5.1'. Got: {version!r}."
        )
    return version.lstrip("v")


def normalize_git_ref(value: str | None) -> str:
    """Validate the git-ref input. Empty means: install from PyPI."""
    ref = (value or "").strip()
    if not ref:
        return ""
    # git's own ref rules, narrowed to the characters that are also safe inside
    # a PEP 508 direct reference.
    if not GIT_REF_RE.match(ref) or ".." in ref or ref.endswith((".", "/")):
        raise InstallError(
            f"git-ref must be a branch, tag or commit, such as 'master' or "
            f"'feature/my-branch'. Got: {ref!r}."
        )
    return ref


def normalize_git_repository(value: str | None) -> str:
    """Validate the git-repository input."""
    repository = (value or DEFAULT_GIT_REPOSITORY).strip()
    if not GIT_REPOSITORY_RE.match(repository):
        raise InstallError(
            f"git-repository must be a GitHub repository in owner/name form, "
            f"such as {DEFAULT_GIT_REPOSITORY!r}. Got: {repository!r}."
        )
    return repository


def check_source(version: str, git_ref: str, git_repository: str) -> None:
    """Reject input combinations that ask for two different sources at once."""
    if git_ref and version != LATEST:
        raise InstallError(
            f"version and git-ref cannot be combined: version picks a PyPI "
            f"release, git-ref installs from a branch, tag or commit instead. "
            f"Set only one of them."
        )
    if not git_ref and git_repository != DEFAULT_GIT_REPOSITORY:
        raise InstallError(
            "git-repository only applies when git-ref is set, and would be "
            "ignored here. Set git-ref as well, or drop git-repository."
        )


def build_requirement(
    version: str,
    backend: str,
    git_ref: str = "",
    git_repository: str = DEFAULT_GIT_REPOSITORY,
) -> str:
    """Build the pip requirement for the requested source and backend."""
    requirement = DISTRIBUTION if backend == NO_BACKEND else f"{DISTRIBUTION}[{backend}]"
    if git_ref:
        return f"{requirement} @ git+{GIT_HOST}/{git_repository}@{git_ref}"
    if version == LATEST:
        return requirement
    return f"{requirement}=={version}"


def pip_command(requirements: list[str], upgrade: bool = False) -> list[str]:
    """Build the pip argument list.

    An argument list rather than a command string is what keeps an input from
    being interpreted by a shell.
    """
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
    ]
    if upgrade:
        command.append("--upgrade")
    command.extend(requirements)
    return command


def pip_install(requirements: list[str], upgrade: bool = False) -> None:
    """Install the given requirements, letting pip write to the step log."""
    subprocess.run(pip_command(requirements, upgrade=upgrade), check=True)


def query_interpreter(code: str) -> str | None:
    """Run a snippet in a fresh interpreter and return its stdout.

    A subprocess is used rather than importing here, because this process
    started before the install and would still hold the old import and metadata
    caches.
    """
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def backend_available(backend: str) -> bool:
    """Whether the backend's module can actually be imported after the install."""
    module = BACKEND_MODULES[backend]
    return query_interpreter(f"import {module}") is not None


def installed_commit() -> str | None:
    """Read the commit a git install resolved to, if it was one.

    pip records it in direct_url.json, which is the only place the exact code
    under test is written down: a branch reports whatever version its pyproject
    declares, which says nothing about where the branch stood.
    """
    return (
        query_interpreter(
            "import importlib.metadata as m, json;"
            "t = m.distribution('audible-cli').read_text('direct_url.json');"
            "print(json.loads(t)['vcs_info']['commit_id'] if t else '')"
        )
        or None
    )


def build_reported_version(distribution_version: str, commit: str | None) -> str:
    """Attach the commit to the version as a PEP 440 local version identifier.

    A branch reports whatever version its pyproject declares -- master says
    0.5.1 today, which is also what the last release said -- so the bare version
    cannot identify what was installed. "0.5.1+<sha>" is the standard way to say
    "this build of that version": still a valid PEP 440 version, still ordered
    after the plain release, and Version(...).base_version gives 0.5.1 back.

    The "g" follows git describe and setuptools-scm, and is not decoration: PEP
    440 normalizes an all-digit local segment to an integer, which would eat the
    leading zeroes of a commit that happens to contain no letters.
    """
    if not commit:
        return distribution_version
    return f"{distribution_version}+g{commit}"


def installed_version(distribution: str = DISTRIBUTION) -> str | None:
    """Read an installed distribution's version from its metadata."""
    return query_interpreter(
        f"import importlib.metadata as m; print(m.version({distribution!r}))"
    )


def backend_requirement(backend: str, audible_version: str) -> str:
    """Build the requirement that installs the backend through audible itself.

    Pinned to the audible that the audible-cli install just resolved, so adding
    the extra cannot pull a different audible into the environment.
    """
    return f"audible[{backend}]=={audible_version}"


def selected_backend() -> str | None:
    """Ask audible which crypto provider it will actually use.

    audible picks its provider by availability, preferring cryptography over
    pycryptodome over its pure-Python fallback, so having the requested module
    installed does not by itself mean it is the one being used. Returns None if
    the installed audible does not expose the registry.
    """
    return query_interpreter(
        "from audible.crypto_provider import get_crypto_providers;"
        "print(get_crypto_providers().provider_name)"
    )


def executable_names() -> tuple[str, ...]:
    """Candidate file names for the console script on this platform."""
    if os.name == "nt":
        return (f"{EXECUTABLE}.exe", EXECUTABLE)
    return (EXECUTABLE,)


def script_dirs() -> list[Path]:
    """Directories this interpreter installs console scripts into."""
    directories = []
    for scheme in (None, f"{os.name}_user"):
        try:
            path = (
                sysconfig.get_path("scripts")
                if scheme is None
                else sysconfig.get_path("scripts", scheme)
            )
        except (KeyError, ValueError):  # pragma: no cover - scheme-dependent
            continue
        if path:
            directories.append(Path(path))
    return directories


def resolve_executable() -> Path | None:
    """Locate the audible executable belonging to this interpreter.

    Only this interpreter's own script directories are searched. Falling back to
    PATH would happily return an unrelated audible that happens to be installed
    there, and report it alongside the version read from this interpreter's
    metadata.
    """
    for directory in script_dirs():
        for name in executable_names():
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def main(environ: Mapping[str, str] | None = None) -> int:
    environ = os.environ if environ is None else environ
    try:
        check_python_version()
        version = normalize_version(environ.get("INPUT_VERSION"))
        backend = normalize_backend(environ.get("INPUT_CRYPTO_BACKEND"))
        git_ref = normalize_git_ref(environ.get("INPUT_GIT_REF"))
        git_repository = normalize_git_repository(environ.get("INPUT_GIT_REPOSITORY"))
        check_source(version, git_ref, git_repository)
    except InstallError as exc:
        github.error(str(exc))
        return 1

    requirement = build_requirement(version, backend, git_ref, git_repository)
    print(f"Installing {requirement}")
    try:
        # A branch moves, so a git ref is always reinstalled rather than left at
        # whatever an earlier step happened to put there.
        pip_install([requirement], upgrade=bool(git_ref) or version == LATEST)
    except subprocess.CalledProcessError as exc:
        github.error(f"pip failed to install {requirement} (exit code {exc.returncode}).")
        return 1

    if backend != NO_BACKEND and not backend_available(backend):
        # Released audible-cli versions before the pycryptodome extra existed
        # accept the extra without providing it, which would leave audible on
        # its pure-Python fallback instead of the requested backend.
        audible_version = installed_version("audible")
        if audible_version is None:
            github.error(
                f"the {backend!r} extra is missing and the installed audible "
                f"version could not be read, so it cannot be added safely."
            )
            return 1
        fallback = backend_requirement(backend, audible_version)
        github.notice(
            f"The installed {DISTRIBUTION} does not provide the {backend!r} "
            f"extra; installing {fallback} so the requested backend is present."
        )
        try:
            pip_install([fallback])
        except subprocess.CalledProcessError as exc:
            github.error(f"pip failed to install {fallback} (exit code {exc.returncode}).")
            return 1
        if not backend_available(backend):
            github.error(
                f"the {backend!r} crypto backend is not importable after installation."
            )
            return 1

    provider = selected_backend()
    if backend != NO_BACKEND and provider is not None and provider != backend:
        # Not an error: audible's preference order is audible's to decide, and
        # removing the preferred library to honour the request would be worse.
        github.notice(
            f"{backend} is installed, but audible selects {provider}, which it "
            f"prefers when both are available."
        )

    executable = resolve_executable()
    if executable is None:
        searched = ", ".join(str(directory) for directory in script_dirs())
        github.error(
            f"the {EXECUTABLE} executable was not found after installing "
            f"{requirement}. Searched: {searched}."
        )
        return 1

    distribution_version = installed_version()
    if distribution_version is None:
        github.error(f"could not read the installed {DISTRIBUTION} version.")
        return 1

    if not git_ref and version != LATEST and distribution_version != version:
        # pip normalizes and zero-pads versions, so "1.0" can legitimately
        # resolve to "1.0.0". Report the difference instead of failing on it.
        github.notice(
            f"requested {DISTRIBUTION} {version}, installed {distribution_version}."
        )

    reported_version = build_reported_version(
        distribution_version, installed_commit() if git_ref else None
    )

    # add_path guarantees the executable is on PATH for every following workflow
    # step, independent of how the interpreter was set up. All three have to land
    # for the step to have delivered what it promises, so they fail closed.
    published = [
        github.add_path(executable.parent),
        github.set_output(VERSION_OUTPUT, reported_version),
        github.set_output(PATH_OUTPUT, str(executable)),
    ]
    if not all(published):
        github.error(
            "the runner command files are not available, so PATH and the outputs "
            "could not be published."
        )
        return 1

    summary = f"Installed {DISTRIBUTION} {reported_version}"
    if provider is not None:
        summary += f" (crypto provider: {provider})"
    print(summary)
    if git_ref:
        print(f"source: git+{GIT_HOST}/{git_repository}@{git_ref}")
    print(f"{EXECUTABLE}: {executable}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
