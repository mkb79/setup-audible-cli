"""Obviously fake credentials for the tests.

These are shaped like the real values but cannot be mistaken for them, and are
never sent anywhere: no test in this suite performs a network request.
"""

from __future__ import annotations

FAKE_ADP_TOKEN = "{enc:NOT-A-REAL-ADP-TOKEN}{key:FAKE}{iv:FAKE}{name:FAKE}{serial:Mg==}"

# No trailing newline on purpose, so the tests exercise the case where the
# action has to append one.
FAKE_PRIVATE_KEY = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "NOTAREALKEYnotarealkeyNOTAREALKEY000000000000\n"
    "NOTAREALKEYnotarealkeyNOTAREALKEY111111111111\n"
    "-----END RSA PRIVATE KEY-----"
)

# Substrings that must never turn up in a log line, an error message or a
# workflow command file.
SECRET_MARKERS = ("NOT-A-REAL-ADP-TOKEN", "NOTAREALKEYnotarealkey")
