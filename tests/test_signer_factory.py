"""Test the signer mode auto-detect and explicit override logic."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from hermes_botcoin.signer import SignerNotConfigured, make_signer


def test_no_credentials_raises():
    with pytest.raises(SignerNotConfigured):
        make_signer(env={})


def test_bankr_picked_when_only_bankr_set(monkeypatch):
    s = make_signer(env={"BANKR_API_KEY": "bk_x", "BOTCOIN_MINER_ADDRESS": "0x" + "a" * 40})
    assert s.mode == "bankr"


def test_eoa_wins_when_both_set():
    s = make_signer(env={
        "BANKR_API_KEY": "bk_x",
        "BOTCOIN_MINER_KEY": "0x" + "1" * 64,
    })
    assert s.mode == "eoa"


def test_explicit_override_to_bankr_when_eoa_present():
    s = make_signer(env={
        "BOTCOIN_SIGNER": "bankr",
        "BANKR_API_KEY": "bk_x",
        "BOTCOIN_MINER_KEY": "0x" + "1" * 64,
        "BOTCOIN_MINER_ADDRESS": "0x" + "a" * 40,
    })
    assert s.mode == "bankr"


def test_unknown_mode_raises():
    with pytest.raises(SignerNotConfigured):
        make_signer(env={"BOTCOIN_SIGNER": "ledger"})
