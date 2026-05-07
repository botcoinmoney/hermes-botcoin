"""End-to-end autonomous mining loop.

This is the function the cron console script and the ``hermes botcoin mine``
CLI call. It is **never** invoked from a Hermes tool — for in-session use,
the agent itself is the solver and the plugin only exposes
``botcoin_request_challenge`` / ``botcoin_submit_artifact`` /
``botcoin_post_receipt``.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Optional

from .auth import AuthSession
from .coordinator import Coordinator, CoordinatorError, is_retryable, respect_retry_after
from .signer import SignerError, SignerNotConfigured, make_signer
from .solver import solve_challenge
from .trace import normalize_trace, serialize_submitted_answers

logger = logging.getLogger(__name__)


def autonomous_mine_one(
    *,
    solver_provider: str = "venice",
    solver_model: Optional[str] = None,
    solver_max_tokens: int = 32000,
    solver_thinking_budget: int = 12000,
    log_prefix: str = "",
    coord: Optional[Coordinator] = None,
) -> dict[str, Any]:
    """Run one full attempt: auth → challenge → solve → submit → broadcast receipt.

    Returns a structured dict so cron output stays machine-readable.
    Never raises — every failure path is captured and surfaced under ``error``.
    """
    prefix = f"[{log_prefix}] " if log_prefix else ""
    coord = coord or Coordinator()

    try:
        signer = make_signer()
    except SignerNotConfigured as exc:
        return {"ok": False, "stage": "signer", "error": str(exc)}

    miner = signer.address()
    auth = AuthSession(coord, signer)
    nonce = uuid.uuid4().hex[:32]

    # 1. Authenticate
    try:
        bearer = auth.bearer()
    except (CoordinatorError, SignerError) as exc:
        logger.warning("%sauth failed: %s", prefix, exc)
        return {"ok": False, "stage": "auth", "miner": miner, "error": str(exc)}

    # 2. Challenge
    challenge = None
    for attempt in range(3):
        try:
            challenge = coord.challenge(miner, bearer=bearer, nonce=nonce)
            break
        except CoordinatorError as exc:
            if exc.status == 401:
                auth.reset()
                bearer = auth.bearer(force=True)
                continue
            if is_retryable(exc) and attempt < 2:
                wait = respect_retry_after(exc, attempt=attempt)
                logger.info("%schallenge retry in %.1fs: %s", prefix, wait, exc.error)
                time.sleep(wait)
                continue
            return {"ok": False, "stage": "challenge", "miner": miner, "error": str(exc),
                    "status": exc.status, "retry_after_seconds": exc.retry_after_seconds}
    if challenge is None:
        return {"ok": False, "stage": "challenge", "miner": miner, "error": "exhausted retries"}

    challenge_id = challenge.get("challengeId")
    manifest_hash = challenge.get("challengeManifestHash", "")
    domain = challenge.get("challengeDomain", "")
    logger.info("%schallenge %s (domain=%s)", prefix, challenge_id, domain)

    # 3-4. Solve + submit (multi-pass aware — up to 3 attempts per challenge).
    submit_result: Optional[dict[str, Any]] = None
    model_version = ""
    last_feedback: Optional[dict[str, Any]] = None
    multipass_max = 3

    for pass_idx in range(multipass_max):
        # Re-solve from scratch each pass. The skill is explicit: resubmit a
        # COMPLETE fresh reasoningTrace, not a continuation. We add a `revision`
        # step at the front when this is a retry so the trace explains what
        # changed.
        try:
            challenge_for_solver = challenge
            if pass_idx > 0 and last_feedback:
                # Inject prior-attempt feedback into solveInstructions so the
                # solver knows what to focus on.
                hint = (
                    "\n\n# Prior attempt feedback (retry pass {p}/{m})\n"
                    "constraintsPassed={cp}/{ct}; questionAnswersCorrect={qc}/{qt}. "
                    "Re-derive every constraint from scratch. Pay extra attention to: "
                    "the equation digits and the prime-number derivation; the acrostic "
                    "letter sequence (case-sensitive first letters of first N words); "
                    "the forbidden letter (case-insensitive). Include a revision step "
                    "at step_id 'rev1' explaining what you changed.\n"
                ).format(
                    p=pass_idx + 1,
                    m=multipass_max,
                    cp=last_feedback.get("constraintsPassed"),
                    ct=last_feedback.get("constraintsTotal"),
                    qc=last_feedback.get("questionAnswersCorrect"),
                    qt=last_feedback.get("questionAnswersTotal"),
                )
                challenge_for_solver = {
                    **challenge,
                    "solveInstructions": (challenge.get("solveInstructions") or "") + hint,
                }
            artifact, raw_trace, raw_answers, model_version = solve_challenge(
                challenge_for_solver,
                provider=solver_provider,
                model=solver_model,
                max_tokens=solver_max_tokens,
                thinking_budget=solver_thinking_budget,
            )
        except Exception as exc:
            logger.warning("%spass %d solve failed: %s", prefix, pass_idx + 1, exc)
            return {"ok": False, "stage": "solve", "miner": miner, "challenge_id": challenge_id,
                    "pass_idx": pass_idx + 1, "error": str(exc)}

        trace = normalize_trace(raw_trace)
        answers = serialize_submitted_answers(raw_answers)
        logger.info("%spass %d/%d: artifact=%d chars trace_steps=%d answers=%d",
                    prefix, pass_idx + 1, multipass_max, len(artifact), len(trace), len(answers or {}))

        submit_result = None
        for retry in range(3):
            try:
                submit_result = coord.submit(
                    miner=miner,
                    challenge_id=challenge_id,
                    artifact=artifact,
                    nonce=nonce,
                    challenge_manifest_hash=manifest_hash,
                    model_version=model_version,
                    reasoning_trace=trace,
                    bearer=bearer,
                    submitted_answers=answers,
                )
                break
            except CoordinatorError as exc:
                if exc.status == 401:
                    auth.reset()
                    bearer = auth.bearer(force=True)
                    continue
                if is_retryable(exc) and retry < 2:
                    time.sleep(respect_retry_after(exc, attempt=retry))
                    continue
                return {"ok": False, "stage": "submit", "miner": miner, "challenge_id": challenge_id,
                        "pass_idx": pass_idx + 1, "error": str(exc), "status": exc.status,
                        "retry_after_seconds": exc.retry_after_seconds, "body": exc.body}
        if submit_result is None:
            return {"ok": False, "stage": "submit", "miner": miner, "challenge_id": challenge_id,
                    "error": "exhausted retries"}

        if submit_result.get("pass"):
            break

        last_feedback = submit_result
        if not submit_result.get("retryAllowed"):
            break
        logger.info("%spass %d failed (%d/%d constraints, %d/%d answers) — retrying",
                    prefix, pass_idx + 1,
                    submit_result.get("constraintsPassed", 0),
                    submit_result.get("constraintsTotal", 0),
                    submit_result.get("questionAnswersCorrect", 0),
                    submit_result.get("questionAnswersTotal", 0))

    if not submit_result or not submit_result.get("pass"):
        return {
            "ok": False,
            "stage": "verification",
            "miner": miner,
            "challenge_id": challenge_id,
            "domain": domain,
            "model_version": model_version,
            "result": submit_result,
        }

    # 5. Broadcast receipt (sync) + vouch (fire-and-forget, when present)
    tx = submit_result.get("transaction")
    vouch_tx = submit_result.get("vouchTransaction")
    receipt = None
    vouch = None
    if tx:
        try:
            receipt = signer.submit_tx(tx, wait=True)
        except SignerError as exc:
            return {"ok": False, "stage": "post_receipt", "miner": miner,
                    "challenge_id": challenge_id, "error": str(exc),
                    "submit_result": submit_result}
    if isinstance(vouch_tx, dict) and vouch_tx.get("to") and vouch_tx.get("data"):
        try:
            vouch = signer.submit_tx(vouch_tx, wait=False)
        except SignerError as exc:
            vouch = {"ok": False, "error": str(exc)}

    return {
        "ok": True,
        "stage": "complete",
        "miner": miner,
        "challenge_id": challenge_id,
        "domain": domain,
        "model_version": model_version,
        # creditsPerSolve lives on the challenge response (it depends on the
        # miner's stake tier at challenge time), not on the receipt.
        "credits_earned": challenge.get("creditsPerSolve"),
        "epoch_id": submit_result.get("receipt", {}).get("epochId"),
        "receipt": receipt,
        "vouch": vouch,
    }
