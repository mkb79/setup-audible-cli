"""Unit tests for scripts/configure.py.

Nothing here contacts Audible or any other network service.
"""

from __future__ import annotations

import json
import os
import stat
import tomllib

import pytest

import configure
from fake_credentials import FAKE_ADP_TOKEN, FAKE_PRIVATE_KEY, SECRET_MARKERS

POSIX_ONLY = pytest.mark.skipif(
    os.name != "posix", reason="POSIX file modes are not meaningful here"
)


# --------------------------------------------------------------------------
# authentication input group
# --------------------------------------------------------------------------


def test_install_only_when_nothing_is_supplied():
    assert configure.resolve_auth_mode("", "", "") is False


def test_install_only_when_inputs_are_absent():
    assert configure.resolve_auth_mode(None, None, None) is False


def test_complete_tuple_is_accepted():
    assert configure.resolve_auth_mode(FAKE_ADP_TOKEN, FAKE_PRIVATE_KEY, "de") is True


@pytest.mark.parametrize(
    ("adp_token", "private_key", "country_code", "missing"),
    [
        (FAKE_ADP_TOKEN, "", "", ["device-private-key", "country-code"]),
        ("", FAKE_PRIVATE_KEY, "", ["adp-token", "country-code"]),
        ("", "", "de", ["adp-token", "device-private-key"]),
        (FAKE_ADP_TOKEN, FAKE_PRIVATE_KEY, "", ["country-code"]),
        (FAKE_ADP_TOKEN, "", "de", ["device-private-key"]),
        ("", FAKE_PRIVATE_KEY, "de", ["adp-token"]),
    ],
    ids=[
        "adp-token-alone",
        "device-private-key-alone",
        "country-code-alone",
        "credentials-without-country-code",
        "missing-device-private-key",
        "missing-adp-token",
    ],
)
def test_partial_tuple_is_rejected(adp_token, private_key, country_code, missing):
    with pytest.raises(configure.ConfigurationError) as excinfo:
        configure.resolve_auth_mode(adp_token, private_key, country_code)

    message = str(excinfo.value)
    for name in missing:
        assert name in message


def test_whitespace_only_input_does_not_count_as_supplied():
    assert configure.resolve_auth_mode("   ", "\n", "\t") is False


def test_rejection_message_never_contains_a_credential():
    with pytest.raises(configure.ConfigurationError) as excinfo:
        configure.resolve_auth_mode(FAKE_ADP_TOKEN, FAKE_PRIVATE_KEY, "")

    message = str(excinfo.value)
    for marker in SECRET_MARKERS:
        assert marker not in message


# --------------------------------------------------------------------------
# country code
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [("de", "de"), ("DE", "de"), (" us ", "us"), ("Uk", "uk")],
)
def test_country_code_is_normalized(supplied, expected):
    assert configure.normalize_country_code(supplied) == expected


@pytest.mark.parametrize("supplied", ["germany", "d", "", "d1", "deu", "d e"])
def test_invalid_country_code_is_rejected(supplied):
    with pytest.raises(configure.ConfigurationError):
        configure.normalize_country_code(supplied)


# --------------------------------------------------------------------------
# private key normalization
# --------------------------------------------------------------------------


def test_final_newline_is_appended_when_missing():
    normalized = configure.normalize_private_key(FAKE_PRIVATE_KEY)
    assert normalized == FAKE_PRIVATE_KEY + "\n"


def test_existing_final_newline_is_not_duplicated():
    already = FAKE_PRIVATE_KEY + "\n"
    assert configure.normalize_private_key(already) == already


def test_repeated_normalization_is_stable():
    once = configure.normalize_private_key(FAKE_PRIVATE_KEY)
    assert configure.normalize_private_key(once) == once


@pytest.mark.parametrize("terminator", ["", "\n", "\n\n", "\n\n\n", "\r\n", "\r\n\r\n"])
def test_any_terminator_collapses_to_exactly_one_newline(terminator):
    """audible accepts only a footer followed by a single plain newline."""
    normalized = configure.normalize_private_key(FAKE_PRIVATE_KEY + terminator)
    assert normalized == FAKE_PRIVATE_KEY + "\n"
    assert not normalized.endswith("\n\n")
    assert not normalized.endswith("\r\n")


def test_embedded_crlf_line_endings_are_preserved():
    """Only the final line ending matters to audible; the body is left alone."""
    internal = FAKE_PRIVATE_KEY.replace("\n", "\r\n")
    normalized = configure.normalize_private_key(internal)
    assert normalized == internal + "\n"
    assert "\r\n" in normalized


def test_trailing_whitespace_after_the_footer_is_rejected():
    with pytest.raises(configure.ConfigurationError):
        configure.normalize_private_key(FAKE_PRIVATE_KEY + "   \n")


def test_leading_whitespace_before_the_header_is_rejected():
    with pytest.raises(configure.ConfigurationError):
        configure.normalize_private_key("  " + FAKE_PRIVATE_KEY)


def test_key_rejection_never_contains_the_key():
    with pytest.raises(configure.ConfigurationError) as excinfo:
        configure.normalize_private_key("  " + FAKE_PRIVATE_KEY)
    for marker in SECRET_MARKERS:
        assert marker not in str(excinfo.value)


def test_main_rejects_a_malformed_key_without_creating_anything(runner, capsys):
    exit_code = configure.main(
        {
            "INPUT_ADP_TOKEN": FAKE_ADP_TOKEN,
            "INPUT_DEVICE_PRIVATE_KEY": FAKE_PRIVATE_KEY + "  \n",
            "INPUT_COUNTRY_CODE": "de",
            "RUNNER_TEMP": str(runner["temp"]),
        }
    )
    assert exit_code == 1
    assert list(runner["temp"].iterdir()) == []
    captured = capsys.readouterr()
    assert "::error::" in captured.out
    for marker in SECRET_MARKERS:
        assert marker not in captured.out


def test_embedded_newlines_are_preserved():
    normalized = configure.normalize_private_key(FAKE_PRIVATE_KEY)
    assert normalized.count("\n") == FAKE_PRIVATE_KEY.count("\n") + 1
    assert normalized.splitlines() == FAKE_PRIVATE_KEY.splitlines()


def test_adp_token_surrounding_whitespace_is_removed():
    assert configure.normalize_adp_token(f"  {FAKE_ADP_TOKEN}\n") == FAKE_ADP_TOKEN


# --------------------------------------------------------------------------
# auth.json
# --------------------------------------------------------------------------


def test_auth_document_contains_exactly_the_two_credentials():
    document = json.loads(configure.build_auth_document(FAKE_ADP_TOKEN, FAKE_PRIVATE_KEY))
    assert set(document) == {"adp_token", "device_private_key"}


def test_auth_document_is_valid_json_and_round_trips_the_key():
    document = json.loads(configure.build_auth_document(FAKE_ADP_TOKEN, FAKE_PRIVATE_KEY))
    assert document["adp_token"] == FAKE_ADP_TOKEN
    assert document["device_private_key"] == FAKE_PRIVATE_KEY + "\n"
    assert document["device_private_key"].startswith("-----BEGIN RSA PRIVATE KEY-----\n")
    assert document["device_private_key"].endswith("-----END RSA PRIVATE KEY-----\n")


def test_auth_document_omits_every_other_audible_field():
    document = json.loads(configure.build_auth_document(FAKE_ADP_TOKEN, FAKE_PRIVATE_KEY))
    for unwanted in (
        "access_token",
        "refresh_token",
        "website_cookies",
        "customer_info",
        "device_info",
        "expires",
        "locale_code",
        "store_authentication_cookie",
    ):
        assert unwanted not in document


# --------------------------------------------------------------------------
# config.toml
# --------------------------------------------------------------------------


def test_config_document_parses_and_selects_the_ci_profile():
    document = tomllib.loads(configure.build_config_document("de"))
    assert document["APP"]["primary_profile"] == "ci"
    assert document["profile"]["ci"]["auth_file"] == "auth.json"


@pytest.mark.parametrize("country_code", ["de", "us", "uk", "jp", "br"])
def test_country_code_is_propagated_into_the_config(country_code):
    document = tomllib.loads(configure.build_config_document(country_code))
    assert document["profile"]["ci"]["country_code"] == country_code


def test_config_document_verification_accepts_its_own_output():
    configure.verify_config_document(configure.build_config_document("de"), "de")


def test_config_document_verification_rejects_a_mismatch():
    with pytest.raises(configure.ConfigurationError):
        configure.verify_config_document(configure.build_config_document("de"), "us")


# --------------------------------------------------------------------------
# writing the configuration
# --------------------------------------------------------------------------


@pytest.fixture
def spaced_dir(tmp_path):
    """A configuration directory whose path contains a space."""
    directory = tmp_path / "runner temp" / "audible config"
    directory.mkdir(parents=True)
    return directory


def test_write_configuration_creates_both_files(spaced_dir):
    auth_file, config_file = configure.write_configuration(
        spaced_dir, FAKE_ADP_TOKEN, FAKE_PRIVATE_KEY, "de"
    )
    assert auth_file.is_file()
    assert config_file.is_file()
    assert " " in str(auth_file)

    document = json.loads(auth_file.read_text(encoding="utf-8"))
    assert document["device_private_key"] == FAKE_PRIVATE_KEY + "\n"
    assert tomllib.loads(config_file.read_text(encoding="utf-8"))["profile"]["ci"][
        "country_code"
    ] == "de"


def test_written_auth_file_has_no_platform_newline_translation(spaced_dir):
    auth_file, _ = configure.write_configuration(
        spaced_dir, FAKE_ADP_TOKEN, FAKE_PRIVATE_KEY, "de"
    )
    assert b"\r\n" not in auth_file.read_bytes()


@POSIX_ONLY
def test_written_files_are_not_readable_by_others(spaced_dir):
    auth_file, config_file = configure.write_configuration(
        spaced_dir, FAKE_ADP_TOKEN, FAKE_PRIVATE_KEY, "de"
    )
    assert stat.S_IMODE(auth_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(config_file.stat().st_mode) == 0o600


@POSIX_ONLY
def test_created_config_dir_is_private(tmp_path):
    runner_temp = tmp_path / "runner temp"
    runner_temp.mkdir()
    config_dir = configure.create_config_dir(runner_temp)
    assert stat.S_IMODE(config_dir.stat().st_mode) == 0o700


def test_created_config_dirs_do_not_collide(tmp_path):
    first = configure.create_config_dir(tmp_path)
    second = configure.create_config_dir(tmp_path)
    assert first != second


# --------------------------------------------------------------------------
# main()
# --------------------------------------------------------------------------


@pytest.fixture
def runner(tmp_path, monkeypatch):
    """A stand-in for the runner's workflow command files."""
    github_env = tmp_path / "github env"
    github_output = tmp_path / "github output"
    runner_temp = tmp_path / "runner temp"
    github_env.touch()
    github_output.touch()
    runner_temp.mkdir()
    monkeypatch.setenv("GITHUB_ENV", str(github_env))
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    return {
        "env": github_env,
        "output": github_output,
        "temp": runner_temp,
    }


def read_command_file(path):
    """Parse the runner's ``name<<delimiter`` form back into a mapping."""
    values = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    index = 0
    while index < len(lines):
        name, _, delimiter = lines[index].partition("<<")
        index += 1
        collected = []
        while index < len(lines) and lines[index] != delimiter:
            collected.append(lines[index])
            index += 1
        index += 1
        values[name] = "\n".join(collected)
    return values


def test_main_install_only_writes_an_empty_config_dir(runner, capsys):
    assert configure.main({"RUNNER_TEMP": str(runner["temp"])}) == 0

    assert read_command_file(runner["output"]) == {"config-dir": ""}
    assert runner["env"].read_text(encoding="utf-8") == ""
    assert list(runner["temp"].iterdir()) == []
    assert "::error::" not in capsys.readouterr().out


def test_main_writes_the_configuration_and_exports_the_config_dir(runner, capsys):
    exit_code = configure.main(
        {
            "INPUT_ADP_TOKEN": FAKE_ADP_TOKEN,
            "INPUT_DEVICE_PRIVATE_KEY": FAKE_PRIVATE_KEY,
            "INPUT_COUNTRY_CODE": "DE",
            "RUNNER_TEMP": str(runner["temp"]),
        }
    )
    assert exit_code == 0

    exported = read_command_file(runner["env"])
    published = read_command_file(runner["output"])
    config_dir = runner["temp"] / os.path.basename(exported["AUDIBLE_CONFIG_DIR"])

    assert exported["AUDIBLE_CONFIG_DIR"] == str(config_dir)
    assert published["config-dir"] == str(config_dir)

    document = json.loads((config_dir / "auth.json").read_text(encoding="utf-8"))
    assert document["adp_token"] == FAKE_ADP_TOKEN
    assert document["device_private_key"] == FAKE_PRIVATE_KEY + "\n"

    config = tomllib.loads((config_dir / "config.toml").read_text(encoding="utf-8"))
    assert config["profile"]["ci"]["country_code"] == "de"

    capsys.readouterr()


def test_main_rejects_a_partial_tuple_without_creating_anything(runner, capsys):
    exit_code = configure.main(
        {
            "INPUT_ADP_TOKEN": FAKE_ADP_TOKEN,
            "RUNNER_TEMP": str(runner["temp"]),
        }
    )
    assert exit_code == 1
    assert list(runner["temp"].iterdir()) == []
    assert runner["env"].read_text(encoding="utf-8") == ""
    assert runner["output"].read_text(encoding="utf-8") == ""

    captured = capsys.readouterr()
    assert "::error::" in captured.out
    assert "device-private-key" in captured.out


def test_main_requires_runner_temp_in_auth_mode(runner, capsys):
    exit_code = configure.main(
        {
            "INPUT_ADP_TOKEN": FAKE_ADP_TOKEN,
            "INPUT_DEVICE_PRIVATE_KEY": FAKE_PRIVATE_KEY,
            "INPUT_COUNTRY_CODE": "de",
        }
    )
    assert exit_code == 1
    assert "RUNNER_TEMP" in capsys.readouterr().out


def test_main_never_leaks_a_credential(runner, capsys):
    configure.main(
        {
            "INPUT_ADP_TOKEN": FAKE_ADP_TOKEN,
            "INPUT_DEVICE_PRIVATE_KEY": FAKE_PRIVATE_KEY,
            "INPUT_COUNTRY_CODE": "de",
            "RUNNER_TEMP": str(runner["temp"]),
        }
    )
    captured = capsys.readouterr()
    written = (
        captured.out
        + captured.err
        + runner["env"].read_text(encoding="utf-8")
        + runner["output"].read_text(encoding="utf-8")
    )
    for marker in SECRET_MARKERS:
        assert marker not in written


def test_main_fails_when_the_config_dir_cannot_be_exported(runner, monkeypatch, capsys):
    """A configuration the following steps cannot see is not a success."""
    monkeypatch.delenv("GITHUB_ENV")

    exit_code = configure.main(
        {
            "INPUT_ADP_TOKEN": FAKE_ADP_TOKEN,
            "INPUT_DEVICE_PRIVATE_KEY": FAKE_PRIVATE_KEY,
            "INPUT_COUNTRY_CODE": "de",
            "RUNNER_TEMP": str(runner["temp"]),
        }
    )
    assert exit_code == 1
    assert "AUDIBLE_CONFIG_DIR" in capsys.readouterr().out


def test_main_fails_when_outputs_cannot_be_published(runner, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_OUTPUT")
    assert configure.main({"RUNNER_TEMP": str(runner["temp"])}) == 1
    assert "::error::" in capsys.readouterr().out
