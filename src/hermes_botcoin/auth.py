"""Coordinator auth handshake (nonce → personal_sign → verify) with bearer caching.

A single :class:`AuthSession` instance handles the full lifecycle for one
miner address. Bearer tokens have a server-side TTL of ~10 minutes; we cache
locally and proactively re-auth a few seconds before expiry to keep the
mining loop snappy. Tokens are only ever held in memory — never written to
disk by this module.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .coordinator import Coordinator, CoordinatorError, is_retryable, respect_retry_after
from .signer import Signer

logger = logging.getLogger(__name__)


def _extract_address_from_message(message: str) -> str | None:
    """Pull the `Address:` line out of the EIP-191 nonce message.

    The coordinator's nonce message looks like::

        Botcoin Auth
        Domain: coordinator.agentmoney.net
        Address: 0xabc... (lowercase)
        Nonce: ...

    The verify endpoint validates that the recovered signer matches the
    `miner` field, but case sensitivity in the equality check has bitten us
    before — easiest fix is to send back exactly what we got.
    """
    for line in message.splitlines():
        if line.startswith("Address:"):
            value = line.split(":", 1)[1].strip()
            if value.startswith("0x") and len(value) == 42:
                return value
    return None


@dataclass
class _Token:
    value: str
    expires_at: float  # epoch seconds
    audience: str
    binding: dict


class AuthSession:
    """Cache + refresh bearer tokens for one (miner, agentId?) tuple."""

    def __init__(self, coord: Coordinator, signer: Signer, *, agent_id: Optional[str] = None) -> None:
        self.coord = coord
        self.signer = signer
        self.agent_id = agent_id
        self._lock = threading.Lock()
        self._token: Optional[_Token] = None

    @property
    def miner(self) -> str:
        return self.signer.address()

    def bearer(self, *, force: bool = False) -> str:
        """Return a valid bearer token, re-authenticating when needed."""
        now = time.time()
        with self._lock:
            tok = self._token
            if not force and tok and tok.expires_at - 5 > now:
                return tok.value
            self._token = None  # ensure no stale return on partial failure

        new = self._handshake()
        with self._lock:
            self._token = new
        return new.value

    def reset(self) -> None:
        with self._lock:
            self._token = None

    def _handshake(self) -> _Token:
        miner = self.miner
        # Step 1: nonce
        nonce: dict = {}
        for attempt in range(4):
            try:
                nonce = self.coord.auth_nonce(miner)
                break
            except CoordinatorError as exc:
                if is_retryable(exc) and attempt < 3:
                    time.sleep(respect_retry_after(exc, attempt=attempt))
                    continue
                raise
        message = nonce.get("message")
        if not message:
            raise CoordinatorError(
                status=500, route="/v1/auth/nonce", error="missing message in nonce response", body=nonce
            )
        # Sign with the EXACT address case that appears in the nonce message —
        # the coordinator embeds Address: <lowercased> in the message and
        # expects the verify call's `miner` field to match that case.
        canonical_miner = _extract_address_from_message(message) or miner

        sig = self.signer.personal_sign(message)
        if not sig.startswith("0x"):
            sig = "0x" + sig

        # Step 2: verify (retry on transient 5xx — coordinator occasionally 503s)
        verify: dict = {}
        for attempt in range(4):
            try:
                verify = self.coord.auth_verify(
                    canonical_miner, message, sig, agent_id=self.agent_id
                )
                break
            except CoordinatorError as exc:
                if is_retryable(exc) and attempt < 3:
                    time.sleep(respect_retry_after(exc, attempt=attempt))
                    continue
                raise
        token = verify.get("token")
        if not token:
            raise CoordinatorError(
                status=500, route="/v1/auth/verify", error="missing token in verify response", body=verify
            )
        # Server gives us either expiresAt (ISO) or expiresInSeconds.
        ttl_seconds = float(verify.get("expiresInSeconds") or 0.0)
        if ttl_seconds <= 0:
            iso = verify.get("expiresAt") or ""
            try:
                dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                ttl_seconds = max(0.0, dt.timestamp() - time.time())
            except Exception:
                ttl_seconds = 540.0  # fall back to 9 minutes (server cap is 10)
        expires_at = time.time() + ttl_seconds
        return _Token(
            value=token,
            expires_at=expires_at,
            audience=str(verify.get("audience") or ""),
            binding=verify.get("binding") or {},
        )
