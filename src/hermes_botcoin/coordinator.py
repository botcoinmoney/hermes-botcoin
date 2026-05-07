"""HTTP client for the BOTCOIN coordinator.

Uses only the Python standard library so this module also works when imported
from a cron-mode helper script that runs outside the Hermes virtualenv.

Every request returns a parsed JSON dict on success; coordinator errors are
raised as :class:`CoordinatorError` carrying the HTTP status, route, error
code, and any `retryAfterSeconds` hint when the server provided one.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)

DEFAULT_COORDINATOR_URL = "https://coordinator.agentmoney.net"
DEFAULT_TIMEOUT_SECONDS = 30
USER_AGENT = "hermes-botcoin/0.1.0 (+https://github.com/botcoinmoney/hermes-botcoin)"


# ---------------------------------------------------------------------------
# Errors


@dataclass
class CoordinatorError(Exception):
    """Raised when the coordinator returns a non-2xx status or a structured error."""

    status: int
    route: str
    error: str
    body: Optional[dict] = None
    retry_after_seconds: Optional[int] = None

    def __str__(self) -> str:  # pragma: no cover — trivial
        retry = f" retry_after={self.retry_after_seconds}s" if self.retry_after_seconds else ""
        return f"CoordinatorError {self.status} {self.route}: {self.error}{retry}"


def _retry_after_from_response(headers: Mapping[str, str], body: Optional[dict]) -> Optional[int]:
    """Combine `Retry-After` header and `retryAfterSeconds` JSON field, take the longer."""
    candidates: list[int] = []
    raw_header = headers.get("Retry-After") or headers.get("retry-after")
    if raw_header:
        try:
            candidates.append(int(float(raw_header)))
        except (TypeError, ValueError):
            pass
    if isinstance(body, dict):
        v = body.get("retryAfterSeconds")
        if isinstance(v, (int, float)):
            candidates.append(int(v))
    if not candidates:
        return None
    return max(candidates)


# ---------------------------------------------------------------------------
# Client


class Coordinator:
    """Thin synchronous client over the coordinator HTTP API.

    Only methods we actually use in mining live here. Everything else (e.g.
    `/v1/stats`, `/v1/frontend/total-staked`, `/v1/bonus/proof`) goes through
    the generic :meth:`get` helper.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        user_agent: str = USER_AGENT,
    ) -> None:
        self.base_url = (base_url or os.environ.get("COORDINATOR_URL") or DEFAULT_COORDINATOR_URL).rstrip("/")
        self.timeout = timeout
        self.user_agent = user_agent

    # -- low-level ----------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        bearer: Optional[str] = None,
        params: Optional[Mapping[str, Any]] = None,
        json_body: Optional[Mapping[str, Any]] = None,
        timeout: Optional[int] = None,
    ) -> dict:
        url = self.base_url + path
        if params:
            qs = urllib.parse.urlencode(
                {k: ("true" if v is True else "false" if v is False else str(v)) for k, v in params.items() if v is not None}
            )
            if qs:
                url = f"{url}?{qs}"

        data: Optional[bytes] = None
        headers = {
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"

        req = urllib.request.Request(url=url, data=data, headers=headers, method=method.upper())

        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                raw = resp.read()
                resp_headers = {k: v for k, v in resp.headers.items()}
                status = resp.status
        except urllib.error.HTTPError as exc:
            raw = exc.read() or b""
            resp_headers = {k: v for k, v in (exc.headers.items() if exc.headers else [])}
            status = exc.code
        except urllib.error.URLError as exc:
            raise CoordinatorError(status=0, route=path, error=f"network: {exc.reason}") from exc

        if not raw:
            parsed: dict = {}
        else:
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                if 200 <= status < 300:
                    raise CoordinatorError(
                        status=status,
                        route=path,
                        error="non-JSON success body",
                        body={"raw": raw[:512].decode("utf-8", errors="replace")},
                    )
                parsed = {"raw": raw[:512].decode("utf-8", errors="replace")}

        if 200 <= status < 300:
            return parsed if isinstance(parsed, dict) else {"value": parsed}

        retry = _retry_after_from_response(resp_headers, parsed if isinstance(parsed, dict) else None)
        err = ""
        if isinstance(parsed, dict):
            err = str(parsed.get("error") or parsed.get("reason") or "")
        if not err:
            err = f"http_{status}"
        raise CoordinatorError(
            status=status,
            route=path,
            error=err,
            body=parsed if isinstance(parsed, dict) else {"raw": parsed},
            retry_after_seconds=retry,
        )

    # -- public API ---------------------------------------------------------

    def get(self, path: str, **kw) -> dict:
        return self._request("GET", path, **kw)

    def post(self, path: str, **kw) -> dict:
        return self._request("POST", path, **kw)

    # Discovery (no auth)
    def agent_card(self) -> dict:
        return self.get("/.well-known/agent-card.json")

    def epoch(self) -> dict:
        return self.get("/v1/epoch")

    def stats(self) -> dict:
        return self.get("/v1/stats")

    def total_staked(self) -> dict:
        return self.get("/v1/frontend/total-staked")

    def scorecard(self, miner: str, *, as_of: Optional[int] = None) -> dict:
        params = {"asOf": as_of} if as_of else None
        return self.get(f"/v1/miner/{miner}/scorecard", params=params)

    def credits(self, miner: str) -> dict:
        """Per-miner credit summary grouped by epoch. Throttled per address."""
        return self.get("/v1/credits", params={"miner": miner})

    def token(self) -> dict:
        """Authoritative BOTCOIN token metadata served by the coordinator."""
        return self.get("/v1/token")

    def health(self) -> dict:
        return self.get("/health")

    # Auth
    def auth_nonce(self, miner: str) -> dict:
        return self.post("/v1/auth/nonce", json_body={"miner": miner})

    def auth_verify(
        self,
        miner: str,
        message: str,
        signature: str,
        *,
        agent_id: Optional[str] = None,
    ) -> dict:
        body: dict[str, Any] = {"miner": miner, "message": message, "signature": signature}
        if agent_id:
            body["agentId"] = str(agent_id)
        return self.post("/v1/auth/verify", json_body=body)

    # ERC-8004 binding
    def bind_nonce(self, miner: str, agent_id: str) -> dict:
        return self.post("/v1/agent/bind/nonce", json_body={"miner": miner, "agentId": str(agent_id)})

    def bind_verify(self, miner: str, message: str, signature: str) -> dict:
        return self.post(
            "/v1/agent/bind/verify",
            json_body={"miner": miner, "message": message, "signature": signature},
        )

    # Mining
    def challenge(self, miner: str, *, bearer: str, nonce: Optional[str] = None) -> dict:
        params = {"miner": miner}
        if nonce:
            params["nonce"] = nonce
        return self.get("/v1/challenge", bearer=bearer, params=params, timeout=60)

    def submit(
        self,
        *,
        miner: str,
        challenge_id: str,
        artifact: str,
        nonce: str,
        challenge_manifest_hash: str,
        model_version: str,
        reasoning_trace: list,
        bearer: str,
        submitted_answers: Optional[list] = None,
        pool: bool = False,
    ) -> dict:
        body: dict[str, Any] = {
            "miner": miner,
            "challengeId": challenge_id,
            "artifact": artifact,
            "nonce": nonce,
            "challengeManifestHash": challenge_manifest_hash,
            "modelVersion": model_version,
            "reasoningTrace": reasoning_trace,
        }
        if submitted_answers is not None:
            body["submittedAnswers"] = submitted_answers
        if pool:
            body["pool"] = True
        return self.post("/v1/submit", json_body=body, bearer=bearer, timeout=120)

    # Reward / stake calldata helpers
    def claim_calldata(self, epochs: list[int], *, target: Optional[str] = None) -> dict:
        params = {"epochs": ",".join(str(int(e)) for e in epochs)}
        if target:
            params["target"] = target
        return self.get("/v1/claim-calldata", params=params)

    def bonus_status(self, epochs: list[int]) -> dict:
        params = {"epochs": ",".join(str(int(e)) for e in epochs)}
        return self.get("/v1/bonus/status", params=params)

    def bonus_claim_calldata(self, epochs: list[int], *, target: Optional[str] = None) -> dict:
        params = {"epochs": ",".join(str(int(e)) for e in epochs)}
        if target:
            params["target"] = target
        return self.get("/v1/bonus/claim-calldata", params=params)

    def stake_approve_calldata(self, amount_wei: int) -> dict:
        return self.get("/v1/stake-approve-calldata", params={"amount": str(int(amount_wei))})

    def stake_calldata(self, amount_wei: int) -> dict:
        return self.get("/v1/stake-calldata", params={"amount": str(int(amount_wei))})

    def unstake_calldata(self) -> dict:
        return self.get("/v1/unstake-calldata")

    def withdraw_calldata(self) -> dict:
        return self.get("/v1/withdraw-calldata")


# ---------------------------------------------------------------------------
# Backoff helpers shared by mining loop and tools


def backoff_seconds(attempt: int, *, base: float = 2.0, cap: float = 60.0) -> float:
    """Exponential backoff with cap. attempt is 0-indexed."""
    return min(cap, base * (2 ** max(0, attempt)))


def respect_retry_after(err: CoordinatorError, *, attempt: int = 0, jitter: float = 0.25) -> float:
    """Pick a wait duration that respects the server's Retry-After hint.

    Returns seconds to sleep. The caller is expected to ``time.sleep(result)``.
    """
    import random
    base = float(err.retry_after_seconds or backoff_seconds(attempt))
    return base * (1 + random.uniform(0, max(0.0, jitter)))


def is_retryable(err: CoordinatorError) -> bool:
    """Whether the caller should retry after a delay (vs. give up immediately)."""
    if err.status in (0, 408, 425, 429, 500, 502, 503, 504):
        return True
    # Any 401 from a token-protected route is potentially recoverable by
    # re-authenticating; the caller decides whether to refresh the bearer.
    if err.status == 401:
        return True
    return False
