"""Coordinator URL building, error parsing, retry helpers."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hermes_botcoin.coordinator import (
    Coordinator,
    CoordinatorError,
    backoff_seconds,
    is_retryable,
    respect_retry_after,
)


def test_default_base_url():
    c = Coordinator()
    assert c.base_url == "https://coordinator.agentmoney.net"


def test_explicit_base_url_strips_trailing_slash():
    c = Coordinator(base_url="https://example.com/")
    assert c.base_url == "https://example.com"


def test_backoff_caps():
    assert backoff_seconds(0) == 2.0
    assert backoff_seconds(10, cap=30.0) == 30.0


def test_is_retryable_matrix():
    assert is_retryable(CoordinatorError(status=429, route="/x", error="rate_limited"))
    assert is_retryable(CoordinatorError(status=503, route="/x", error="service_unavailable"))
    assert is_retryable(CoordinatorError(status=0, route="/x", error="network: timeout"))
    assert is_retryable(CoordinatorError(status=401, route="/x", error="token_expired"))
    assert not is_retryable(CoordinatorError(status=400, route="/x", error="bad_request"))
    assert not is_retryable(CoordinatorError(status=403, route="/x", error="insufficient_balance"))


def test_respect_retry_after_uses_server_hint():
    err = CoordinatorError(status=429, route="/x", error="rl", retry_after_seconds=42)
    delay = respect_retry_after(err, attempt=0, jitter=0.0)
    assert delay == 42.0
