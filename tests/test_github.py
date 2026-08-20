"""Unit tests for scripts/_github.py, the runner file-command helpers."""

from __future__ import annotations

import pytest

import _github as github
from fake_credentials import FAKE_PRIVATE_KEY


def parse(text):
    """Parse the runner's ``name<<delimiter`` form back into a mapping."""
    values = {}
    lines = text.splitlines()
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


def test_value_round_trips():
    assert parse(github.format_key_value("config-dir", "/tmp/a b/c")) == {
        "config-dir": "/tmp/a b/c"
    }


def test_value_containing_an_equals_sign_round_trips():
    assert parse(github.format_key_value("name", "a=b=c"))["name"] == "a=b=c"


def test_multiline_value_round_trips():
    assert parse(github.format_key_value("name", FAKE_PRIVATE_KEY))["name"] == FAKE_PRIVATE_KEY


def test_empty_value_round_trips():
    assert parse(github.format_key_value("config-dir", "")) == {"config-dir": ""}


def test_each_entry_uses_a_fresh_delimiter():
    first = github.format_key_value("a", "1").splitlines()[0]
    second = github.format_key_value("a", "1").splitlines()[0]
    assert first != second


def test_set_output_appends_to_the_output_file(tmp_path, monkeypatch):
    output = tmp_path / "github output"
    output.touch()
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    assert github.set_output("audible-version", "0.5.1") is True
    assert github.set_output("audible-path", "/usr/bin/audible") is True

    values = parse(output.read_text(encoding="utf-8"))
    assert values == {"audible-version": "0.5.1", "audible-path": "/usr/bin/audible"}


def test_set_env_appends_to_the_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / "github env"
    env_file.touch()
    monkeypatch.setenv("GITHUB_ENV", str(env_file))

    assert github.set_env("AUDIBLE_CONFIG_DIR", "/tmp/runner temp/audible") is True
    values = parse(env_file.read_text(encoding="utf-8"))
    assert values["AUDIBLE_CONFIG_DIR"] == "/tmp/runner temp/audible"


def test_written_files_use_line_feeds_only(tmp_path, monkeypatch):
    output = tmp_path / "github output"
    output.touch()
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    github.set_output("audible-version", "0.5.1")
    assert b"\r\n" not in output.read_bytes()


def test_add_path_writes_one_line(tmp_path, monkeypatch):
    path_file = tmp_path / "github path"
    path_file.touch()
    monkeypatch.setenv("GITHUB_PATH", str(path_file))

    assert github.add_path(tmp_path / "python env" / "bin") is True
    assert path_file.read_text(encoding="utf-8") == f"{tmp_path / 'python env' / 'bin'}\n"


def test_add_path_rejects_a_line_break(tmp_path, monkeypatch):
    path_file = tmp_path / "github path"
    path_file.touch()
    monkeypatch.setenv("GITHUB_PATH", str(path_file))

    with pytest.raises(github.GitHubFileError):
        github.add_path("/tmp/one\n/tmp/two")


@pytest.mark.parametrize("writer", ["set_output", "set_env"])
def test_writers_are_inert_outside_a_runner(writer, monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.delenv("GITHUB_ENV", raising=False)
    assert getattr(github, writer)("name", "value") is False


def test_add_path_is_inert_outside_a_runner(monkeypatch):
    monkeypatch.delenv("GITHUB_PATH", raising=False)
    assert github.add_path("/usr/bin") is False


@pytest.mark.parametrize(("emit", "prefix"), [("error", "::error::"), ("notice", "::notice::")])
def test_annotations_are_written_to_stdout(emit, prefix, capsys):
    getattr(github, emit)("something happened")
    captured = capsys.readouterr()
    assert captured.out == f"{prefix}something happened\n"
    assert captured.err == ""
