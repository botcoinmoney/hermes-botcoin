"""``/botcoin`` slash command — the in-session UX.

Exposes a small dispatcher that maps subcommands to the same handlers used
by the agent's tools. Keeps the surface minimal: anything more elaborate
should be done through the tools so the LLM remains the one driving the
flow.
"""

from __future__ import annotations

import json
import shlex
from typing import Optional

from . import tools as t
from .status import get_status


_HELP = """\
/botcoin — BOTCOIN mining commands

  /botcoin status                Snapshot of mining state (cached 60s)
  /botcoin setup                 Run the setup checklist
  /botcoin scorecard [address]   Fetch the EIP-712 mining scorecard
  /botcoin claim <epochs>        Claim rewards (e.g. /botcoin claim 41,42)
  /botcoin stake <amount>        Stake whole BOTCOIN (e.g. /botcoin stake 5000000)
  /botcoin unstake               Begin unstaking (24h cooldown)
  /botcoin unstake cancel        Cancel pending unstake
  /botcoin withdraw              Withdraw after cooldown
  /botcoin help                  This message
"""


def _pretty(payload: str) -> str:
    """Format JSON tool output for in-chat display without losing fidelity."""
    try:
        data = json.loads(payload)
    except Exception:
        return payload
    return "```json\n" + json.dumps(data, indent=2, default=str) + "\n```"


def handle_slash(raw_args: str) -> Optional[str]:
    args = (raw_args or "").strip()
    if not args or args in {"help", "-h", "--help"}:
        return _HELP

    parts = shlex.split(args)
    sub, rest = parts[0].lower(), parts[1:]

    if sub == "status":
        snap = get_status(force_refresh=False)
        return _pretty(json.dumps(snap.to_dict()))

    if sub == "setup":
        return _pretty(t.handle_setup_check())

    if sub == "scorecard":
        params = {"address": rest[0]} if rest else {}
        return _pretty(t.handle_scorecard(params))

    if sub == "claim":
        if not rest:
            return "Usage: /botcoin claim <epochs>  e.g. /botcoin claim 41,42"
        try:
            epochs = [int(e.strip()) for e in rest[0].replace(" ", ",").split(",") if e.strip()]
        except ValueError:
            return "epoch list must be integers separated by commas (e.g. 41,42)"
        return _pretty(t.handle_claim_rewards({"epoch_ids": epochs, "include_bonus": True}))

    if sub == "stake":
        if not rest:
            return "Usage: /botcoin stake <amount>  e.g. /botcoin stake 5000000"
        return _pretty(t.handle_stake({"amount": rest[0]}))

    if sub == "unstake":
        cancel = bool(rest and rest[0].lower() == "cancel")
        return _pretty(t.handle_unstake({"cancel": cancel}))

    if sub == "withdraw":
        return _pretty(t.handle_withdraw_stake())

    return f"Unknown subcommand: {sub}\n\n{_HELP}"
