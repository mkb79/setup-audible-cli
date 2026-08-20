"""Unit tests for scripts/install.py.

No test here runs pip, resolves a distribution or reaches the network: the
subprocess boundary is always replaced.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

import install


# --------------------------------------------------------------------------
# version input
# --------------------------------------------------------------------------


@pytest.mark.parametrize("supplied", ["latest", "LATEST", " latest ", "", None])
def test_latest_is_the_default_and_is_accepted(supplied):
    assert install.normalize_version(supplied) == "latest"


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        ("0.5.1", "0.5.1"),
        (" 0.5.1 ", "0.5.1"),
        ("v0.5.1", "0.5.1"),
        ("1.0", "1.0"),
        ("1.2.3.4", "1.2.3.4"),
        ("1.0rc1", "1.0rc1"),
        ("1.0a2", "1.0a2"),
        ("1.0.post1", "1.0.post1"),
        ("1.0.dev1", "1.0.dev1"),
        ("1!1.0", "1!1.0"),
    ],
)
def test_explicit_versions_are_accepted(supplied, expected):
    assert install.normalize_version(supplied) == expected


@pytest.mark.parametrize(
    "supplied",
    [
        ">=0.5.1",
        "<1.0",
        "==0.5.1",
        "0.5.*",
        "0.5.1,<0.6",
        "audible-cli==0.5.1",
        "audible-cli @ git+https://example.invalid/repo.git",
        "0.5.1 --index-url https://example.invalid/simple",
        "0.5.1; python_version>='3.12'",
        "$(id)",
        "0.5.1 && id",
        "latest-ish",
        "01.2",
        "abc",
        "1.0.0-beta",
    ],
)
def test_surprising_version_expressions_are_rejected(supplied):
    with pytest.raises(install.InstallError):
        install.normalize_version(supplied)


# --------------------------------------------------------------------------
# crypto backend input
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        ("cryptography", "cryptography"),
        ("pycryptodome", "pycryptodome"),
        ("PyCryptodome", "pycryptodome"),
        (" cryptography ", "cryptography"),
        ("none", "none"),
        ("NONE", "none"),
        (" none ", "none"),
        ("", "cryptography"),
        (None, "cryptography"),
    ],
)
def test_supported_backends_are_accepted(supplied, expected):
    assert install.normalize_backend(supplied) == expected


@pytest.mark.parametrize("supplied", ["openssl", "legacy", "rsa", "crypto", "no"])
def test_unsupported_backend_is_rejected(supplied):
    with pytest.raises(install.InstallError) as excinfo:
        install.normalize_backend(supplied)

    message = str(excinfo.value)
    for supported in ("cryptography", "pycryptodome", "none"):
        assert supported in message


# --------------------------------------------------------------------------
# python version
# --------------------------------------------------------------------------


@pytest.mark.parametrize("version_info", [(3, 11), (3, 12), (3, 13), (3, 14)])
def test_supported_python_versions_pass(version_info):
    install.check_python_version(version_info)


@pytest.mark.parametrize("version_info", [(3, 9), (3, 10), (3, 15), (4, 0)])
def test_unsupported_python_versions_are_rejected(version_info):
    with pytest.raises(install.InstallError) as excinfo:
        install.check_python_version(version_info)
    assert "python-version" in str(excinfo.value)


# --------------------------------------------------------------------------
# requirement and pip command
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "backend", "expected"),
    [
        ("latest", "cryptography", "audible-cli[cryptography]"),
        ("latest", "pycryptodome", "audible-cli[pycryptodome]"),
        ("0.5.1", "cryptography", "audible-cli[cryptography]==0.5.1"),
        ("0.5.1", "pycryptodome", "audible-cli[pycryptodome]==0.5.1"),
        ("latest", "none", "audible-cli"),
        ("0.5.1", "none", "audible-cli==0.5.1"),
    ],
)
def test_requirement_is_built_for_version_and_backend(version, backend, expected):
    assert install.build_requirement(version, backend) == expected


def test_pip_command_is_an_argument_list_using_this_interpreter():
    command = install.pip_command(["audible-cli[cryptography]"])
    assert command[:5] == [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"]
    assert command[-1] == "audible-cli[cryptography]"
    assert "--upgrade" not in command


def test_pip_command_upgrades_only_when_asked():
    assert "--upgrade" in install.pip_command(["audible-cli"], upgrade=True)


@pytest.mark.parametrize(
    ("backend", "audible_version", "expected"),
    [
        ("pycryptodome", "0.12.0", "audible[pycryptodome]==0.12.0"),
        ("cryptography", "0.12.0", "audible[cryptography]==0.12.0"),
        ("pycryptodome", "1.0", "audible[pycryptodome]==1.0"),
    ],
)
def test_backend_fallback_is_pinned_to_the_installed_audible(
    backend, audible_version, expected
):
    assert install.backend_requirement(backend, audible_version) == expected


def test_pip_command_never_builds_a_shell_string():
    command = install.pip_command(["audible-cli[cryptography]==0.5.1"])
    assert all(isinstance(argument, str) for argument in command)
    assert not any(" " in argument for argument in command[1:5])


# --------------------------------------------------------------------------
# executable discovery
# --------------------------------------------------------------------------


def test_executable_is_found_in_a_script_dir_containing_spaces(tmp_path, monkeypatch):
    scripts = tmp_path / "python env" / "bin"
    scripts.mkdir(parents=True)
    executable = scripts / install.executable_names()[0]
    executable.touch()

    monkeypatch.setattr(install, "script_dirs", lambda: [scripts])
    assert install.resolve_executable() == executable


def test_an_unrelated_audible_on_path_is_not_accepted(tmp_path, monkeypatch):
    """A foreign audible must never be reported as the one just installed."""
    elsewhere = tmp_path / "somewhere else"
    elsewhere.mkdir()
    (elsewhere / install.executable_names()[0]).touch()
    monkeypatch.setenv("PATH", str(elsewhere))
    monkeypatch.setattr(install, "script_dirs", lambda: [tmp_path / "missing"])

    assert install.resolve_executable() is None


def test_missing_executable_resolves_to_none(tmp_path, monkeypatch):
    monkeypatch.setattr(install, "script_dirs", lambda: [tmp_path / "missing"])
    assert install.resolve_executable() is None


def test_script_dirs_are_real_candidates():
    assert install.script_dirs()


# --------------------------------------------------------------------------
# main()
# --------------------------------------------------------------------------


@pytest.fixture
def runner(tmp_path, monkeypatch):
    github_output = tmp_path / "github output"
    github_path = tmp_path / "github path"
    github_output.touch()
    github_path.touch()
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    monkeypatch.setenv("GITHUB_PATH", str(github_path))
    return {"output": github_output, "path": github_path}


@pytest.fixture
def no_pip(monkeypatch):
    """Fail loudly if a test would reach the network."""

    def refuse(*args, **kwargs):
        raise AssertionError("pip must not run in a unit test")

    monkeypatch.setattr(install, "pip_install", refuse)


@pytest.mark.parametrize(
    "environ",
    [
        {"INPUT_CRYPTO_BACKEND": "openssl"},
        {"INPUT_VERSION": ">=0.5"},
    ],
)
def test_main_rejects_bad_input_before_installing(environ, runner, no_pip, capsys):
    assert install.main(environ) == 1
    assert runner["output"].read_text(encoding="utf-8") == ""
    assert runner["path"].read_text(encoding="utf-8") == ""
    assert "::error::" in capsys.readouterr().out


def test_main_publishes_outputs_and_extends_path(tmp_path, runner, monkeypatch, capsys):
    scripts = tmp_path / "python env" / "bin"
    scripts.mkdir(parents=True)
    executable = scripts / install.executable_names()[0]
    executable.touch()

    installed = []
    monkeypatch.setattr(install, "pip_install", lambda reqs, **kw: installed.append(reqs))
    monkeypatch.setattr(install, "backend_available", lambda backend: True)
    monkeypatch.setattr(install, "selected_backend", lambda: "cryptography")
    monkeypatch.setattr(install, "resolve_executable", lambda: executable)
    monkeypatch.setattr(install, "installed_version", lambda *a: "0.5.1")

    assert install.main({"INPUT_VERSION": "0.5.1"}) == 0
    assert installed == [["audible-cli[cryptography]==0.5.1"]]

    from test_configure import read_command_file

    published = read_command_file(runner["output"])
    assert published["audible-version"] == "0.5.1"
    assert published["audible-path"] == str(executable)
    assert "+" not in published["audible-version"], "a PyPI install has no commit"
    assert runner["path"].read_text(encoding="utf-8").strip() == str(scripts)
    capsys.readouterr()


def test_main_installs_the_backend_directly_when_the_extra_is_missing(
    tmp_path, runner, monkeypatch, capsys
):
    """audible-cli releases without the pycryptodome extra must not degrade silently."""
    executable = tmp_path / install.executable_names()[0]
    executable.touch()

    installed = []
    available = {"value": False}

    def fake_pip_install(requirements, **kwargs):
        installed.append(requirements)
        # Only the direct audible[...] install makes the backend importable;
        # the extra on this audible-cli release resolves to nothing.
        if requirements == ["audible[pycryptodome]==0.12.0"]:
            available["value"] = True

    monkeypatch.setattr(install, "pip_install", fake_pip_install)
    monkeypatch.setattr(install, "backend_available", lambda backend: available["value"])
    monkeypatch.setattr(install, "selected_backend", lambda: "pycryptodome")
    monkeypatch.setattr(install, "resolve_executable", lambda: executable)
    monkeypatch.setattr(install, "installed_version", lambda *a: "0.12.0")

    assert install.main({"INPUT_CRYPTO_BACKEND": "pycryptodome"}) == 0
    assert installed == [
        ["audible-cli[pycryptodome]"],
        ["audible[pycryptodome]==0.12.0"],
    ]
    assert "::notice::" in capsys.readouterr().out


def test_main_fails_when_the_backend_stays_unavailable(tmp_path, runner, monkeypatch, capsys):
    monkeypatch.setattr(install, "pip_install", lambda reqs, **kw: None)
    monkeypatch.setattr(install, "backend_available", lambda backend: False)

    assert install.main({"INPUT_CRYPTO_BACKEND": "pycryptodome"}) == 1
    assert "::error::" in capsys.readouterr().out
    assert runner["output"].read_text(encoding="utf-8") == ""


def test_main_fails_when_pip_fails(runner, monkeypatch, capsys):
    def fail(requirements, **kwargs):
        raise subprocess.CalledProcessError(1, ["pip"])

    monkeypatch.setattr(install, "pip_install", fail)
    assert install.main({}) == 1
    assert "::error::" in capsys.readouterr().out
    assert runner["output"].read_text(encoding="utf-8") == ""


def test_main_fails_when_the_executable_is_missing(runner, monkeypatch, capsys):
    monkeypatch.setattr(install, "pip_install", lambda reqs, **kw: None)
    monkeypatch.setattr(install, "backend_available", lambda backend: True)
    monkeypatch.setattr(install, "selected_backend", lambda: "cryptography")
    monkeypatch.setattr(install, "resolve_executable", lambda: None)

    assert install.main({}) == 1
    assert "::error::" in capsys.readouterr().out
    assert runner["output"].read_text(encoding="utf-8") == ""


def test_main_reports_when_audible_selects_a_different_backend(
    tmp_path, runner, monkeypatch, capsys
):
    """Having pycryptodome installed does not mean audible uses it."""
    executable = tmp_path / install.executable_names()[0]
    executable.touch()

    monkeypatch.setattr(install, "pip_install", lambda reqs, **kw: None)
    monkeypatch.setattr(install, "backend_available", lambda backend: True)
    monkeypatch.setattr(install, "selected_backend", lambda: "cryptography")
    monkeypatch.setattr(install, "resolve_executable", lambda: executable)
    monkeypatch.setattr(install, "installed_version", lambda *a: "0.5.1")

    assert install.main({"INPUT_CRYPTO_BACKEND": "pycryptodome"}) == 0
    captured = capsys.readouterr().out
    assert "::notice::" in captured
    assert "audible selects cryptography" in captured
    assert "crypto provider: cryptography" in captured


def test_main_fails_when_the_backend_extra_and_audible_version_are_both_missing(
    runner, monkeypatch, capsys
):
    monkeypatch.setattr(install, "pip_install", lambda reqs, **kw: None)
    monkeypatch.setattr(install, "backend_available", lambda backend: False)
    monkeypatch.setattr(install, "installed_version", lambda *a: None)

    assert install.main({"INPUT_CRYPTO_BACKEND": "pycryptodome"}) == 1
    assert "::error::" in capsys.readouterr().out


@pytest.mark.parametrize("missing", ["GITHUB_OUTPUT", "GITHUB_PATH"])
def test_main_fails_when_a_runner_command_file_is_missing(
    missing, tmp_path, runner, monkeypatch, capsys
):
    """Outputs and PATH are promises; not being able to keep them is a failure."""
    executable = tmp_path / install.executable_names()[0]
    executable.touch()
    monkeypatch.delenv(missing)

    monkeypatch.setattr(install, "pip_install", lambda reqs, **kw: None)
    monkeypatch.setattr(install, "backend_available", lambda backend: True)
    monkeypatch.setattr(install, "selected_backend", lambda: "cryptography")
    monkeypatch.setattr(install, "resolve_executable", lambda: executable)
    monkeypatch.setattr(install, "installed_version", lambda *a: "0.5.1")

    assert install.main({}) == 1
    assert "::error::" in capsys.readouterr().out


def test_main_installs_no_extra_and_skips_the_backend_check_for_none(
    tmp_path, runner, monkeypatch, capsys
):
    """crypto-backend: none must not install or require an accelerated backend."""
    executable = tmp_path / install.executable_names()[0]
    executable.touch()

    installed = []
    monkeypatch.setattr(install, "pip_install", lambda reqs, **kw: installed.append(reqs))
    monkeypatch.setattr(
        install,
        "backend_available",
        lambda backend: pytest.fail("the backend must not be probed for 'none'"),
    )
    monkeypatch.setattr(install, "selected_backend", lambda: "legacy")
    monkeypatch.setattr(install, "resolve_executable", lambda: executable)
    monkeypatch.setattr(install, "installed_version", lambda *a: "0.5.1")

    assert install.main({"INPUT_CRYPTO_BACKEND": "none"}) == 0
    assert installed == [["audible-cli"]]

    captured = capsys.readouterr().out
    assert "crypto provider: legacy" in captured
    assert "::notice::" not in captured


# --------------------------------------------------------------------------
# installing from a git ref
# --------------------------------------------------------------------------


@pytest.mark.parametrize("supplied", ["", "   ", None])
def test_no_git_ref_means_pypi(supplied):
    assert install.normalize_git_ref(supplied) == ""


@pytest.mark.parametrize(
    "supplied",
    ["master", "main", " master ", "feature/my-branch", "v0.5.1", "023b8de", "a" * 40],
)
def test_valid_git_refs_are_accepted(supplied):
    assert install.normalize_git_ref(supplied) == supplied.strip()


@pytest.mark.parametrize(
    "supplied",
    [
        "master@other",
        "master#egg=evil",
        "branch with spaces",
        "-oh-no",
        "ssh://example.invalid/repo",
        "../../etc/passwd",
        "master;id",
    ],
)
def test_git_refs_that_could_reshape_the_requirement_are_rejected(supplied):
    with pytest.raises(install.InstallError):
        install.normalize_git_ref(supplied)


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        (None, "mkb79/audible-cli"),
        ("", "mkb79/audible-cli"),
        ("someone/audible-cli", "someone/audible-cli"),
        (" someone/fork ", "someone/fork"),
    ],
)
def test_git_repository_is_normalized(supplied, expected):
    assert install.normalize_git_repository(supplied) == expected


@pytest.mark.parametrize(
    "supplied",
    [
        "not-a-repo",
        "owner/repo/extra",
        "https://github.com/owner/repo",
        "owner/repo@master",
        "owner /repo",
    ],
)
def test_invalid_git_repository_is_rejected(supplied):
    with pytest.raises(install.InstallError):
        install.normalize_git_repository(supplied)


@pytest.mark.parametrize(
    ("version", "backend", "git_ref", "repository", "expected"),
    [
        (
            "latest",
            "cryptography",
            "master",
            "mkb79/audible-cli",
            "audible-cli[cryptography] @ git+https://github.com/mkb79/audible-cli@master",
        ),
        (
            "latest",
            "none",
            "feature/x",
            "someone/fork",
            "audible-cli @ git+https://github.com/someone/fork@feature/x",
        ),
    ],
)
def test_git_requirement_is_a_pep_508_direct_reference(
    version, backend, git_ref, repository, expected
):
    assert install.build_requirement(version, backend, git_ref, repository) == expected


def test_a_pinned_version_and_a_git_ref_cannot_be_combined():
    with pytest.raises(install.InstallError) as excinfo:
        install.check_source("0.5.1", "master", install.DEFAULT_GIT_REPOSITORY)
    assert "git-ref" in str(excinfo.value)


def test_latest_and_a_git_ref_are_not_a_conflict():
    install.check_source("latest", "master", install.DEFAULT_GIT_REPOSITORY)


def test_git_repository_without_a_git_ref_is_rejected():
    """Otherwise it would be silently ignored."""
    with pytest.raises(install.InstallError) as excinfo:
        install.check_source("latest", "", "someone/fork")
    assert "git-ref" in str(excinfo.value)


def test_main_installs_from_the_git_ref_and_reports_the_commit(
    tmp_path, runner, monkeypatch, capsys
):
    executable = tmp_path / install.executable_names()[0]
    executable.touch()

    installed = []

    def record(requirements, **kwargs):
        installed.append((requirements, kwargs))

    monkeypatch.setattr(install, "pip_install", record)
    monkeypatch.setattr(install, "backend_available", lambda backend: True)
    monkeypatch.setattr(install, "selected_backend", lambda: "cryptography")
    monkeypatch.setattr(install, "resolve_executable", lambda: executable)
    monkeypatch.setattr(install, "installed_version", lambda *a: "0.5.1")
    monkeypatch.setattr(install, "installed_commit", lambda: "023b8de8dd2a")

    from test_configure import read_command_file

    assert install.main({"INPUT_GIT_REF": "master"}) == 0

    requirements, kwargs = installed[0]
    assert requirements == [
        "audible-cli[cryptography] @ git+https://github.com/mkb79/audible-cli@master"
    ]
    assert kwargs["upgrade"] is True

    # The version output carries the commit, because 0.5.1 alone would say
    # nothing about where master stood.
    published = read_command_file(runner["output"])
    assert published["audible-version"] == "0.5.1+g023b8de8dd2a"

    out = capsys.readouterr().out
    assert "git+https://github.com/mkb79/audible-cli@master" in out
    assert "0.5.1+g023b8de8dd2a" in out


def test_main_rejects_a_git_ref_combined_with_a_version(runner, no_pip, capsys):
    assert install.main({"INPUT_GIT_REF": "master", "INPUT_VERSION": "0.5.1"}) == 1
    assert "::error::" in capsys.readouterr().out
    assert runner["output"].read_text(encoding="utf-8") == ""


@pytest.mark.parametrize(
    ("distribution_version", "commit", "expected"),
    [
        ("0.5.1", None, "0.5.1"),
        ("0.5.1", "", "0.5.1"),
        ("0.5.1", "023b8de", "0.5.1+g023b8de"),
        ("0.6.0.dev1", "abc123", "0.6.0.dev1+gabc123"),
    ],
)
def test_commit_is_attached_as_a_local_version(distribution_version, commit, expected):
    assert install.build_reported_version(distribution_version, commit) == expected


def test_reported_version_stays_a_valid_pep_440_version():
    """Consumers must still be able to parse and compare what we publish."""
    packaging_version = pytest.importorskip("packaging.version")

    # An all-digit commit is the case PEP 440 would normalize into an integer;
    # the "g" prefix is what keeps every commit round-tripping unchanged.
    for commit in ("023b8de8dd2a8b2b76ed2cb1a189e4143b688e74", "0" * 40):
        reported = install.build_reported_version("0.5.1", commit)
        parsed = packaging_version.Version(reported)
        assert parsed.base_version == "0.5.1"
        assert parsed.local == f"g{commit}"
        assert parsed.local[1:] == commit
        assert parsed > packaging_version.Version("0.5.1")


def test_main_omits_the_commit_when_it_cannot_be_read(tmp_path, runner, monkeypatch, capsys):
    executable = tmp_path / install.executable_names()[0]
    executable.touch()

    monkeypatch.setattr(install, "pip_install", lambda reqs, **kw: None)
    monkeypatch.setattr(install, "backend_available", lambda backend: True)
    monkeypatch.setattr(install, "selected_backend", lambda: "cryptography")
    monkeypatch.setattr(install, "resolve_executable", lambda: executable)
    monkeypatch.setattr(install, "installed_version", lambda *a: "0.5.1")
    monkeypatch.setattr(install, "installed_commit", lambda: None)

    from test_configure import read_command_file

    assert install.main({"INPUT_GIT_REF": "master"}) == 0
    assert read_command_file(runner["output"])["audible-version"] == "0.5.1"
    capsys.readouterr()
