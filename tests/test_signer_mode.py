"""Single source of truth for signer-mode reporting across status, hooks, tools."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hermes_botcoin.signer import (  # noqa: E402
    SignerNotConfigured,
    make_signer,
    resolve_signer_mode,
)
import pytest  # noqa: E402


def test_no_credentials():
    assert resolve_signer_mode({}) is None


def test_eoa_only():
    assert resolve_signer_mode({"BOTCOIN_MINER_KEY": "0x" + "1" * 64}) == "eoa"


def test_bankr_only():
    assert resolve_signer_mode({"BANKR_API_KEY": "bk_x"}) == "bankr"


def test_eoa_wins_when_both():
    assert resolve_signer_mode({
        "BOTCOIN_MINER_KEY": "0x" + "1" * 64,
        "BANKR_API_KEY": "bk_x",
    }) == "eoa"


def test_explicit_bankr_overrides_eoa_key():
    """status / setup must report 'bankr' when BOTCOIN_SIGNER=bankr,
    even if BOTCOIN_MINER_KEY is also set."""
    assert resolve_signer_mode({
        "BOTCOIN_SIGNER": "bankr",
        "BOTCOIN_MINER_KEY": "0x" + "1" * 64,
        "BANKR_API_KEY": "bk_x",
    }) == "bankr"


def test_explicit_eoa_overrides_bankr_key():
    assert resolve_signer_mode({
        "BOTCOIN_SIGNER": "eoa",
        "BANKR_API_KEY": "bk_x",
    }) == "eoa"


def test_unknown_mode_passes_through():
    """Unknown override returns as-is so callers surface a helpful error
    rather than auto-detecting silently."""
    assert resolve_signer_mode({"BOTCOIN_SIGNER": "ledger"}) == "ledger"


def test_case_and_whitespace_normalized():
    assert resolve_signer_mode({
        "BOTCOIN_SIGNER": "  EOA  ",
        "BOTCOIN_MINER_KEY": "0x" + "1" * 64,
    }) == "eoa"


def test_make_signer_no_creds_raises():
    with pytest.raises(SignerNotConfigured):
        make_signer(env={})


def test_make_signer_unknown_mode_raises():
    with pytest.raises(SignerNotConfigured):
        make_signer(env={"BOTCOIN_SIGNER": "ledger"})
