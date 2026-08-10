"""Re-export the shared timezone knob into stoiclife.

The resolver lives in the openclaw workspace (`scripts/active_tz.py`) because three repos
need the same answer — stoiclife, fitbit-sync and the workspace scripts all write day keys
into the same `~/.openclaw/stoic/stoic_journal.db`, and they must agree on what "today"
means or the trigger matrix joins the wrong rows.

A shim rather than a symlink: this repo has its own deploy key and remote, and a symlink
pointing outside the repo root would resolve to nothing in any other checkout.

    from _tz import TZ
"""

import sys
from pathlib import Path

_RESOLVER_DIR = Path.home() / ".openclaw" / "workspace" / "scripts"
if str(_RESOLVER_DIR) not in sys.path:
    sys.path.insert(0, str(_RESOLVER_DIR))

from active_tz import TZ, active_tz, active_tz_name  # noqa: E402,F401
