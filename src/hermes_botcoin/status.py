"""Cached miner status snapshot.

The status snapshot is read from the coordinator's public endpoints plus a
small set of derived fields. It powers the discoverability hook (every turn
costs zero extra HTTP requests when the cache is warm) and the /botcoin
status slash command.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, asdict
from typing import Any, Optional

from .coordinator import Coordinator, CoordinatorError
from .signer import make_signer, resolve_signer_mode, SignerNotConfigured

logger = logging.getLogger(__name__)


@dataclass
class StatusSnapshot:
    configured: bool
    signer_mode: Optional[str]
    miner: Optional[str]
    epoch_id: Optional[str]
    epoch_ends_at: Optional[int]
    epoch_reward_estimate: Optional[str]
    active_miners: Optional[int]
    total_staked: Optional[str]
    coordinator_url: str
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_CACHE_LOCK = threading.Lock()
_CACHE: Optional[tuple[float, StatusSnapshot]] = None
_TTL_SECONDS = 60.0


def _resolve_miner_address() -> Optional[str]:
    """Cheap miner-address resolution; never raises."""
    addr = os.environ.get("BOTCOIN_MINER_ADDRESS")
    if addr:
        return addr.strip()
    try:
        signer = make_signer()
        return signer.address()
    except SignerNotConfigured:
        return None
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("miner address resolution failed: %s", exc)
        return None


def get_status(*, force_refresh: bool = False) -> StatusSnapshot:
    """Return a status snapshot, using a TTL cache to keep hooks cheap."""
    global _CACHE
    now = time.time()
    if not force_refresh:
        with _CACHE_LOCK:
            if _CACHE and now - _CACHE[0] < _TTL_SECONDS:
                return _CACHE[1]

    coord = Coordinator()
    snap = StatusSnapshot(
        configured=False,
        signer_mode=None,
        miner=None,
        epoch_id=None,
        epoch_ends_at=None,
        epoch_reward_estimate=None,
        active_miners=None,
        total_staked=None,
        coordinator_url=coord.base_url,
        error=None,
    )

    miner = _resolve_miner_address()
    if miner:
        snap.miner = miner
        snap.signer_mode = resolve_signer_mode()
        snap.configured = snap.signer_mode in ("eoa", "bankr")

    try:
        ep = coord.epoch()
        snap.epoch_id = ep.get("epochId")
        snap.epoch_ends_at = ep.get("nextEpochStartTimestamp")
    except CoordinatorError as exc:
        snap.error = f"epoch: {exc.error}"

    try:
        stats = coord.stats()
        snap.epoch_reward_estimate = stats.get("currentEpochEstimate")
        am = stats.get("activeMiners")
        snap.active_miners = int(am) if isinstance(am, (int, float, str)) and str(am).isdigit() else None
    except CoordinatorError as exc:
        snap.error = (snap.error + "; " if snap.error else "") + f"stats: {exc.error}"

    try:
        ts = coord.total_staked()
        snap.total_staked = ts.get("totalStaked")
    except CoordinatorError as exc:
        snap.error = (snap.error + "; " if snap.error else "") + f"total_staked: {exc.error}"

    with _CACHE_LOCK:
        _CACHE = (now, snap)
    return snap


def invalidate_cache() -> None:
    """Drop the cached snapshot so the next read hits the network."""
    global _CACHE
    with _CACHE_LOCK:
        _CACHE = None
