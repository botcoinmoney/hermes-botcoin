"""FastMCP server exposing every BOTCOIN tool over MCP stdio.

Every tool delegates to the same handler the Hermes plugin uses, so the
behavior, error shape, and rate-limit handling are identical across both
distribution channels.

Run via ``hermes-botcoin-mcp`` (console script) or
``python -m hermes_botcoin_mcp.server``.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)


def _json_loads_or_dict(payload: Any) -> dict:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except Exception:
            return {"raw": payload}
    return {"value": payload}


def main() -> int:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover — install hint only
        print(
            "ERROR: the `mcp` package is required. Install with: pip install mcp",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc

    from hermes_botcoin import tools as t  # imports the shared library

    server = FastMCP(
        name="botcoin",
        instructions=(
            "Mine BOTCOIN by solving proof-of-inference challenges on Base. "
            "Workflow: (1) botcoin_setup_check to verify config; (2) botcoin_status "
            "for live state; (3) botcoin_request_challenge to fetch a challenge "
            "(YOU are the solver); (4) botcoin_submit_artifact with your artifact "
            "+ reasoning trace; (5) botcoin_post_receipt to broadcast the on-chain "
            "credit. Claim with botcoin_claim_rewards after epochs finalize."
        ),
    )

    @server.tool()
    def botcoin_status(force_refresh: bool = False) -> dict:
        """Snapshot of the BOTCOIN mining state (cached 60s)."""
        return _json_loads_or_dict(t.handle_status({"force_refresh": force_refresh}))

    @server.tool()
    def botcoin_setup_check() -> dict:
        """Diagnose whether this client is fully configured for mining."""
        return _json_loads_or_dict(t.handle_setup_check())

    @server.tool()
    def botcoin_scorecard(address: str | None = None, as_of: int | None = None) -> dict:
        """Fetch the EIP-712 signed mining scorecard for an address (defaults to configured miner)."""
        return _json_loads_or_dict(t.handle_scorecard({"address": address, "as_of": as_of}))

    @server.tool()
    def botcoin_request_challenge(client_nonce: str | None = None) -> dict:
        """Request a fresh BOTCOIN mining challenge. YOU are the solver — return the artifact + trace via botcoin_submit_artifact."""
        return _json_loads_or_dict(t.handle_request_challenge({"client_nonce": client_nonce}))

    @server.tool()
    def botcoin_submit_artifact(
        challenge_id: str,
        nonce: str,
        challenge_manifest_hash: str,
        artifact: str,
        reasoning_trace: list[dict],
        model_version: str,
        submitted_answers: dict[str, str] | list[Any] | None = None,
        pool: bool = False,
    ) -> dict:
        """Submit a solved artifact + reasoning trace for verification.

        ``submitted_answers`` is preferred as a flat object keyed by question
        id — for example ``{"q01": "EntityName", "q05": "247"}``. A list is
        also accepted and mapped to ``q01``/``q02``/... by 1-indexed position
        for backwards compatibility with array-style callers.
        """
        return _json_loads_or_dict(t.handle_submit_artifact({
            "challenge_id": challenge_id,
            "nonce": nonce,
            "challenge_manifest_hash": challenge_manifest_hash,
            "artifact": artifact,
            "reasoning_trace": reasoning_trace,
            "model_version": model_version,
            "submitted_answers": submitted_answers,
            "pool": pool,
        }))

    @server.tool()
    def botcoin_post_receipt(
        transaction: dict,
        vouch_transaction: dict | None = None,
        wait_for_confirmation: bool = True,
    ) -> dict:
        """Broadcast the coordinator-signed transactions to Base.

        - ``transaction`` (required): the mining receipt — broadcast synchronously.
        - ``vouch_transaction`` (optional): the ERC-8004 ReputationRegistry
          calldata returned alongside the receipt on a successful submit.
          Broadcast fire-and-forget so it never blocks the next mining round.
        """
        return _json_loads_or_dict(t.handle_post_receipt({
            "transaction": transaction,
            "vouch_transaction": vouch_transaction,
            "wait_for_confirmation": wait_for_confirmation,
        }))

    @server.tool()
    def botcoin_claim_rewards(
        epoch_ids: list[int],
        include_bonus: bool = True,
        pool_target: str | None = None,
    ) -> dict:
        """Claim BOTCOIN rewards for one or more finalized epochs."""
        return _json_loads_or_dict(t.handle_claim_rewards({
            "epoch_ids": epoch_ids,
            "include_bonus": include_bonus,
            "pool_target": pool_target,
        }))

    @server.tool()
    def botcoin_stake(amount: str) -> dict:
        """Stake BOTCOIN on V3. Tier 1 minimum: 5,000,000 whole BOTCOIN. Approve + stake in two txs."""
        return _json_loads_or_dict(t.handle_stake({"amount": amount}))

    @server.tool()
    def botcoin_unstake(cancel: bool = False) -> dict:
        """Begin unstaking (24h cooldown). Pass cancel=True to revert a pending unstake."""
        return _json_loads_or_dict(t.handle_unstake({"cancel": cancel}))

    @server.tool()
    def botcoin_withdraw_stake() -> dict:
        """Withdraw previously-unstaked BOTCOIN after the 24h cooldown."""
        return _json_loads_or_dict(t.handle_withdraw_stake())

    @server.tool()
    def botcoin_bind_agent_id(agent_id: str | int) -> dict:
        """Explicitly bind an ERC-8004 agentId to the configured miner address.

        Walks /v1/agent/bind/nonce → personal_sign → /v1/agent/bind/verify.
        """
        return _json_loads_or_dict(t.handle_bind_agent_id({"agent_id": agent_id}))

    @server.tool()
    def botcoin_autostart(
        schedule: str = "every 90s",
        solver: str | None = None,
        model: str | None = None,
        max_per_day: int | None = None,
        deliver: str = "local",
    ) -> dict:
        """Schedule a Hermes cron job that runs `hermes-botcoin-mine` every cycle.

        Idempotent: returns the existing job's id if one is already scheduled.
        Cost ceiling enforced via `BOTCOIN_MAX_ATTEMPTS_PER_DAY` (default 100).
        Only available when invoked from inside the Hermes runtime.
        """
        return _json_loads_or_dict(t.handle_autostart({
            "schedule": schedule, "solver": solver, "model": model,
            "max_per_day": max_per_day, "deliver": deliver,
        }))

    @server.tool()
    def botcoin_autostop() -> dict:
        """Stop the BOTCOIN autonomous miner cron job (no-op if not scheduled)."""
        return _json_loads_or_dict(t.handle_autostop())

    server.run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
