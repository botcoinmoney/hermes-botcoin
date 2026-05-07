"""resolve_signer_mode — single source of truth for signer-mode reporting."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hermes_botcoin.signer import resolve_signer_mode


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
    """Auditor-flagged: status must report 'bankr' when BOTCOIN_SIGNER=bankr,
    even if BOTCOIN_MINER_KEY is also present."""
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
    """Returning the unknown override (vs. silently auto-detecting) lets
    callers surface a helpful error instead of using the wrong signer."""
    assert resolve_signer_mode({"BOTCOIN_SIGNER": "ledger"}) == "ledger"


def test_case_and_whitespace_normalized():
    assert resolve_signer_mode({
        "BOTCOIN_SIGNER": "  EOA  ",
        "BOTCOIN_MINER_KEY": "0x" + "1" * 64,
    }) == "eoa"
