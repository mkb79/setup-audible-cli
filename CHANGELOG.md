# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-08-20

Derived from the GitHub Actions workflow [@DanMat](https://github.com/DanMat)
contributed in [audible-cli#304](https://github.com/mkb79/audible-cli/pull/304),
which grew out of his request in
[audible-cli#303](https://github.com/mkb79/audible-cli/issues/303).

### Added

- Composite action `mkb79/setup-audible-cli` that installs `audible-cli` and
  makes the `audible` executable available to the following workflow steps.
- `version` input accepting `latest` or one exact release. Pip requirement
  expressions such as `>=0.5` are rejected rather than given a surprising
  meaning.
- `git-ref` and `git-repository` inputs for installing from a branch, tag or
  commit of the audible-cli repository instead of from PyPI, built as a PEP 508
  direct reference. Both are validated against git's own ref rules and GitHub's
  `owner/name` form, and combining `git-ref` with `version` is rejected rather
  than silently resolved. With `git-ref`, the `audible-version` output carries
  the resolved commit as a PEP 440 local version, for example
  `0.5.1+g023b8de…`, because a branch otherwise reports whatever version its
  `pyproject.toml` declares.
- `python-version` input, defaulting to `3.14` — the version `audible-cli`
  builds its own releases with — used with `actions/setup-python` so consumers
  do not need their own setup step. An interpreter outside the
  range `audible-cli` supports is rejected before anything is installed.
- `crypto-backend` input accepting `cryptography` (default), `pycryptodome`, or
  `none` to install no crypto extra at all and leave `audible` on its
  pure-Python implementation.
  After installing, the action verifies that the requested backend is really
  importable and installs `audible[<backend>]` — pinned to the `audible` the
  install just resolved — if the selected `audible-cli` release does not declare
  the matching extra, so the backend can never fall back silently to the
  pure-Python implementation.
- Optional Audible ADP authentication through the `adp-token`,
  `device-private-key` and `country-code` inputs. The three form one group:
  supplying none installs only, supplying any requires all three.
- Generation of a minimal `auth.json` containing exactly `adp_token` and
  `device_private_key`, and a `config.toml` selecting a `ci` profile for the
  requested marketplace, in a fresh directory below `RUNNER_TEMP`.
- Normalization of whatever line breaks follow the private key's
  `-----END RSA PRIVATE KEY-----` line down to the single newline `audible`
  accepts, so a key that picked up a `\r\n` or an extra newline from `jq` or
  from being copied on Windows still works. Line endings inside the key are left
  untouched, and a key with a damaged envelope is reported while the inputs are
  being read instead of failing on the first authenticated command.
- A log line naming the crypto provider `audible` actually selected, which is
  not necessarily the requested one: `audible` prefers `cryptography` when both
  libraries are present.
- `AUDIBLE_CONFIG_DIR` exported through `$GITHUB_ENV`, so every following step
  in the job uses the generated configuration.
- Outputs `audible-version`, `audible-path` and `config-dir`, the last of which
  is empty in install-only mode.
- Unit tests for input validation, requirement building, credential
  serialization and the runner file-command helpers, plus a cross-platform
  workflow that runs the action on `ubuntu-latest`, `macos-latest` and
  `windows-latest` with fake credentials.

- Commit-SHA pins for every action used, with a Dependabot configuration that
  keeps them current.
- MIT license.

### Security

- Credentials are passed to the helper scripts only as environment variables and
  serialized by Python, so they never appear in a command line, in shell text or
  in the process table.
- Validation errors name the inputs involved and never contain a credential
  value, and no credential is exposed through an action output.
- The configuration directory is created with mode `700` and its files with mode
  `600` where POSIX modes are meaningful. On Windows they are not applied,
  because they would grant no protection there.
- Setting the action up performs no Audible API request.

[Unreleased]: https://github.com/mkb79/setup-audible-cli/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/mkb79/setup-audible-cli/releases/tag/v1.0.0
