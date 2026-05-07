"""Lifecycle hooks — discoverability + onboarding.

Two hooks are registered:

* ``pre_llm_call`` — once per turn, optionally injects a short BOTCOIN
  status block into the model's context. Triggers on relevant keywords
  in the user's message (mine, earn, stake, BOTCOIN, ...) OR on the
  first turn of any session when a miner is configured. The TTL cache
  in :mod:`hermes_botcoin.status` keeps this cheap.
* ``on_session_start`` — fires once per new session. If the plugin is
  installed but unconfigured, queues a one-time onboarding nudge
  through ``ctx.inject_message`` so the user sees ``/botcoin setup``.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

from .status import get_status

logger = logging.getLogger(__name__)


_DISCOVERY_KEYWORDS = (
    "botcoin", "agent money", "agentmoney", "proof of inference", "mining",
    "earn", "stake", "epoch", "claim reward", "passive income", "miner",
)

_INJECTED_SESSIONS: set[str] = set()
_LOCK = threading.Lock()


def _maybe_should_inject(user_message: Optional[str], is_first_turn: bool) -> bool:
    if is_first_turn:
        return True
    if not user_message:
        return False
    lowered = user_message.lower()
    return any(kw in lowered for kw in _DISCOVERY_KEYWORDS)


def pre_llm_call(
    *,
    user_message: Optional[str] = None,
    is_first_turn: bool = False,
    **_: Any,
):
    """Inject ephemeral mining context when relevant. Returns None or {"context": "..."}."""
    if not _maybe_should_inject(user_message, is_first_turn):
        return None

    try:
        snap = get_status(force_refresh=False)
    except Exception as exc:  # pragma: no cover — best effort
        logger.debug("pre_llm_call status fetch failed: %s", exc)
        return None

    if not snap.configured:
        # Surface mining as an option when not yet set up — but ONLY on a
        # keyword trigger, not blindly on first turn.
        if not user_message or not any(k in user_message.lower() for k in _DISCOVERY_KEYWORDS):
            return None
        return {
            "context": (
                "BOTCOIN mining tools are installed but not configured. "
                "If the user wants to set up mining, run `/botcoin setup` to see the "
                "checklist, then ask them for either a Bankr API key (BANKR_API_KEY) "
                "or an EOA private key (BOTCOIN_MINER_KEY). The Tier 1 minimum is "
                "5,000,000 BOTCOIN staked on Base."
            ),
        }

    parts = [
        f"BOTCOIN mining is active. Miner {snap.miner} (signer {snap.signer_mode})."
    ]
    if snap.epoch_id:
        parts.append(f"Current epoch: {snap.epoch_id}.")
    if snap.epoch_reward_estimate:
        parts.append(f"Estimated epoch reward: {snap.epoch_reward_estimate} BOTCOIN.")
    if snap.active_miners is not None:
        parts.append(f"Active miners: {snap.active_miners}.")
    parts.append(
        "Tools: botcoin_status, botcoin_request_challenge, botcoin_submit_artifact, "
        "botcoin_post_receipt, botcoin_claim_rewards, botcoin_stake. The agent (you) "
        "is the solver — request a challenge, produce the artifact + reasoning trace, "
        "submit, then post the on-chain receipt."
    )
    return {"context": " ".join(parts)}


def on_session_start(
    *,
    session_id: str = "",
    **_: Any,
):
    """Fire a single onboarding nudge per session when unconfigured."""
    from .signer import resolve_signer_mode
    if resolve_signer_mode() in ("eoa", "bankr"):
        return None
    with _LOCK:
        if session_id in _INJECTED_SESSIONS:
            return None
        _INJECTED_SESSIONS.add(session_id or "default")

    # The plugin context is not directly available in this hook signature, so
    # we return a context block that pre_llm_call would normally produce. The
    # actual `inject_message` call happens from the plugin entry point when
    # the CLI is available; see plugin_entry.register_module.
    return None
