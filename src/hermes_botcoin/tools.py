"""Tool handlers exposed to the Hermes agent.

Every handler returns a JSON string (Hermes contract: `tools/registry.dispatch`
expects ``str``). Errors are caught and returned as ``{"ok": false, "error": "..."}``
so a single tool call never crashes the agent loop.

Design note: Hermes is the solver. The plugin **does not** call any LLM API.
The agent receives the challenge from `botcoin_request_challenge`, produces
the artifact + reasoning trace itself (using whatever provider the user has
configured in Hermes), then submits with `botcoin_submit_artifact` and
broadcasts with `botcoin_post_receipt`.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any, Optional

from .auth import AuthSession
from .coordinator import Coordinator, CoordinatorError, is_retryable, respect_retry_after
from . import cron_jobs as cron_lifecycle
from .signer import Signer, SignerError, SignerNotConfigured, make_signer, resolve_signer_mode
from .status import get_status, invalidate_cache
from .trace import normalize_trace, serialize_submitted_answers

logger = logging.getLogger(__name__)


_BOTCOIN_TOKEN = "0xA601877977340862Ca67f816eb079958E5bd0BA3"  # Base mainnet
_MINING_V3 = "0xB2fbe0DB5A99B4E2Dd294dE64cEd82740b53A2Ea"
_BONUS = "0xA185fE194A7F603b7287BC0abAeBA1b896a36Ba8"
_TIER_1_WHOLE = 5_000_000  # whole BOTCOIN required for Tier 1


# Source-of-truth tier table from https://agentmoney.net/skill.md (verified 2026-05-07).
# These are *defaults* shown in the skill — the on-chain values may differ; for the
# authoritative live tier table, call MiningContractV3.tierCount() / getTier(i).
_TIER_TABLE: list[tuple[int, int]] = [
    (5_000_000, 100),
    (10_000_000, 205),
    (25_000_000, 520),
    (50_000_000, 1_075),
    (100_000_000, 2_200),
]


def _credits_for_stake(staked_whole: int) -> int:
    """Return the credits-per-solve a miner with `staked_whole` BOTCOIN earns."""
    earned = 0
    for threshold, credits in _TIER_TABLE:
        if staked_whole >= threshold:
            earned = credits
        else:
            break
    return earned


# ---------------------------------------------------------------------------
# Module-level singletons (rebuilt on auth reset / config change)


_COORD: Optional[Coordinator] = None
_SIGNER: Optional[Signer] = None
_AUTH: Optional[AuthSession] = None


def _coord() -> Coordinator:
    global _COORD
    if _COORD is None:
        _COORD = Coordinator()
    return _COORD


def _signer() -> Signer:
    global _SIGNER
    if _SIGNER is None:
        _SIGNER = make_signer()
    return _SIGNER


def _auth() -> AuthSession:
    global _AUTH
    if _AUTH is None:
        agent_id = os.environ.get("BOTCOIN_AGENT_ID") or None
        _AUTH = AuthSession(_coord(), _signer(), agent_id=agent_id)
    return _AUTH


def _reset_clients() -> None:
    global _COORD, _SIGNER, _AUTH
    _COORD = _SIGNER = _AUTH = None
    invalidate_cache()


# ---------------------------------------------------------------------------
# Helpers


def _ok(payload: dict[str, Any]) -> str:
    payload.setdefault("ok", True)
    return json.dumps(payload, default=str)


def _err(message: str, **extra: Any) -> str:
    body: dict[str, Any] = {"ok": False, "error": message}
    body.update(extra)
    return json.dumps(body, default=str)


def _safe_call(func, *args, **kwargs):
    """Run a coordinator call, surfacing structured errors as JSON tool output."""
    try:
        return func(*args, **kwargs), None
    except CoordinatorError as exc:
        return None, _err(
            str(exc),
            status=exc.status,
            route=exc.route,
            error_code=exc.error,
            retryable=is_retryable(exc),
            retry_after_seconds=exc.retry_after_seconds,
            body=exc.body,
        )
    except SignerError as exc:
        return None, _err(f"signer: {exc}")
    except Exception as exc:  # pragma: no cover — defensive belt
        logger.exception("unhandled error in BOTCOIN tool")
        return None, _err(f"unexpected: {exc}")


# ---------------------------------------------------------------------------
# Tool handlers — read-only


def handle_status(params: dict | None = None, **_: Any) -> str:
    params = params or {}
    snap = get_status(force_refresh=bool(params.get("force_refresh")))
    return _ok(snap.to_dict())


def handle_setup_check(params: dict | None = None, **_: Any) -> str:
    """Run a structured pre-flight checklist."""
    checklist: list[dict[str, Any]] = []
    next_steps: list[str] = []

    # 1. Signer configuration — single resolver shared with status, hooks, make_signer
    signer_mode = resolve_signer_mode()
    forced = (os.environ.get("BOTCOIN_SIGNER") or "").strip().lower() or None
    checklist.append({
        "check": "signer_configured",
        "ok": signer_mode in ("eoa", "bankr"),
        "mode": signer_mode,
        "forced": forced,
    })
    if signer_mode not in ("eoa", "bankr"):
        next_steps.append(
            "Set BOTCOIN_MINER_KEY (preferred) or BANKR_API_KEY in ~/.hermes/.env. "
            "Re-run hermes plugins install botcoinmoney/hermes-botcoin if you skipped the prompts."
        )

    # 2. Resolve miner address
    miner_addr: Optional[str] = None
    if signer_mode:
        try:
            miner_addr = _signer().address()
        except (SignerError, SignerNotConfigured) as exc:
            checklist.append({"check": "signer_init", "ok": False, "error": str(exc)})
            next_steps.append("Fix the signer error above before continuing.")
    if miner_addr:
        checklist.append({"check": "miner_address", "ok": True, "address": miner_addr})

    # 3. Coordinator reachable + epoch
    coord = _coord()
    try:
        ep = coord.epoch()
        checklist.append({
            "check": "coordinator_reachable",
            "ok": True,
            "epoch_id": ep.get("epochId"),
            "next_epoch_at": ep.get("nextEpochStartTimestamp"),
            "url": coord.base_url,
        })
    except CoordinatorError as exc:
        checklist.append({
            "check": "coordinator_reachable",
            "ok": False,
            "error": str(exc),
            "url": coord.base_url,
        })
        next_steps.append("Coordinator is unreachable — check COORDINATOR_URL and your network.")

    # 4. Stake check + ETH balance — both via direct eth_call to Base.
    if miner_addr and any(c.get("check") == "coordinator_reachable" and c.get("ok") for c in checklist):
        try:
            from .signer import _rpc_call
            rpc = os.environ.get("BASE_RPC_URL") or "https://mainnet.base.org"
            # stakedAmount(address) on MiningContractV3 — selector 0xf9931855
            addr_hex = miner_addr.lower().replace("0x", "").rjust(64, "0")
            staked_hex = _rpc_call(
                rpc, "eth_call",
                [{"to": _MINING_V3, "data": "0xf9931855" + addr_hex}, "latest"],
            )
            staked_wei = int(staked_hex, 16) if staked_hex else 0
            staked_whole = staked_wei // (10 ** 18)
            tier = _credits_for_stake(staked_whole)
            checklist.append({
                "check": "stake_meets_tier_1",
                "ok": staked_whole >= _TIER_1_WHOLE,
                "staked_whole": staked_whole,
                "tier_1_minimum_whole": _TIER_1_WHOLE,
                "credits_per_solve": tier,
            })
            if staked_whole < _TIER_1_WHOLE:
                next_steps.append(
                    f"Stake at least {_TIER_1_WHOLE:,} BOTCOIN via botcoin_stake to start mining "
                    f"(currently staked: {staked_whole:,})."
                )
        except Exception as exc:
            checklist.append({"check": "stake_meets_tier_1", "ok": False, "error": str(exc)})

        if signer_mode == "eoa":
            try:
                from .signer import _rpc_call
                rpc = os.environ.get("BASE_RPC_URL") or "https://mainnet.base.org"
                bal_hex = _rpc_call(rpc, "eth_getBalance", [miner_addr, "latest"])
                wei = int(bal_hex, 16) if bal_hex else 0
                checklist.append({
                    "check": "eth_for_gas",
                    "ok": wei > 1_000_000_000_000_000,
                    "wei": str(wei),
                    "eth": f"{wei / 10**18:.6f}",
                })
                if wei <= 1_000_000_000_000_000:
                    next_steps.append(
                        "Top up at least 0.001 ETH on Base for gas (each tx is < $0.01)."
                    )
            except Exception as exc:
                checklist.append({"check": "eth_for_gas", "ok": False, "error": str(exc)})

    return _ok({"checklist": checklist, "next_steps": next_steps})


def handle_scorecard(params: dict | None = None, **_: Any) -> str:
    params = params or {}
    address = params.get("address")
    if not address:
        try:
            address = _signer().address()
        except (SignerError, SignerNotConfigured) as exc:
            return _err(f"no address: {exc}")
    as_of = params.get("as_of")
    data, err = _safe_call(_coord().scorecard, address, as_of=int(as_of) if as_of else None)
    if err:
        return err
    return _ok({"scorecard": data})


# ---------------------------------------------------------------------------
# Tool handlers — mining


def handle_request_challenge(params: dict | None = None, **_: Any) -> str:
    params = params or {}
    try:
        signer = _signer()
        miner = signer.address()
        bearer = _auth().bearer()
    except (SignerError, SignerNotConfigured) as exc:
        return _err(f"signer not ready: {exc}")
    except CoordinatorError as exc:
        return _err(f"auth failed: {exc}", status=exc.status, retryable=is_retryable(exc),
                    retry_after_seconds=exc.retry_after_seconds)

    nonce = (params.get("client_nonce") or "")[:64] or uuid.uuid4().hex[:32]

    for attempt in range(3):
        try:
            ch = _coord().challenge(miner, bearer=bearer, nonce=nonce)
        except CoordinatorError as exc:
            if exc.status == 401:
                _auth().reset()
                bearer = _auth().bearer(force=True)
                continue
            if is_retryable(exc) and attempt < 2:
                wait = respect_retry_after(exc, attempt=attempt)
                logger.info("challenge retry in %.1fs (%s)", wait, exc.error)
                time.sleep(wait)
                continue
            return _err(str(exc), status=exc.status, error_code=exc.error,
                        retry_after_seconds=exc.retry_after_seconds, body=exc.body)
        break
    else:
        return _err("challenge: max retries exhausted")

    # Echo the *exact* nonce the agent must use on submit, plus inline guidance.
    out = {
        "nonce_echoed": nonce,
        "miner": miner,
        "challenge": ch,
        "_solver_instructions": (
            "Read the doc, answer the questions, and produce a single-line artifact "
            "satisfying every constraint. Build a trace with extract_fact + compute_logic "
            "steps citing paragraph_N. Submit using the same challengeId, nonce, and "
            "challengeManifestHash via botcoin_submit_artifact."
        ),
    }
    return _ok(out)


def handle_submit_artifact(params: dict | None = None, **_: Any) -> str:
    params = params or {}
    required = ["challenge_id", "nonce", "challenge_manifest_hash", "artifact",
                "reasoning_trace", "model_version"]
    missing = [k for k in required if k not in params or params[k] in (None, "")]
    if missing:
        return _err(f"missing required parameters: {missing}")

    try:
        signer = _signer()
        miner = signer.address()
        bearer = _auth().bearer()
    except (SignerError, SignerNotConfigured) as exc:
        return _err(f"signer not ready: {exc}")
    except CoordinatorError as exc:
        return _err(f"auth failed: {exc}")

    trace = normalize_trace(params["reasoning_trace"])
    artifact = str(params["artifact"]).strip()
    answers = serialize_submitted_answers(params.get("submitted_answers"))

    for attempt in range(3):
        try:
            result = _coord().submit(
                miner=miner,
                challenge_id=str(params["challenge_id"]),
                artifact=artifact,
                nonce=str(params["nonce"]),
                challenge_manifest_hash=str(params["challenge_manifest_hash"]),
                model_version=str(params["model_version"]),
                reasoning_trace=trace,
                bearer=bearer,
                submitted_answers=answers,
                pool=bool(params.get("pool", False)),
            )
        except CoordinatorError as exc:
            if exc.status == 401:
                _auth().reset()
                bearer = _auth().bearer(force=True)
                continue
            if is_retryable(exc) and attempt < 2:
                time.sleep(respect_retry_after(exc, attempt=attempt))
                continue
            return _err(str(exc), status=exc.status, error_code=exc.error, body=exc.body,
                        retry_after_seconds=exc.retry_after_seconds)
        break
    else:
        return _err("submit: max retries exhausted")

    # `result` carries pass/fail + (on pass) signed receipt + ready-to-broadcast tx.
    return _ok({"result": result})


def handle_post_receipt(params: dict | None = None, **_: Any) -> str:
    params = params or {}
    tx = params.get("transaction")
    if not isinstance(tx, dict):
        return _err("missing transaction object")
    vouch_tx = params.get("vouch_transaction")
    wait = bool(params.get("wait_for_confirmation", True))

    try:
        signer = _signer()
    except (SignerError, SignerNotConfigured) as exc:
        return _err(f"signer not ready: {exc}")

    out: dict[str, Any] = {"signer_mode": signer.mode}
    try:
        out["receipt"] = signer.submit_tx(tx, wait=wait)
    except SignerError as exc:
        return _err(f"receipt broadcast failed: {exc}")

    # Vouch is fire-and-forget — never block the next mining round on it.
    if isinstance(vouch_tx, dict) and vouch_tx.get("to") and vouch_tx.get("data"):
        try:
            out["vouch"] = signer.submit_tx(vouch_tx, wait=False)
        except SignerError as exc:
            out["vouch"] = {"ok": False, "error": str(exc)}

    return _ok(out)


# ---------------------------------------------------------------------------
# Tool handlers — claim / stake


def handle_claim_rewards(params: dict | None = None, **_: Any) -> str:
    params = params or {}
    epoch_ids = params.get("epoch_ids")
    if not isinstance(epoch_ids, list) or not epoch_ids:
        return _err("epoch_ids must be a non-empty list of integers")
    try:
        epochs = [int(e) for e in epoch_ids]
    except (TypeError, ValueError):
        return _err("epoch_ids must contain integers")

    try:
        signer = _signer()
    except (SignerError, SignerNotConfigured) as exc:
        return _err(f"signer not ready: {exc}")

    coord = _coord()
    txs: list[dict[str, Any]] = []

    main, err = _safe_call(
        coord.claim_calldata, epochs, target=params.get("pool_target")
    )
    if err:
        return err
    main_tx = main.get("transaction")
    if main_tx:
        try:
            r = signer.submit_tx(main_tx, wait=True)
            txs.append({"kind": "claim", "epochs": epochs, "receipt": r})
        except SignerError as exc:
            return _err(f"claim broadcast failed: {exc}")

    if params.get("include_bonus", True):
        # Filter to epochs that are actual bonus epochs and have funded rewards.
        try:
            bonus_status = coord.bonus_status(epochs)
            statuses = bonus_status if isinstance(bonus_status, list) else [bonus_status]
            bonus_epochs = [
                int(s.get("epochId"))
                for s in statuses
                if isinstance(s, dict) and s.get("isBonusEpoch") and s.get("claimsOpen")
            ]
        except CoordinatorError as exc:
            bonus_epochs = []
            txs.append({"kind": "bonus_status", "ok": False, "error": str(exc)})

        if bonus_epochs:
            bonus_cd, b_err = _safe_call(
                coord.bonus_claim_calldata, bonus_epochs, target=params.get("pool_target")
            )
            if b_err:
                return b_err
            b_tx = bonus_cd.get("transaction")
            if b_tx:
                try:
                    r = signer.submit_tx(b_tx, wait=True)
                    txs.append({"kind": "bonus_claim", "epochs": bonus_epochs, "receipt": r})
                except SignerError as exc:
                    txs.append({"kind": "bonus_claim", "ok": False, "error": str(exc)})

    invalidate_cache()
    return _ok({"transactions": txs})


def handle_stake(params: dict | None = None, **_: Any) -> str:
    params = params or {}
    raw_amount = params.get("amount")
    if raw_amount is None:
        return _err("amount is required (whole BOTCOIN as a decimal string)")
    try:
        whole = int(str(raw_amount).replace(",", "").strip())
    except ValueError:
        return _err("amount must be a whole-token integer like \"5000000\"")
    if whole < 1:
        return _err("amount must be >= 1 whole BOTCOIN")
    wei = whole * (10 ** 18)

    try:
        signer = _signer()
    except (SignerError, SignerNotConfigured) as exc:
        return _err(f"signer not ready: {exc}")
    coord = _coord()

    approve, err = _safe_call(coord.stake_approve_calldata, wei)
    if err:
        return err
    stake, err2 = _safe_call(coord.stake_calldata, wei)
    if err2:
        return err2

    out: list[dict[str, Any]] = []
    try:
        approve_tx = approve.get("transaction")
        if approve_tx:
            r = signer.submit_tx(approve_tx, wait=True)
            out.append({"kind": "approve", "amount_whole": whole, "receipt": r})
        stake_tx = stake.get("transaction")
        if stake_tx:
            r = signer.submit_tx(stake_tx, wait=True)
            out.append({"kind": "stake", "amount_whole": whole, "receipt": r})
    except SignerError as exc:
        return _err(f"stake broadcast failed: {exc}", partial=out)

    invalidate_cache()
    return _ok({"transactions": out})


def handle_unstake(params: dict | None = None, **_: Any) -> str:
    params = params or {}
    cancel = bool(params.get("cancel"))
    try:
        signer = _signer()
    except (SignerError, SignerNotConfigured) as exc:
        return _err(f"signer not ready: {exc}")
    coord = _coord()
    if cancel:
        # The coordinator does not currently expose a /cancel-unstake-calldata
        # helper. We construct the call locally.
        # cancelUnstake() = 0x... — let the agent know to use the contract directly.
        return _err(
            "cancel_unstake calldata is not exposed by the coordinator yet. "
            "Call cancelUnstake() on MiningContractV3 directly with no args. "
            f"Contract: {_MINING_V3} on Base (chainId 8453)."
        )

    cd, err = _safe_call(coord.unstake_calldata)
    if err:
        return err
    tx = cd.get("transaction")
    if not tx:
        return _err("coordinator did not return a transaction")
    try:
        r = signer.submit_tx(tx, wait=True)
    except SignerError as exc:
        return _err(f"unstake broadcast failed: {exc}")
    invalidate_cache()
    return _ok({"transaction": r, "note": "Cooldown started — withdraw with botcoin_withdraw_stake after 24h."})


def handle_withdraw_stake(params: dict | None = None, **_: Any) -> str:
    try:
        signer = _signer()
    except (SignerError, SignerNotConfigured) as exc:
        return _err(f"signer not ready: {exc}")
    coord = _coord()
    cd, err = _safe_call(coord.withdraw_calldata)
    if err:
        return err
    tx = cd.get("transaction")
    if not tx:
        return _err("coordinator did not return a transaction (likely cooldown not elapsed)")
    try:
        r = signer.submit_tx(tx, wait=True)
    except SignerError as exc:
        return _err(f"withdraw broadcast failed: {exc}")
    invalidate_cache()
    return _ok({"transaction": r})


# ---------------------------------------------------------------------------
# Tool handlers — ERC-8004 binding


def handle_bind_agent_id(params: dict | None = None, **_: Any) -> str:
    params = params or {}
    agent_id = params.get("agent_id")
    if agent_id in (None, ""):
        return _err("agent_id is required (numeric ERC-8004 agent identifier)")
    try:
        agent_id_str = str(int(str(agent_id).strip()))
    except (TypeError, ValueError):
        return _err(f"agent_id must be numeric, got {agent_id!r}")

    try:
        signer = _signer()
        miner = signer.address()
    except (SignerError, SignerNotConfigured) as exc:
        return _err(f"signer not ready: {exc}")
    coord = _coord()

    nonce, err = _safe_call(coord.bind_nonce, miner, agent_id_str)
    if err:
        return err
    message = nonce.get("message")
    if not message:
        return _err("bind/nonce returned no message", body=nonce)

    # Mirror the auth handshake's Address: canonicalization — the bind
    # message embeds the address with the case Hermes' nonce response chose.
    # Sending verify with the SAME case avoids spurious recovery mismatches
    # on coordinator versions that compare strings instead of checksumming.
    from .auth import _extract_address_from_message
    canonical_miner = _extract_address_from_message(message) or miner

    try:
        sig = signer.personal_sign(message)
    except SignerError as exc:
        return _err(f"signing failed: {exc}")
    if not sig.startswith("0x"):
        sig = "0x" + sig

    verify, err2 = _safe_call(coord.bind_verify, canonical_miner, message, sig)
    if err2:
        return err2
    invalidate_cache()
    return _ok({"miner": canonical_miner, "agentId": agent_id_str, "result": verify})


# ---------------------------------------------------------------------------
# Tool handlers — autonomous cron lifecycle


def handle_autostart(params: dict | None = None, **_: Any) -> str:
    params = params or {}
    if not check_configured():
        return _err("signer not configured — set BOTCOIN_MINER_KEY or BANKR_API_KEY first.")
    try:
        result = cron_lifecycle.autostart(
            schedule=str(params.get("schedule") or "every 90s"),
            solver=params.get("solver"),
            model=params.get("model"),
            max_per_day=params.get("max_per_day"),
            deliver=str(params.get("deliver") or "local"),
        )
    except RuntimeError as exc:
        return _err(str(exc))
    return _ok(result)


def handle_autostop(params: dict | None = None, **_: Any) -> str:
    try:
        return _ok(cron_lifecycle.autostop())
    except RuntimeError as exc:
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Map for register()


HANDLERS = {
    "botcoin_status": handle_status,
    "botcoin_setup_check": handle_setup_check,
    "botcoin_scorecard": handle_scorecard,
    "botcoin_bind_agent_id": handle_bind_agent_id,
    "botcoin_request_challenge": handle_request_challenge,
    "botcoin_submit_artifact": handle_submit_artifact,
    "botcoin_post_receipt": handle_post_receipt,
    "botcoin_claim_rewards": handle_claim_rewards,
    "botcoin_stake": handle_stake,
    "botcoin_unstake": handle_unstake,
    "botcoin_withdraw_stake": handle_withdraw_stake,
    "botcoin_autostart": handle_autostart,
    "botcoin_autostop": handle_autostop,
}


def check_configured() -> bool:
    """check_fn used by ctx.register_tool — gates tool visibility on env presence."""
    return resolve_signer_mode() in ("eoa", "bankr")
