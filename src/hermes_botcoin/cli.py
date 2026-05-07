"""``hermes botcoin <subcmd>`` CLI surface.

Uses ``argparse`` to match Hermes' own subcommand registration pattern. Two
entry points are exposed:

1. :func:`setup_cli_parser` / :func:`handle_cli` — wired into Hermes via
   ``ctx.register_cli_command`` so users get ``hermes botcoin status``,
   ``hermes botcoin mine``, etc., as native top-level CLI verbs.
2. :func:`cron_entry` — the ``hermes-botcoin-mine`` console script published
   in pyproject.toml. Designed for ``no_agent=True`` cron jobs so a
   permanent autonomous miner can run with zero LLM overhead inside Hermes.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from typing import Any, Optional

from . import tools as t
from .mining import autonomous_mine_one


def setup_cli_parser(parser: argparse.ArgumentParser) -> None:
    """Build the argparse tree for ``hermes botcoin``."""
    sub = parser.add_subparsers(dest="botcoin_cmd", required=True, metavar="<command>")

    p_status = sub.add_parser("status", help="Show mining snapshot (cached 60s)")
    p_status.add_argument("--refresh", action="store_true", help="Bypass cache")
    p_status.set_defaults(func=lambda a: print(t.handle_status({"force_refresh": a.refresh})))

    p_setup = sub.add_parser("setup", help="Run the configuration checklist")
    p_setup.set_defaults(func=lambda a: print(t.handle_setup_check()))

    p_score = sub.add_parser("scorecard", help="Fetch EIP-712 signed scorecard")
    p_score.add_argument("--address", default=None)
    p_score.set_defaults(func=lambda a: print(t.handle_scorecard({"address": a.address})))

    p_mine = sub.add_parser("mine", help="Mine one round (or loop) using the configured solver")
    p_mine.add_argument("--loop", action="store_true", help="Run continuously until interrupted")
    p_mine.add_argument("--max-attempts", type=int, default=0,
                        help="Stop after N attempts (0 = unlimited; --loop required)")
    p_mine.add_argument("--cooldown", type=int, default=65,
                        help="Seconds to wait between attempts (must be >= 60)")
    p_mine.add_argument("--solver", default=os.environ.get("BOTCOIN_SOLVER_PROVIDER", "venice"),
                        choices=["venice", "anthropic", "openai", "openrouter", "deepseek"],
                        help="LLM provider used to solve in headless mode (venice recommended for privacy + cost)")
    p_mine.add_argument("--model", default=os.environ.get("BOTCOIN_SOLVER_MODEL"))
    p_mine.set_defaults(func=_handle_mine)

    p_claim = sub.add_parser("claim", help="Claim mining rewards for one or more epochs")
    p_claim.add_argument("--epochs", required=True,
                         help="Comma-separated epoch IDs (e.g. 41,42)")
    p_claim.add_argument("--no-bonus", action="store_true", help="Skip bonus epoch claim")
    p_claim.add_argument("--pool-target", default=None)
    p_claim.set_defaults(func=_handle_claim)

    p_stake = sub.add_parser("stake", help="Stake whole BOTCOIN")
    p_stake.add_argument("--amount", required=True, help="Whole BOTCOIN, e.g. 5000000")
    p_stake.set_defaults(func=lambda a: print(t.handle_stake({"amount": a.amount})))

    p_un = sub.add_parser("unstake", help="Begin unstaking (24h cooldown)")
    p_un.add_argument("--cancel", action="store_true", help="Cancel pending unstake")
    p_un.set_defaults(func=lambda a: print(t.handle_unstake({"cancel": a.cancel})))

    p_wd = sub.add_parser("withdraw", help="Withdraw after cooldown")
    p_wd.set_defaults(func=lambda a: print(t.handle_withdraw_stake()))


def handle_cli(args: argparse.Namespace) -> int:
    """Dispatch table — argparse sets ``args.func`` for each subcommand."""
    func = getattr(args, "func", None)
    if not callable(func):
        print("usage: hermes botcoin <command> --help", file=sys.stderr)
        return 2
    func(args)
    return 0


# ---------------------------------------------------------------------------
# Subcommand bodies (extracted for testability)


def _handle_mine(args: argparse.Namespace) -> None:
    if args.cooldown < 60:
        print("ERROR: --cooldown must be >= 60s (coordinator rate limit).", file=sys.stderr)
        sys.exit(2)

    attempt = 0
    while True:
        attempt += 1
        out = autonomous_mine_one(
            solver_provider=args.solver,
            solver_model=args.model,
            log_prefix=f"attempt-{attempt}",
        )
        print(json.dumps(out, default=str))
        if not args.loop:
            return
        if args.max_attempts and attempt >= args.max_attempts:
            return
        time.sleep(args.cooldown)


def _handle_claim(args: argparse.Namespace) -> None:
    try:
        epochs = [int(x.strip()) for x in args.epochs.split(",") if x.strip()]
    except ValueError:
        print("ERROR: --epochs must be a comma-separated list of integers.", file=sys.stderr)
        sys.exit(2)
    print(t.handle_claim_rewards({
        "epoch_ids": epochs,
        "include_bonus": not args.no_bonus,
        "pool_target": args.pool_target,
    }))


# ---------------------------------------------------------------------------
# `hermes-botcoin-mine` console script — for cron `no_agent=True` jobs


def cron_entry() -> int:
    """Standalone CLI for cron-driven autonomous mining.

    Usage:
        hermes-botcoin-mine [--solver anthropic|openai|openrouter|deepseek]
                            [--model NAME] [--max-attempts N] [--cooldown S]

    Each invocation runs at most ``--max-attempts`` rounds (default 1), so
    a Hermes cron job at e.g. ``every 90s`` triggers a single attempt cycle
    per tick — matching the coordinator's per-miner rate window.
    """
    parser = argparse.ArgumentParser(prog="hermes-botcoin-mine")
    parser.add_argument("--solver", default=os.environ.get("BOTCOIN_SOLVER_PROVIDER", "venice"),
                        choices=["venice", "anthropic", "openai", "openrouter", "deepseek"])
    parser.add_argument("--model", default=os.environ.get("BOTCOIN_SOLVER_MODEL"))
    parser.add_argument("--max-attempts", type=int, default=1,
                        help="Maximum solve attempts per invocation (default 1; ideal for cron)")
    parser.add_argument("--cooldown", type=int, default=65,
                        help="Seconds between attempts when --max-attempts > 1")
    parser.add_argument("--quiet", action="store_true",
                        help="Only emit JSON output on success/fail (good for cron deliver: hooks)")
    args = parser.parse_args()

    if not args.quiet:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )

    attempts = max(1, args.max_attempts)
    last: Optional[dict[str, Any]] = None
    for i in range(attempts):
        last = autonomous_mine_one(
            solver_provider=args.solver,
            solver_model=args.model,
            log_prefix=f"cron-{i + 1}/{attempts}",
        )
        if not args.quiet:
            print(json.dumps(last, default=str))
        if i < attempts - 1:
            time.sleep(max(60, args.cooldown))

    if args.quiet and last is not None:
        print(json.dumps(last, default=str))
    return 0 if last and last.get("ok") else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(cron_entry())
