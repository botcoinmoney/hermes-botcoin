"""Hermes plugin entry point.

The repo-root ``__init__.py`` (used by ``hermes plugins install``) and the
PyPI ``hermes_agent.plugins`` entry point both delegate to
:func:`register_module` here so the registration logic lives in exactly one
place. ``register_module`` is the symbol Hermes' entry-point loader looks for.

On first registration we print the BOTCOIN ASCII banner once to whatever
file the plugin loader is currently writing to (stderr in the Hermes CLI
under normal operation). This is intentionally cheap — no I/O if Hermes
captures the stream.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from . import hooks, slash, tools, cli as cli_mod
from .schemas import ALL_TOOLS

logger = logging.getLogger(__name__)


_BANNER_PRINTED = False


def _print_banner_once() -> None:
    """Print the BOTCOIN banner to stderr on first plugin registration.

    No-op when stderr isn't a TTY (e.g. Hermes' headless CLI logging) — the
    banner is for humans, not log streams.
    """
    global _BANNER_PRINTED
    if _BANNER_PRINTED:
        return
    _BANNER_PRINTED = True
    try:
        import sys
        if not (sys.stderr and sys.stderr.isatty()):
            return
        from .banner import render
        sys.stderr.write("\n" + render() + "\n\n")
        sys.stderr.flush()
    except Exception:  # pragma: no cover — never let a banner fail the load
        pass


def register(ctx: Any) -> None:
    """Hermes plugin registration. Wires tools, slash, CLI, hooks, and skill."""

    _print_banner_once()

    # 1. Tools — diagnostic tools (status, setup_check, scorecard) are
    #    always visible so an unconfigured user can discover what's missing.
    #    Everything that signs/broadcasts is gated on a configured signer.
    handler_map = tools.HANDLERS
    for name, schema, emoji, gated in ALL_TOOLS:
        handler = handler_map.get(name)
        if handler is None:
            logger.warning("BOTCOIN: schema %s has no handler — skipping", name)
            continue
        ctx.register_tool(
            name=name,
            toolset="botcoin",
            schema=schema,
            handler=handler,
            check_fn=tools.check_configured if gated else None,
            emoji=emoji,
            description=schema.get("description", "")[:280],
        )

    # 2. /botcoin slash command
    ctx.register_command(
        "botcoin",
        handler=slash.handle_slash,
        description="BOTCOIN mining: status, setup, claim, stake, unstake, withdraw, scorecard.",
        args_hint="status|setup|claim <epochs>|stake <amount>|unstake|withdraw|scorecard",
    )

    # 3. hermes botcoin <subcmd> CLI
    ctx.register_cli_command(
        "botcoin",
        help="BOTCOIN mining utilities (status, setup, mine, claim, stake, unstake, withdraw).",
        setup_fn=cli_mod.setup_cli_parser,
        handler_fn=cli_mod.handle_cli,
        description=(
            "Mine BOTCOIN on Base by solving proof-of-inference challenges. "
            "Pair with `hermes cron` for fully autonomous mining via the "
            "hermes-botcoin-mine console script (see `hermes botcoin mine --help`)."
        ),
    )

    # 4. Bundled skill (the deep mining playbook). Registered as
    #    `botcoin:mining-strategy` — load explicitly via /skills load.
    #    SKILL.md ships INSIDE the package so it survives `pip install`
    #    (declared via [tool.setuptools.package-data] in pyproject.toml).
    skill_md = Path(__file__).resolve().parent / "skills" / "mining-strategy" / "SKILL.md"
    if skill_md.exists():
        ctx.register_skill(
            "mining-strategy",
            path=skill_md,
            description=(
                "Deep BOTCOIN mining playbook — challenge anatomy, trace requirements, "
                "constraint derivation walkthroughs, and common failure modes."
            ),
        )
    else:
        logger.warning("BOTCOIN: mining-strategy SKILL.md not found at %s", skill_md)

    # 5. Hooks: pre_llm_call (discoverability), on_session_start (onboarding).
    ctx.register_hook("pre_llm_call", hooks.pre_llm_call)
    ctx.register_hook("on_session_start", hooks.on_session_start)

    # 6. First-run onboarding via inject_message — only when unconfigured.
    from .signer import resolve_signer_mode
    if resolve_signer_mode() not in ("eoa", "bankr"):
        try:
            ctx.inject_message(
                "BOTCOIN mining is installed but not yet configured. Run `/botcoin setup` "
                "to see the checklist. You'll need either a Bankr API key or an EVM "
                "private key, plus 5,000,000 BOTCOIN staked on Base. Coordinator: "
                "https://coordinator.agentmoney.net.",
                role="user",
            )
        except Exception as exc:  # pragma: no cover — gateway mode has no CLI ref
            logger.debug("inject_message skipped: %s", exc)


# Hermes' pip-installed plugin loader looks for this symbol via importlib.metadata.
# We expose a module-with-register-attribute since `_scan_entry_points` calls
# the entry point and then attribute-checks for `register`.
class _Module:
    """Tiny shim that satisfies the entry-point contract."""

    def __init__(self):
        self.register = register


register_module = _Module()
