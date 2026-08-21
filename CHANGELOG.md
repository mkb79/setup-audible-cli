# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog], and this project adheres to
[Semantic Versioning].

## [Unreleased]

## [1.0.1] - 2026-08-21

### Changed

- Action description shortened to fit the GitHub Marketplace's 125-character
  limit, and the auth mode described as request signing rather than ADP ([#5])

## [1.0.0] - 2026-08-20

Derived from the GitHub Actions workflow [@DanMat] contributed in
[audible-cli#304], which grew out of his request in [audible-cli#303].

### Added

- Composite action that installs `audible-cli` and puts `audible` on `PATH` for
  the following workflow steps
- `version` input taking `latest` or one exact release, not a pip requirement
  expression
- `git-ref` and `git-repository` inputs to install from a branch, tag or commit
  instead of PyPI; the resolved commit is reported in `audible-version` as a
  PEP 440 local version
- `python-version` input, default `3.14`, applied through `actions/setup-python`
- `crypto-backend` input taking `cryptography`, `pycryptodome` or `none`,
  verified to be importable after installation
- Optional authentication through `adp-token`, `device-private-key` and
  `country-code`, which are required together or not at all
- A minimal `auth.json` and `config.toml` written to a fresh directory below
  `RUNNER_TEMP`, with `AUDIBLE_CONFIG_DIR` exported through `$GITHUB_ENV`
- The private key's trailing line breaks normalized to the single newline
  `audible` accepts, leaving the rest of the key untouched
- Outputs `audible-version`, `audible-path` and `config-dir`
- Unit tests and a cross-platform workflow covering Ubuntu, macOS and Windows
- Commit-SHA pins for every action used, kept current by Dependabot
- MIT license

### Security

- Credentials reach the helper scripts only as environment variables and are
  serialized by Python, never interpolated into shell text
- Validation errors name inputs, never values, and no credential is exposed
  through an output
- Configuration directory `700` and files `600` where POSIX modes apply, and not
  claimed on Windows where they would grant nothing
- Setting the action up performs no Audible API request

[Keep a Changelog]: https://keepachangelog.com/en/1.1.0/
[Semantic Versioning]: https://semver.org/spec/v2.0.0.html
[@DanMat]: https://github.com/DanMat
[audible-cli#303]: https://github.com/mkb79/audible-cli/issues/303
[audible-cli#304]: https://github.com/mkb79/audible-cli/pull/304

[Unreleased]: https://github.com/mkb79/setup-audible-cli/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/mkb79/setup-audible-cli/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/mkb79/setup-audible-cli/releases/tag/v1.0.0

[#5]: https://github.com/mkb79/setup-audible-cli/pull/5
