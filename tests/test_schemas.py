"""Tool schemas + handler parity invariants, including the gated/ungated split."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hermes_botcoin.schemas import ALL_TOOLS  # noqa: E402
from hermes_botcoin.tools import HANDLERS  # noqa: E402


def test_every_schema_declares_required_keys():
    for name, schema, _emoji, gated in ALL_TOOLS:
        assert schema["name"] == name, f"{name} schema name mismatch"
        assert isinstance(schema.get("description"), str) and schema["description"], name
        params = schema["parameters"]
        assert params["type"] == "object", name
        assert "properties" in params, name
        assert "required" in params, name
        assert isinstance(gated, bool), name


def test_every_schema_has_a_handler():
    for name, _schema, _emoji, _gated in ALL_TOOLS:
        assert name in HANDLERS, f"missing handler for {name}"
        assert callable(HANDLERS[name])


def test_no_duplicate_tool_names():
    names = [name for name, _s, _e, _g in ALL_TOOLS]
    assert len(names) == len(set(names))


def test_thirteen_tools_total():
    """Bumping requires intentional update to release notes + README."""
    assert len(ALL_TOOLS) == 13


def test_diagnostic_tools_are_ungated():
    """Diagnostic tools must always appear in the model's tool list — that's
    how an unconfigured user discovers what to set up. Auditor caught this
    in v0.1.1."""
    ungated = {name for name, _s, _e, gated in ALL_TOOLS if not gated}
    assert ungated == {"botcoin_status", "botcoin_setup_check", "botcoin_scorecard"}


def test_signing_tools_are_gated():
    """Tools that auth, sign, or broadcast must be gated on a configured signer."""
    gated = {name for name, _s, _e, gated in ALL_TOOLS if gated}
    expected = {
        "botcoin_bind_agent_id",
        "botcoin_request_challenge",
        "botcoin_submit_artifact",
        "botcoin_post_receipt",
        "botcoin_claim_rewards",
        "botcoin_stake",
        "botcoin_unstake",
        "botcoin_withdraw_stake",
        "botcoin_autostart",
        "botcoin_autostop",
    }
    assert gated == expected


def test_plugin_yaml_lists_match_schemas():
    """plugin.yaml provides_tools must match the runtime tool set exactly."""
    import re
    plugin_yaml = (Path(__file__).resolve().parents[1] / "plugin.yaml").read_text()
    declared = set(re.findall(r"^\s*-\s+(botcoin_\w+)\s*$", plugin_yaml, re.MULTILINE))
    runtime = {name for name, _s, _e, _g in ALL_TOOLS}
    assert declared == runtime, (declared ^ runtime, "drift between plugin.yaml and schemas.py")
