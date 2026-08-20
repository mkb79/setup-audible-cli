# setup-audible-cli

Set up [`audible-cli`](https://github.com/mkb79/audible-cli) in a GitHub Actions
workflow, and optionally configure the minimal Audible ADP authentication needed
to run authenticated commands.

```yaml
- uses: mkb79/setup-audible-cli@v1
  with:
    adp-token: ${{ secrets.AUDIBLE_ADP_TOKEN }}
    device-private-key: ${{ secrets.AUDIBLE_DEVICE_PRIVATE_KEY }}
    country-code: ${{ vars.AUDIBLE_COUNTRY_CODE }}

- run: audible library list
```

After the action has run, `audible` is on `PATH` and every following step in the
job uses the generated configuration.

```yaml
- run: audible library export

- run: audible api catalog/products/B07J2M2VC7 --param response_groups=media
```

## Contents

- [Usage](#usage)
- [Inputs](#inputs)
- [Outputs](#outputs)
- [Checking Audible API responses in CI](#checking-audible-api-responses-in-ci)
- [Creating the secrets](#creating-the-secrets)
- [Security](#security)
- [What this action does and does not do](#what-this-action-does-and-does-not-do)
- [Platform support](#platform-support)
- [Versioning](#versioning)
- [Development](#development)
- [Acknowledgements](#acknowledgements)
- [License](#license)

## Usage

### Install only

Authentication is optional. Without credentials the action just installs
`audible-cli`, which is enough for commands that need no account:

```yaml
- uses: mkb79/setup-audible-cli@v1

- run: audible --help
```

### With authentication

Supplying credentials additionally writes an ephemeral `auth.json` and
`config.toml` and points `AUDIBLE_CONFIG_DIR` at them:

```yaml
- uses: mkb79/setup-audible-cli@v1
  with:
    adp-token: ${{ secrets.AUDIBLE_ADP_TOKEN }}
    device-private-key: ${{ secrets.AUDIBLE_DEVICE_PRIVATE_KEY }}
    country-code: ${{ vars.AUDIBLE_COUNTRY_CODE }}

- run: audible library list
```

`adp-token`, `device-private-key` and `country-code` form one group. Supply all
three, or none of them. Supplying only some of them fails with an error naming
the missing inputs — never their values.

### Pinning a version

```yaml
- uses: mkb79/setup-audible-cli@v1
  with:
    version: "0.5.1"
```

`version` accepts `latest` or one exact release. It is deliberately not a pip
requirement expression: `>=0.5`, `0.5.*` and similar are rejected rather than
given a meaning you did not ask for.

### Installing from a branch instead of PyPI

`git-ref` installs from the `audible-cli` repository at a branch, tag or commit,
which is how you try out an unreleased fix before it ships:

```yaml
- uses: mkb79/setup-audible-cli@v1
  with:
    git-ref: master
```

```yaml
- uses: mkb79/setup-audible-cli@v1
  with:
    git-ref: 023b8de8dd2a8b2b76ed2cb1a189e4143b688e74
```

`git-ref` and `version` are two ways of saying the same thing, so setting both is
an error rather than a silent winner. A ref is always reinstalled, since a branch
moves under you.

`git-repository` points the install at a different GitHub repository, for testing
a fork or a contributor's branch:

```yaml
- uses: mkb79/setup-audible-cli@v1
  with:
    git-repository: someone/audible-cli
    git-ref: feature/their-branch
```

When installing from a ref, `audible-version` carries the commit pip resolved
to, as a PEP 440 local version:

```
0.5.1+g023b8de8dd2a8b2b76ed2cb1a189e4143b688e74
```

Without it the output would just say `0.5.1` — the version that ref's
`pyproject.toml` happens to declare, which says nothing about where the branch
stood. This form stays a valid, comparable version, and the release part is
recoverable:

```python
from packaging.version import Version

v = Version("0.5.1+g023b8de8dd2a8b2b76ed2cb1a189e4143b688e74")
v.base_version   # "0.5.1"
v.local[1:]      # the commit, ready for git checkout
```

The `g` follows `git describe` and setuptools-scm. It is not decoration: PEP 440
normalizes an all-digit local segment into an integer, which would eat the
leading zeroes of a commit that happens to contain no letters.

Installing from a ref also builds the package from source, so it is slower than
a wheel from PyPI.

> ⚠️ Installing from a ref runs that ref's code, including its build backend. Do
> not point `git-repository` at a repository you do not trust, and never combine
> an untrusted ref with real Audible credentials — the credentials are in the
> environment of the job that code runs in.

### Choosing the crypto backend

`audible` accelerates its RSA request signing with a native library. The default
is `cryptography`:

```yaml
- uses: mkb79/setup-audible-cli@v1
  with:
    crypto-backend: pycryptodome
```

Use `pycryptodome` on platforms `cryptography` publishes no wheel for. The action
verifies after installation that the backend is really importable, because
`audible` otherwise falls back silently to its slower pure-Python implementation.

Use `none` to install no crypto extra at all:

```yaml
- uses: mkb79/setup-audible-cli@v1
  with:
    crypto-backend: none
```

That installs plain `audible-cli`, leaving `audible` on its pure-Python
implementation. It is slower at signing, but it needs no wheel and no compiler,
which is useful on an architecture neither library ships for.

This input decides which backend is *installed*. `audible` itself picks the
provider it uses, preferring `cryptography` over `pycryptodome` over its
pure-Python fallback, so a library that is already in the environment stays the
one in use — including with `none`. The action logs which provider `audible`
actually selected rather than assuming the request was decisive.

> Released `audible-cli` versions up to and including 0.5.1 do not declare a
> `pycryptodome` extra. When the extra is missing, the action installs
> `audible[pycryptodome]` directly and says so in the log, so the backend you
> asked for is the backend you get.

### Choosing the Python version

The action runs `actions/setup-python` itself, so a separate setup step is not
needed. The default is Python 3.14 — the version `audible-cli` builds its own
releases with, and one every GitHub-hosted runner keeps in its tool cache, so
choosing it costs no setup time. `audible-cli` supports 3.11 to 3.14, and an
unsupported version is rejected before anything is installed:

```yaml
- uses: mkb79/setup-audible-cli@v1
  with:
    python-version: "3.11"
```

This interpreter only runs `audible-cli`. It is set up by this action and is
independent of whatever Python your own project uses.

## Inputs

| Name | Description | Required | Default |
| --- | --- | --- | --- |
| `version` | Version of audible-cli to install. Either `latest` for the current PyPI release, or an exact version such as `0.5.1`. | No | `latest` |
| `git-ref` | Install from this branch, tag or commit of the audible-cli repository instead of from PyPI. Cannot be combined with `version`. | No | `""` |
| `git-repository` | GitHub repository to install from, in `owner/name` form. Only applies when `git-ref` is set. | No | `mkb79/audible-cli` |
| `python-version` | Python version used to run audible-cli. Anything from 3.11 to 3.14 works. | No | `"3.14"` |
| `crypto-backend` | Crypto backend to install for audible-cli. One of `cryptography`, `pycryptodome`, or `none` to install no crypto extra at all, which leaves audible on its slower pure-Python implementation. | No | `cryptography` |
| `adp-token` | Audible ADP token. **Sensitive**, pass it from a secret. Requires `device-private-key` and `country-code`. | No | `""` |
| `device-private-key` | Multiline RSA private key used for ADP request signing. **Sensitive**, pass it from a secret. Requires `adp-token` and `country-code`. | No | `""` |
| `country-code` | Audible marketplace to use, for example `us`, `uk` or `de`. Required when credentials are supplied. | No | `""` |

`country-code` has no default on purpose. Silently choosing the wrong
marketplace would be worse than asking you for it.

Surrounding whitespace is removed from `adp-token`, because piping a value into
`gh secret set` can leave a trailing newline behind. The private key is never
modified apart from the final-newline rule described under
[Security](#security).

## Outputs

| Name | Description |
| --- | --- |
| `audible-version` | The installed audible-cli distribution version. With `git-ref`, the resolved commit is attached as a PEP 440 local version, for example `0.5.1+g023b8de…`. |
| `audible-path` | Path to the installed audible executable. |
| `config-dir` | The generated audible-cli configuration directory. Empty in install-only mode. |

```yaml
- uses: mkb79/setup-audible-cli@v1
  id: audible

- run: echo "Installed audible-cli ${{ steps.audible.outputs.audible-version }}"
```

No output ever carries a credential.

## Checking Audible API responses in CI

`audible api` sends a request to an Audible endpoint and prints the response.
That is useful if your project depends on a particular response shape: you can
call the endpoints you rely on from a scheduled workflow and notice when an
upstream response stops matching your expectations, instead of finding out from
a user.

```yaml
name: Audible API contract

on:
  workflow_dispatch:
  schedule:
    - cron: "0 6 * * 1"

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7

      - uses: mkb79/setup-audible-cli@v1
        with:
          adp-token: ${{ secrets.AUDIBLE_ADP_TOKEN }}
          device-private-key: ${{ secrets.AUDIBLE_DEVICE_PRIVATE_KEY }}
          country-code: ${{ vars.AUDIBLE_COUNTRY_CODE }}

      - name: Check that the fields we rely on are still there
        run: |
          audible api library \
            --param response_groups=product_desc,product_attrs \
            --param num_results=10 \
            --output library.json
          python check_response_shape.py library.json
```

The Audible API is not a publicly documented or officially supported API. It is
reverse-engineered, and it can change without notice — which is precisely why
watching it from CI can be worth doing.

## Creating the secrets

Authenticate once locally with `audible quickstart` (or
`audible manage auth-file add`). That writes an `auth.json` into your config
directory. A runner needs only two values out of it:

- `adp_token`
- `device_private_key`

There is no reason to upload the whole file or the whole config directory: the
access token, refresh token, website cookies and account details in it are not
needed to sign API requests.

With [`gh`](https://cli.github.com/) and [`jq`](https://jqlang.github.io/jq/),
naming the target repository explicitly:

```shell
jq -r .adp_token ~/.audible/auth.json |
  gh secret set AUDIBLE_ADP_TOKEN -R OWNER/REPO

jq -r .device_private_key ~/.audible/auth.json |
  gh secret set AUDIBLE_DEVICE_PRIVATE_KEY -R OWNER/REPO

gh variable set AUDIBLE_COUNTRY_CODE -R OWNER/REPO --body "us"
```

Adjust `~/.audible/auth.json` if your config directory is somewhere else, and
the `"us"` marketplace code to your own.

> ⚠️ Use `-R OWNER/REPO`. Without it, `gh` picks the repository from whatever
> directory you happen to be in. Standing in your config directory is the
> harmless outcome — `gh` just refuses, because it is not a Git repository.
> Standing in some *other* checkout is the one that hurts: the command succeeds
> and writes your Audible credentials to a repository you did not mean to give
> them to.

If you are already inside the target repository, the flag is redundant and you
can leave it off:

```shell
jq -r .adp_token ~/.audible/auth.json | gh secret set AUDIBLE_ADP_TOKEN
```

`jq` adds its own newline, so the secret can end up with one more line break
than the key had. That is fine: the action normalizes whatever follows the
`-----END RSA PRIVATE KEY-----` line to the single newline `audible` accepts,
including a Windows `\r\n`.

## Security

**`adp_token` and `device_private_key` are sensitive.** Together they are enough
to make authenticated requests against your Audible account, so treat them the
way you would treat a password.

- Store both as **GitHub Actions Secrets**. Never commit them, never paste them
  into a workflow file, and never write them into a step's `run:` block.
- Do not echo or print them, and do not enable shell tracing in a step that has
  them in its environment.
- Do not upload the generated `auth.json` or `config.toml` as an artifact, and
  do not commit them. They are written below the runner's temporary directory
  and disappear with the runner.
- **Do not expose them to arbitrary pull-request code.** A workflow that runs
  with these secrets should be triggered by `workflow_dispatch`, `schedule`, or
  pushes to a trusted branch — not by `pull_request` from forks, and not by
  `pull_request_target`.
- Run authenticated workflows only in trusted contexts, and only in repositories
  whose write access you control.
- `country-code` is **not** sensitive. A GitHub Actions **Variable**
  (`vars.AUDIBLE_COUNTRY_CODE`) is the right place for it.

How the action handles them:

- Credentials reach the helper scripts only as environment variables, never as
  command-line arguments and never interpolated into shell text, so they do not
  show up in a command line or in shell tracing. They are still present in that
  one step's environment, which anything running as the same user on the runner
  could read — that is inherent to handing a value to a program.
- `auth.json` is written by Python's JSON serializer and contains exactly
  `adp_token` and `device_private_key` — no access token, no refresh token, no
  cookies, no customer or device information.
- The private key is stored as supplied, except that whatever line breaks
  follow the `-----END RSA PRIVATE KEY-----` line collapse to the single newline
  `audible` requires. That is the only edit, and it is what makes a key survive
  being piped through `jq` or copied on Windows. Line endings inside the key are
  left alone. A key `audible` could not accept at all — a missing or damaged
  header or footer, or trailing whitespace after it — is reported as an error
  rather than written into an `auth.json` that would fail later.
- On Linux and macOS the configuration directory is created with mode `700` and
  the files with mode `600`. On Windows, POSIX modes grant nothing, so they are
  not applied and the files rely on the ephemeral runner temporary directory
  instead. The action says so in the log rather than implying protection it does
  not provide.
- Validation errors name the inputs that are missing or malformed. They never
  contain a credential value.

## What this action does and does not do

It does:

- install `audible-cli` with the requested version and crypto backend
- put `audible` on `PATH` for every following step
- optionally write a minimal `auth.json` and `config.toml` into a fresh
  directory below `RUNNER_TEMP`
- export `AUDIBLE_CONFIG_DIR` through `$GITHUB_ENV`, so every following step in
  the job picks the configuration up automatically

It does **not**:

- contact Audible. Setting the action up performs no Audible API request and no
  login. Only a command you run afterwards, such as `audible library list`, does.
- validate your credentials. Whether they work is discovered by the first
  authenticated command you run, not here.
- touch a config directory you already have, or write anything outside
  `RUNNER_TEMP`. In install-only mode it also leaves an `AUDIBLE_CONFIG_DIR`
  you set yourself alone, so `config-dir` being empty means "this run generated
  nothing", not "nothing is configured".

## Platform support

Exercised in CI on GitHub-hosted `ubuntu-latest`, `macos-latest` and
`windows-latest`, with every crypto backend. Steps use `shell: bash`, which is
available on all three; self-hosted Windows runners without Git Bash are not
supported.

Supported Python versions follow `audible-cli`: 3.11 up to and including 3.14,
all of which are in every hosted runner's tool cache. An unsupported
`python-version` is rejected before anything is installed.

## Versioning

Releases follow Semantic Versioning. A movable major tag tracks the newest v1
release, which is what most workflows should use:

```yaml
- uses: mkb79/setup-audible-cli@v1
```

To pin exactly, use a full release tag:

```yaml
- uses: mkb79/setup-audible-cli@v1.0.0
```

Breaking changes to inputs, outputs, or the generated files come with a new
major version. See [CHANGELOG.md](CHANGELOG.md).

## Development

```shell
python -m pip install pytest
python -m pytest tests
```

The unit tests use fake credentials and make no network requests. The workflow
in `.github/workflows/test.yml` additionally runs the action through
`uses: ./` on all three platforms, in install-only and in authenticated mode,
and checks the generated files structurally without printing their contents.

The actions this repository uses are pinned to commit SHAs, with the release
they correspond to in a trailing comment. Dependabot watches those comments and
opens a pull request when a pin falls behind.

## Acknowledgements

This action exists because of [@DanMat](https://github.com/DanMat). He opened
[audible-cli#303](https://github.com/mkb79/audible-cli/issues/303) asking for a
documented way to run `audible-cli` headless, made the case for it out of
[earshot](https://github.com/DanMat/earshot), and then wrote
[audible-cli#304](https://github.com/mkb79/audible-cli/pull/304) — the workflow
this action is derived from.

The ephemeral `auth.json` and `config.toml`, the `RUNNER_TEMP` and `$GITHUB_ENV`
handling, and the trailing-newline rule for the device key all trace back to that
pull request. This action packages them so nobody has to copy the YAML around.

## License

[MIT](LICENSE).

`audible-cli` itself is licensed separately, under AGPL-3.0-only. This action
installs it at runtime rather than bundling it, so the two licenses apply to
their own code.
