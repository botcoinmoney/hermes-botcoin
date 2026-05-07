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
  /botcoin scorecard [address]   Pretty-printed EIP-712 mining scorecard
  /botcoin bind <agentId>        Explicitly bind an ERC-8004 agentId
  /botcoin claim <epochs>        Claim rewards (e.g. /botcoin claim 41,42)
  /botcoin stake <amount>        Stake whole BOTCOIN (e.g. /botcoin stake 5000000)
  /botcoin unstake               Begin unstaking (24h cooldown)
  /botcoin unstake cancel        Cancel pending unstake
  /botcoin withdraw              Withdraw after cooldown
  /botcoin autostart             Schedule a Hermes cron job for autonomous mining
  /botcoin autostop              Stop the autonomous miner
  /botcoin help                  This message
"""


def _format_scorecard(payload: dict) -> str:
    """Render the EIP-712 scorecard as a compact human-readable block.

    Falls back to JSON if the payload doesn't match the documented shape.
    """
    if not isinstance(payload, dict):
        return _pretty(json.dumps(payload))
    sc = payload.get("scorecard") or payload
    if not isinstance(sc, dict):
        return _pretty(json.dumps(payload))
    miner = sc.get("miner") or "?"
    agent_id = sc.get("agentId") or "0"
    registry = sc.get("agentRegistry") or "0x0"
    lifetime = sc.get("lifetime") or {}
    per_domain = sc.get("perDomain") or {}
    issued = sc.get("issuedAt")
    valid_until = sc.get("validUntil")
    sig = sc.get("signature") or ""

    bound = "yes" if (str(agent_id) not in ("0", "", "None") and registry != "0x0") else "no"

    lines = [
        "BOTCOIN scorecard",
        f"  Miner       : {miner}",
        f"  Bound 8004  : {bound}  (agentId={agent_id}, registry={registry})",
        "",
        "  Lifetime",
        f"    attempts          : {lifetime.get('totalAttempts', 0)}",
        f"    solves            : {lifetime.get('totalSolves', 0)}",
        f"    pass_rate         : {lifetime.get('overallPassRate', 0)}",
        f"    epochs_active     : {lifetime.get('epochsActive', 0)}",
        f"    first_solve_epoch : {lifetime.get('firstSolveEpoch')}",
    ]
    if per_domain:
        lines.append("")
        lines.append("  Per-domain")
        for domain, stats in sorted(per_domain.items()):
            if not isinstance(stats, dict):
                continue
            lines.append(
                f"    {domain:24s} solves={stats.get('totalSolves', 0):<5d} "
                f"pass_rate={stats.get('passRate', 0)}"
            )
    lines.append("")
    if issued:
        lines.append(f"  issued_at : {issued}")
    if valid_until:
        lines.append(f"  valid_until: {valid_until}")
    if sig:
        lines.append(f"  signature : {sig[:18]}…{sig[-10:]} (EIP-712, BotcoinScorecard v1)")
    lines.append("")
    lines.append("  Verify: https://coordinator.agentmoney.net/agent.md")
    return "```\n" + "\n".join(lines) + "\n```"


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
        raw = t.handle_scorecard(params)
        try:
            payload = json.loads(raw)
        except Exception:
            return _pretty(raw)
        if not payload.get("ok", True):
            return _pretty(raw)
        return _format_scorecard(payload)

    if sub == "bind":
        if not rest:
            return "Usage: /botcoin bind <agentId>  e.g. /botcoin bind 30804"
        return _pretty(t.handle_bind_agent_id({"agent_id": rest[0]}))

    if sub == "autostart":
        # Optional kv args: schedule=every:90s solver=venice deliver=local
        kv: dict = {}
        for tok in rest:
            if "=" in tok:
                k, v = tok.split("=", 1)
                kv[k.strip()] = v.replace(":", " ").strip()
        return _pretty(t.handle_autostart(kv))

    if sub == "autostop":
        return _pretty(t.handle_autostop())

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
