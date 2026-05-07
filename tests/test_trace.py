"""Tests for hermes_botcoin.trace.normalize_trace + serialize_submitted_answers."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hermes_botcoin.trace import (
    SUPPORTED_OPS,
    normalize_trace,
    serialize_submitted_answers,
)


def test_empty():
    assert normalize_trace(None) == []
    assert normalize_trace([]) == []


def test_canonical_v3_passthrough():
    """Skill-shaped traces should pass through without semantic changes."""
    raw = [
        {"step_id": "e1", "action": "extract_fact",
         "targetEntity": "Acme", "attribute": "domain_metric_a",
         "valueExtracted": 4523, "source": "paragraph_15"},
        {"step_id": "c1", "action": "compute_logic",
         "operation": "mod", "inputs": ["e1", 100], "result": 23},
    ]
    out = normalize_trace(raw)
    assert [r["step_id"] for r in out] == ["e1", "c1"]
    assert out[0]["targetEntity"] == "Acme"
    assert out[1]["inputs"] == ["e1", 100]
    assert out[1]["operation"] == "mod"


def test_legacy_integer_step_input_resolved_to_string_step_id():
    """Old miner.py-style integer-step references must rewrite to string step_ids."""
    raw = [
        {"step": 1, "action": "extract_fact", "targetEntity": "A",
         "attribute": "x", "valueExtracted": 100, "source": "paragraph_1"},
        {"step": 2, "action": "compute_logic", "operation": "mod",
         "inputs": [1, 100], "result": 0},  # references step 1
    ]
    out = normalize_trace(raw)
    assert "step" not in out[0]
    assert "step" not in out[1]
    assert "task" not in out[1]
    e_id = out[0]["step_id"]
    assert isinstance(e_id, str)
    assert out[1]["inputs"] == [e_id, 100]


def test_step_id_string_inputs_passthrough():
    raw = [
        {"step_id": "extract_employees", "action": "extract_fact",
         "targetEntity": "Acme", "attribute": "employees",
         "valueExtracted": 4807, "source": "paragraph_5"},
        {"step_id": "compute_prime", "action": "compute_logic",
         "operation": "next_prime", "inputs": ["extract_employees", 11], "result": 89},
    ]
    out = normalize_trace(raw)
    assert out[0]["step_id"] == "extract_employees"
    assert out[1]["inputs"] == ["extract_employees", 11]


def test_unknown_op_preserved():
    """We don't reject unsupported ops — coordinator validates server-side."""
    raw = [{"step_id": "c1", "action": "compute_logic",
            "operation": "calculate_prime_constraint", "inputs": [], "result": 7}]
    out = normalize_trace(raw)
    assert out[0]["operation"] == "calculate_prime_constraint"


def test_revision_step_passthrough():
    raw = [{"step_id": "rev1", "action": "revision",
            "note": "Previous attempt passed 5/8 — re-examining acrostic letter sequence."}]
    out = normalize_trace(raw)
    assert out[0]["action"] == "revision"
    assert out[0]["note"].startswith("Previous attempt passed")


def test_no_step_id_assigns_action_specific_slug():
    raw = [
        {"action": "extract_fact", "targetEntity": "A", "attribute": "x",
         "valueExtracted": 1, "source": "paragraph_1"},
        {"action": "compute_logic", "operation": "add", "inputs": [], "result": 2},
        {"action": "revision", "note": "..."},
    ]
    out = normalize_trace(raw)
    assert out[0]["step_id"].startswith("e")
    assert out[1]["step_id"].startswith("c")
    assert out[2]["step_id"].startswith("rev")


def test_drops_legacy_step_and_task():
    raw = [{"step": 1, "task": "solve_question_1", "action": "extract_fact",
            "targetEntity": "A", "attribute": "x", "valueExtracted": 1,
            "source": "paragraph_1"}]
    out = normalize_trace(raw)
    assert "step" not in out[0]
    assert "task" not in out[0]
    assert out[0]["step_id"]


def test_camelcase_round_op_normalized():
    raw = [{"step_id": "c1", "action": "compute_logic", "operation": "roundNearest",
            "inputs": [], "result": 3}]
    out = normalize_trace(raw)
    assert out[0]["operation"] == "round_nearest"


def test_supported_ops_complete():
    """Sanity check — must include every op the live skill names."""
    expected = {"add", "sum", "subtract", "multiply", "divide", "mod",
                "max", "min", "average", "next_prime", "round", "round_nearest",
                "abs_diff", "ratio", "count", "compare_equal",
                "compare_greater_than", "compare_less_than"}
    assert expected.issubset(SUPPORTED_OPS)


def test_serialize_submitted_answers_dict_passthrough():
    out = serialize_submitted_answers({"q01": "EntityName", "q05": "247"})
    assert out == {"q01": "EntityName", "q05": "247"}


def test_serialize_submitted_answers_array_to_object():
    out = serialize_submitted_answers(["EntityName", "OtherEntity", 247])
    assert out == {"q01": "EntityName", "q02": "OtherEntity", "q03": "247"}


def test_serialize_submitted_answers_none():
    assert serialize_submitted_answers(None) is None
    assert serialize_submitted_answers([]) is None
    assert serialize_submitted_answers({}) is None


def test_collision_handling():
    raw = [
        {"step_id": "e1", "action": "extract_fact", "targetEntity": "A",
         "attribute": "x", "valueExtracted": 1, "source": "paragraph_1"},
        {"step_id": "e1", "action": "extract_fact", "targetEntity": "B",
         "attribute": "y", "valueExtracted": 2, "source": "paragraph_2"},
    ]
    out = normalize_trace(raw)
    assert out[0]["step_id"] != out[1]["step_id"]
