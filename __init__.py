"""Hermes plugin entry — re-exports ``register`` so the loader finds it.

When a user runs ``hermes plugins install botcoinmoney/hermes-botcoin``, the
loader expects this module's ``register(ctx)`` function at the repo root
(see hermes_cli/plugins.py:_scan_directory). We delegate to the canonical
implementation in :mod:`hermes_botcoin.plugin_entry` so behavior is shared
with the pip-install path.
"""

from __future__ import annotations

import sys
from pathlib import Path

# When loaded by `hermes plugins install`, this package is dropped at
# ~/.hermes/plugins/botcoin/ and the framework only adds that dir to
# sys.path. The actual library lives under src/hermes_botcoin — make it
# importable without requiring a pip install.
_REPO_ROOT = Path(__file__).resolve().parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from hermes_botcoin.plugin_entry import register  # noqa: E402

__all__ = ["register"]
