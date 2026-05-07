"""Tool schemas must satisfy a few invariants Hermes' registry asserts implicitly."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hermes_botcoin.schemas import ALL_TOOLS
from hermes_botcoin.tools import HANDLERS


def test_every_schema_declares_required_keys():
    for name, schema, _emoji in ALL_TOOLS:
        assert schema["name"] == name, f"{name} schema name mismatch"
        assert isinstance(schema.get("description"), str) and schema["description"], name
        params = schema["parameters"]
        assert params["type"] == "object", name
        assert "properties" in params, name
        assert "required" in params, name


def test_every_schema_has_a_handler():
    for name, _schema, _emoji in ALL_TOOLS:
        assert name in HANDLERS, f"missing handler for {name}"
        assert callable(HANDLERS[name])


def test_no_duplicate_tool_names():
    names = [name for name, _s, _e in ALL_TOOLS]
    assert len(names) == len(set(names))
