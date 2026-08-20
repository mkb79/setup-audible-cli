"""Make the action's helper scripts importable the way the action runs them.

``action.yml`` invokes ``python "$GITHUB_ACTION_PATH/scripts/<name>.py"``, which
puts ``scripts/`` on ``sys.path``. Mirroring that here keeps the imports in the
tests identical to the ones the scripts perform at runtime.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
