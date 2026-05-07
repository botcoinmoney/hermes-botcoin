"""Signer abstraction over Bankr Agent API and a local EOA private key.

Both signers expose the same surface:

    address() -> "0x..."
    personal_sign(message: str) -> "0x<sig>"
    submit_tx(tx: dict) -> dict          # tx is the coordinator's transaction dict

For ``BOTCOIN_SIGNER=eoa`` we sign locally with eth-account and broadcast via
JSON-RPC to ``BASE_RPC_URL``. For ``BOTCOIN_SIGNER=bankr`` we delegate to
``api.bankr.bot``. Auto-detect: if both sets of secrets are present, EOA wins
(it's deterministic and faster); set ``BOTCOIN_SIGNER`` explicitly to override.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)

BASE_CHAIN_ID = 8453
DEFAULT_BASE_RPC = "https://mainnet.base.org"


# ---------------------------------------------------------------------------
# Errors


class SignerError(Exception):
    """Raised when signing or broadcasting fails."""


class SignerNotConfigured(SignerError):
    """Raised when no usable signer credentials are present."""


# ---------------------------------------------------------------------------
# Base interface


class Signer:
    mode: str = "abstract"

    def address(self) -> str:
        raise NotImplementedError

    def personal_sign(self, message: str) -> str:
        raise NotImplementedError

    def submit_tx(self, tx: dict, *, wait: bool = True) -> dict:
        """Submit ``tx`` to the network. Returns ``{"transactionHash": "0x...", "status": ...}``."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# EOA signer (local key + JSON-RPC broadcast)


class EOASigner(Signer):
    mode = "eoa"

    def __init__(self, private_key: str, *, rpc_url: Optional[str] = None) -> None:
        try:
            from eth_account import Account
            from eth_account.messages import encode_defunct  # noqa: F401  (cached for sign step)
        except ImportError as exc:  # pragma: no cover — install hint only
            raise SignerError(
                "eth-account is required for EOA signing. Install it with `pip install eth-account`."
            ) from exc
        if not private_key.startswith("0x"):
            private_key = "0x" + private_key
        self._key = private_key
        self._account = Account.from_key(private_key)
        self._rpc = (rpc_url or os.environ.get("BASE_RPC_URL") or DEFAULT_BASE_RPC).rstrip("/")

    def address(self) -> str:
        return self._account.address

    def personal_sign(self, message: str) -> str:
        from eth_account import Account
        from eth_account.messages import encode_defunct
        signed = Account.sign_message(encode_defunct(text=message), private_key=self._key)
        return signed.signature.hex() if hasattr(signed.signature, "hex") else str(signed.signature)

    def submit_tx(self, tx: dict, *, wait: bool = True) -> dict:
        to = tx.get("to")
        data = tx.get("data")
        chain_id = int(tx.get("chainId") or BASE_CHAIN_ID)
        value = int(tx.get("value") or 0)
        if not to or not data:
            raise SignerError(f"invalid tx (missing to/data): {tx!r}")

        sender = self._account.address
        nonce = int(_rpc_call(self._rpc, "eth_getTransactionCount", [sender, "pending"]), 16)
        gas_estimate = int(_rpc_call(
            self._rpc,
            "eth_estimateGas",
            [{"from": sender, "to": to, "data": data, "value": hex(value)}],
        ), 16)
        gas_limit = int(gas_estimate * 1.2)

        # EIP-1559 fee market — Base supports it natively and it's more reliable
        # than legacy gasPrice during fee spikes (proper replacement-by-fee
        # semantics, no underpriced-tx rejections from RPC providers).
        max_priority, max_fee = _suggest_1559_fees(self._rpc)
        unsigned: dict[str, Any] = {
            "type": 2,
            "to": to,
            "value": value,
            "gas": gas_limit,
            "maxFeePerGas": max_fee,
            "maxPriorityFeePerGas": max_priority,
            "nonce": nonce,
            "data": data,
            "chainId": chain_id,
        }
        from eth_account import Account
        try:
            signed = Account.sign_transaction(unsigned, private_key=self._key)
        except Exception as exc:
            # Fall back to legacy gasPrice if eth_feeHistory or the chain
            # doesn't support EIP-1559 (extremely unlikely on Base, but
            # keeps the signer robust against private-RPC quirks).
            logger.info("EIP-1559 sign failed (%s) — falling back to legacy gasPrice", exc)
            gas_price = int(_rpc_call(self._rpc, "eth_gasPrice", []), 16)
            unsigned = {
                "to": to, "value": value, "gas": gas_limit,
                "gasPrice": gas_price, "nonce": nonce, "data": data, "chainId": chain_id,
            }
            signed = Account.sign_transaction(unsigned, private_key=self._key)

        raw = signed.raw_transaction.hex() if hasattr(signed, "raw_transaction") else signed.rawTransaction.hex()
        if not raw.startswith("0x"):
            raw = "0x" + raw

        tx_hash = _rpc_call(self._rpc, "eth_sendRawTransaction", [raw])

        out: dict[str, Any] = {"transactionHash": tx_hash, "status": "pending", "from": sender}
        if not wait:
            return out

        receipt = _wait_receipt(self._rpc, tx_hash)
        out["status"] = "success" if receipt.get("status") == "0x1" else "reverted"
        out["blockNumber"] = receipt.get("blockNumber")
        out["gasUsed"] = receipt.get("gasUsed")
        return out


# ---------------------------------------------------------------------------
# Bankr signer


class BankrSigner(Signer):
    mode = "bankr"

    BANKR_URL = "https://api.bankr.bot"

    def __init__(self, api_key: str, *, miner_address: Optional[str] = None) -> None:
        self._api_key = api_key
        # Bankr signs + broadcasts from its own EVM wallet — overriding the
        # miner address with BOTCOIN_MINER_ADDRESS would silently desync the
        # advertised miner from the actual signer (signature recovery fails,
        # receipts get rejected). Always resolve from Bankr; warn loudly if
        # the user-supplied override disagrees.
        resolved = self._resolve_evm_wallet()
        if miner_address and miner_address.lower() != resolved.lower():
            logger.warning(
                "BOTCOIN_MINER_ADDRESS=%s ignored — Bankr signer must use its own "
                "EVM wallet %s (which actually signs + broadcasts).",
                miner_address, resolved,
            )
        self._address = resolved

    def _post(self, path: str, body: dict, *, timeout: int = 60) -> dict:
        req = urllib.request.Request(
            url=self.BANKR_URL + path,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-API-Key": self._api_key,
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read() or b""
            try:
                err = json.loads(raw.decode("utf-8"))
            except Exception:
                err = {"error": raw.decode("utf-8", errors="replace")}
            raise SignerError(f"bankr {path} failed ({exc.code}): {err}") from exc
        except urllib.error.URLError as exc:
            raise SignerError(f"bankr {path} network error: {exc.reason}") from exc
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise SignerError(f"bankr {path} returned non-JSON") from exc

    def _get(self, path: str, *, timeout: int = 30) -> dict:
        req = urllib.request.Request(
            url=self.BANKR_URL + path,
            headers={"X-API-Key": self._api_key, "Accept": "application/json"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _resolve_evm_wallet(self) -> str:
        data = self._get("/agent/me")
        for w in data.get("wallets", []) or []:
            if (w.get("chain") or "").lower() == "evm":
                addr = w.get("address")
                if addr:
                    return addr
        raise SignerError("Bankr API did not return an EVM wallet for this agent.")

    def address(self) -> str:
        return self._address

    def personal_sign(self, message: str) -> str:
        data = self._post(
            "/agent/sign",
            {"signatureType": "personal_sign", "message": message},
        )
        sig = data.get("signature")
        if not sig:
            raise SignerError(f"bankr /agent/sign: missing signature in response: {data}")
        return sig

    def submit_tx(self, tx: dict, *, wait: bool = True) -> dict:
        to = tx.get("to")
        data = tx.get("data")
        chain_id = int(tx.get("chainId") or BASE_CHAIN_ID)
        value = tx.get("value") or "0"
        if not to or not data:
            raise SignerError(f"invalid tx (missing to/data): {tx!r}")
        body = {
            "transaction": {"to": to, "chainId": chain_id, "value": str(value), "data": data},
            "description": "BOTCOIN mining transaction",
            "waitForConfirmation": bool(wait),
        }
        resp = self._post("/agent/submit", body, timeout=180)
        out = {
            "transactionHash": resp.get("transactionHash") or resp.get("hash"),
            "status": resp.get("status", "submitted"),
            "raw": resp,
        }
        return out


# ---------------------------------------------------------------------------
# Factory


def resolve_signer_mode(env: Optional[dict[str, str]] = None) -> Optional[str]:
    """Resolve the active signer mode using the canonical precedence rules.

    1. Explicit ``BOTCOIN_SIGNER=eoa|bankr`` always wins (even if the matching
       credential isn't yet present — the user can fix the credential).
    2. Otherwise auto-detect: ``BOTCOIN_MINER_KEY`` → ``eoa``;
       ``BANKR_API_KEY`` → ``bankr``.
    3. Otherwise ``None`` (not configured).

    Used by :func:`make_signer`, :mod:`hermes_botcoin.status`, and
    :mod:`hermes_botcoin.tools` so every surface reports the same answer.
    """
    env = env or os.environ  # type: ignore[assignment]
    forced = (env.get("BOTCOIN_SIGNER") or "").strip().lower()
    if forced in ("eoa", "bankr"):
        return forced
    if forced:
        # Unknown override — surface as "unknown" so callers don't silently
        # auto-detect to a different mode than the user asked for.
        return forced
    if env.get("BOTCOIN_MINER_KEY"):
        return "eoa"
    if env.get("BANKR_API_KEY"):
        return "bankr"
    return None


def make_signer(*, env: Optional[dict[str, str]] = None) -> Signer:
    """Build a signer from environment variables using :func:`resolve_signer_mode`."""
    env = env or os.environ  # type: ignore[assignment]
    mode = resolve_signer_mode(env)
    if mode is None:
        raise SignerNotConfigured(
            "Set BOTCOIN_MINER_KEY (preferred) or BANKR_API_KEY in ~/.hermes/.env, "
            "then optionally BOTCOIN_SIGNER=eoa|bankr to pin the mode."
        )

    if mode == "eoa":
        key = env.get("BOTCOIN_MINER_KEY")
        if not key:
            raise SignerNotConfigured("BOTCOIN_SIGNER=eoa but BOTCOIN_MINER_KEY is unset.")
        return EOASigner(key, rpc_url=env.get("BASE_RPC_URL"))
    if mode == "bankr":
        key = env.get("BANKR_API_KEY")
        if not key:
            raise SignerNotConfigured("BOTCOIN_SIGNER=bankr but BANKR_API_KEY is unset.")
        return BankrSigner(key, miner_address=env.get("BOTCOIN_MINER_ADDRESS"))
    raise SignerNotConfigured(f"unknown BOTCOIN_SIGNER mode: {mode!r}")


# ---------------------------------------------------------------------------
# JSON-RPC plumbing for EOA path


_RPC_USER_AGENT = "hermes-botcoin/0.1.0 (+https://github.com/botcoinmoney/hermes-botcoin)"


def _rpc_call(rpc_url: str, method: str, params: list, *, timeout: int = 30) -> Any:
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    req = urllib.request.Request(
        url=rpc_url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Public Base RPC (mainnet.base.org) sits behind Cloudflare and
            # rejects requests with empty / Python-default user agents
            # (Error 1010). A real UA fixes that without affecting any other
            # RPC provider.
            "User-Agent": _RPC_USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_preview = ""
        try:
            body_preview = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        raise SignerError(f"rpc {method} http {exc.code}: {body_preview}") from exc
    except urllib.error.URLError as exc:
        raise SignerError(f"rpc {method} network error: {exc.reason}") from exc
    if "error" in data:
        raise SignerError(f"rpc {method} error: {data['error']}")
    return data.get("result")


def _suggest_1559_fees(rpc_url: str) -> tuple[int, int]:
    """Return ``(maxPriorityFeePerGas, maxFeePerGas)`` in wei for an EIP-1559 tx.

    Strategy:
      - ``maxPriorityFeePerGas`` = ``eth_maxPriorityFeePerGas`` (with a 1 gwei
        floor so we never tip 0 on Base, where the public RPC sometimes
        returns very small values).
      - ``maxFeePerGas`` = ``2 * baseFee + maxPriority`` using the latest
        block's ``baseFeePerGas``. The 2x multiplier covers up to ~12.5%
        fee jump per block for ~12 blocks, which is plenty for mining
        receipts that confirm in seconds on Base.

    Raises :class:`SignerError` only if the RPC fails to respond at all —
    callers fall back to legacy gasPrice in that case.
    """
    try:
        priority_hex = _rpc_call(rpc_url, "eth_maxPriorityFeePerGas", [])
        priority = int(priority_hex, 16) if priority_hex else 0
    except SignerError:
        priority = 0
    if priority < 1_000_000_000:  # 1 gwei floor
        priority = 1_000_000_000

    block = _rpc_call(rpc_url, "eth_getBlockByNumber", ["latest", False])
    base_fee_hex = block.get("baseFeePerGas") if isinstance(block, dict) else None
    if not base_fee_hex:
        raise SignerError("EIP-1559 unavailable: latest block missing baseFeePerGas")
    base_fee = int(base_fee_hex, 16)
    max_fee = 2 * base_fee + priority
    return priority, max_fee


def _wait_receipt(rpc_url: str, tx_hash: str, *, max_seconds: int = 180) -> dict:
    deadline = time.time() + max_seconds
    while time.time() < deadline:
        receipt = _rpc_call(rpc_url, "eth_getTransactionReceipt", [tx_hash])
        if receipt:
            return receipt
        time.sleep(2)
    raise SignerError(f"tx {tx_hash} did not confirm within {max_seconds}s")
