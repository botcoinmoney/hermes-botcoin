"""hermes-botcoin: native BOTCOIN mining for Hermes Agent.

The plugin is loaded by Hermes via the `register(ctx)` callable exported from
the repo root `__init__.py` (when installed via `hermes plugins install`),
or via the `hermes_agent.plugins` entry point exposed in `pyproject.toml`
(when pip-installed). Both routes resolve to the same `register_module`
in :mod:`hermes_botcoin.plugin_entry`.
"""

__version__ = "0.1.1"
__all__ = ["__version__"]
