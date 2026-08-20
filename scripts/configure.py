"""Configure minimal Audible ADP authentication on a GitHub Actions runner.

Run as a composite-action step by ``action.yml``. The credentials are read from
the environment rather than from argv, so their values never reach a command
line, a shell script or the process table.

Authentication is optional. ``adp-token``, ``device-private-key`` and
``country-code`` form one group: supplying none of them selects install-only
mode, and supplying any of them requires all three.

The layout written here -- an ephemeral directory below RUNNER_TEMP, an
auth.json holding only the two ADP values, and a config.toml selecting a "ci"
profile -- comes from the workflow DanMat contributed in audible-cli#304.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

import _github as github

# tomllib arrived in 3.11, which is also audible-cli's minimum. Checked before
# importing it so that an unsupported python-version input produces this message
# instead of a bare ModuleNotFoundError traceback.
if sys.version_info < (3, 11):
    github.error(
        "audible-cli requires Python >=3.11,<3.15, but this step is running on "
        f"{sys.version_info[0]}.{sys.version_info[1]}. Adjust the python-version input."
    )
    raise SystemExit(1)

import tomllib  # noqa: E402

# Input names, used for error messages. A credential *value* is never part of
# any message this script produces.
ADP_TOKEN_INPUT = "adp-token"
DEVICE_PRIVATE_KEY_INPUT = "device-private-key"
COUNTRY_CODE_INPUT = "country-code"

CONFIG_DIR_ENV = "AUDIBLE_CONFIG_DIR"
CONFIG_DIR_OUTPUT = "config-dir"
CONFIG_DIR_PREFIX = "setup-audible-cli-"

AUTH_FILE_NAME = "auth.json"
CONFIG_FILE_NAME = "config.toml"
PROFILE_NAME = "ci"

# Audible marketplaces are identified by a two-letter code (us, uk, de, fr, ca,
# it, au, in, jp, es, br). This is a format check only, so that a typo such as
# "germany" fails here instead of much later inside audible-cli.
COUNTRY_CODE_RE = re.compile(r"^[a-z]{2}$")

# audible accepts a device key only if it matches
# "-----BEGIN RSA PRIVATE KEY-----...-----END RSA PRIVATE KEY-----\n" exactly.
# Measured against its validator, that means a key ending in CRLF, in more than
# two newlines, or in trailing spaces is rejected. Those all come from how the
# secret was copied rather than from the key itself, so the terminator is
# canonicalized and anything still malformed is reported here, while the value
# is being transported, instead of on the first authenticated command.
KEY_HEADER = "-----BEGIN RSA PRIVATE KEY-----"
KEY_FOOTER = "-----END RSA PRIVATE KEY-----"


class ConfigurationError(Exception):
    """An input problem that must be reported without leaking a credential."""


def is_supplied(value: str | None) -> bool:
    """Whether an optional input carries a value.

    An input that a workflow leaves out arrives as the empty string, and a
    secret that does not exist in the repository expands the same way.
    """
    return bool(value and value.strip())


def resolve_auth_mode(
    adp_token: str | None,
    device_private_key: str | None,
    country_code: str | None,
) -> bool:
    """Decide between install-only and authenticated mode.

    Returns ``True`` when authentication should be configured. Raises
    :class:`ConfigurationError` when the group is supplied only partially.
    """
    supplied = {
        ADP_TOKEN_INPUT: is_supplied(adp_token),
        DEVICE_PRIVATE_KEY_INPUT: is_supplied(device_private_key),
        COUNTRY_CODE_INPUT: is_supplied(country_code),
    }
    if not any(supplied.values()):
        return False

    missing = [name for name, present in supplied.items() if not present]
    if missing:
        raise ConfigurationError(
            f"{', '.join(supplied)} belong together: supply all three to "
            f"configure Audible authentication, or none of them to only "
            f"install audible-cli. Missing: {', '.join(missing)}."
        )
    return True


def normalize_country_code(value: str) -> str:
    """Normalize and format-check the marketplace code."""
    country_code = value.strip().lower()
    if not COUNTRY_CODE_RE.match(country_code):
        raise ConfigurationError(
            f"{COUNTRY_CODE_INPUT} must be a two-letter Audible marketplace "
            f"code such as us, uk or de."
        )
    return country_code


def normalize_private_key(value: str) -> str:
    """Return the PEM terminated by exactly one newline.

    Only the run of line-break characters after the footer is touched: a missing
    newline is added, and a terminator that is CRLF or repeated -- which audible
    rejects, and which a secret picks up from being piped or copied on Windows --
    collapses to the single newline it requires. Everything before the footer,
    including embedded CRLF line endings, is left exactly as supplied.
    """
    normalized = value.rstrip("\r\n") + "\n"

    if not normalized.startswith(KEY_HEADER):
        raise ConfigurationError(
            f"{DEVICE_PRIVATE_KEY_INPUT} must start with {KEY_HEADER!r}. "
            f"Check the secret for a leading blank line or indentation."
        )
    if not normalized.endswith(f"{KEY_FOOTER}\n"):
        raise ConfigurationError(
            f"{DEVICE_PRIVATE_KEY_INPUT} must end with a {KEY_FOOTER!r} line. "
            f"Check the secret for trailing whitespace after it."
        )
    return normalized


def normalize_adp_token(value: str) -> str:
    """Strip surrounding whitespace from the token.

    ``jq -r ... | gh secret set`` is the documented way to create the secret and
    can leave a trailing newline behind, which would corrupt the signing header.
    """
    return value.strip()


def build_auth_document(adp_token: str, device_private_key: str) -> str:
    """Serialize auth.json with exactly the two values ADP signing needs.

    json.dumps is what preserves the newlines inside the PEM; building this by
    interpolating the credentials into shell text would not.
    """
    payload = {
        "adp_token": normalize_adp_token(adp_token),
        "device_private_key": normalize_private_key(device_private_key),
    }
    return json.dumps(payload, indent=2) + "\n"


def build_config_document(country_code: str) -> str:
    """Serialize the minimal audible-cli config.toml.

    ``country_code`` has passed :func:`normalize_country_code`, so it is two
    ASCII letters and cannot contain a quote, a backslash or a line break that
    would need TOML escaping. Every other value here is a literal.
    """
    return (
        "[APP]\n"
        f'primary_profile = "{PROFILE_NAME}"\n'
        "\n"
        f"[profile.{PROFILE_NAME}]\n"
        f'auth_file = "{AUTH_FILE_NAME}"\n'
        f'country_code = "{country_code}"\n'
    )


def verify_config_document(text: str, country_code: str) -> None:
    """Parse the generated TOML back and check it says what it should."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:  # pragma: no cover - defensive
        raise ConfigurationError(f"generated {CONFIG_FILE_NAME} is invalid: {exc}") from exc

    profile = data.get("profile", {}).get(PROFILE_NAME, {})
    expected = {
        "primary profile": (data.get("APP", {}).get("primary_profile"), PROFILE_NAME),
        "auth file": (profile.get("auth_file"), AUTH_FILE_NAME),
        "country code": (profile.get("country_code"), country_code),
    }
    for label, (actual, wanted) in expected.items():
        if actual != wanted:
            raise ConfigurationError(
                f"generated {CONFIG_FILE_NAME} has an unexpected {label}"
            )


def create_config_dir(runner_temp: Path) -> Path:
    """Create the ephemeral configuration directory below the runner temp dir.

    mkdtemp gives a name no concurrent or repeated invocation can collide with,
    and on POSIX already creates it as 0700; restrict makes that mode explicit
    rather than inherited from a temporary-file implementation detail.
    """
    config_dir = Path(tempfile.mkdtemp(prefix=CONFIG_DIR_PREFIX, dir=runner_temp))
    restrict(config_dir, 0o700)
    return config_dir


def restrict(path: Path, mode: int) -> bool:
    """Apply a POSIX mode where it actually restricts access.

    On Windows os.chmod only toggles the read-only bit and grants nothing, so
    it is skipped rather than pretending the file is protected. There the files
    are protected by living in the ephemeral runner temp directory.
    """
    if os.name != "posix":
        return False
    os.chmod(path, mode)
    return True


def write_bytes_private(path: Path, data: bytes) -> None:
    """Write a file that is unreadable to other users from the moment it exists."""
    if os.name == "posix":
        handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        restrict(path, 0o600)
    else:
        path.write_bytes(data)


def write_configuration(
    config_dir: Path,
    adp_token: str,
    device_private_key: str,
    country_code: str,
) -> tuple[Path, Path]:
    """Write auth.json and config.toml into ``config_dir``."""
    auth_document = build_auth_document(adp_token, device_private_key)
    config_document = build_config_document(country_code)
    verify_config_document(config_document, country_code)

    auth_file = config_dir / AUTH_FILE_NAME
    config_file = config_dir / CONFIG_FILE_NAME

    # Written as bytes so that no platform-dependent newline translation can
    # touch the serialized credentials.
    write_bytes_private(auth_file, auth_document.encode("utf-8"))
    write_bytes_private(config_file, config_document.encode("utf-8"))
    return auth_file, config_file


def main(environ: Mapping[str, str] | None = None) -> int:
    environ = os.environ if environ is None else environ
    adp_token = environ.get("INPUT_ADP_TOKEN", "")
    device_private_key = environ.get("INPUT_DEVICE_PRIVATE_KEY", "")
    country_code_input = environ.get("INPUT_COUNTRY_CODE", "")

    try:
        authenticate = resolve_auth_mode(adp_token, device_private_key, country_code_input)
        country_code = ""
        if authenticate:
            country_code = normalize_country_code(country_code_input)
            normalize_private_key(device_private_key)
    except ConfigurationError as exc:
        github.error(str(exc))
        return 1

    if not authenticate:
        print("No Audible credentials supplied; installing audible-cli only.")
        if not github.set_output(CONFIG_DIR_OUTPUT, ""):
            github.error("GITHUB_OUTPUT is not available; the outputs could not be published.")
            return 1
        return 0

    runner_temp = environ.get("RUNNER_TEMP", "")
    if not runner_temp:
        # RUNNER_TEMP is what the runner provides; runner.temp is unavailable in
        # a job-level env block, which is why it is read here instead.
        github.error("RUNNER_TEMP is not set; this action must run on a GitHub Actions runner.")
        return 1

    try:
        config_dir = create_config_dir(Path(runner_temp))
        write_configuration(config_dir, adp_token, device_private_key, country_code)
    except (ConfigurationError, OSError) as exc:
        github.error(f"could not write the audible-cli configuration: {exc}")
        return 1

    # Fatal rather than best-effort: without this export the following steps
    # would quietly fall back to the default config directory and look like they
    # succeeded while ignoring the credentials that were just written.
    if not github.set_env(CONFIG_DIR_ENV, str(config_dir)):
        github.error(
            f"GITHUB_ENV is not available, so {CONFIG_DIR_ENV} could not be exported "
            f"to the following steps."
        )
        return 1
    if not github.set_output(CONFIG_DIR_OUTPUT, str(config_dir)):
        github.error("GITHUB_OUTPUT is not available; the outputs could not be published.")
        return 1

    print(f"Configured the {PROFILE_NAME} profile for marketplace {country_code}.")
    print(f"{CONFIG_DIR_ENV}={config_dir}")
    if os.name != "posix":
        github.notice(
            "POSIX file modes are not applied on Windows; the generated "
            "credentials rely on the ephemeral runner temp directory."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
