"""solver._parse_output and _iter_json_objects — robust to noisy model output."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from hermes_botcoin.solver import _iter_json_objects, _parse_output


def test_clean_json_object():
    text = json.dumps({
        "artifact": "Acme corp Berlin Smith Germany 31 12+34=46 etc",
        "reasoningTrace": [],
        "submittedAnswers": {"q01": "Acme"},
    })
    art, trace, answers = _parse_output(text)
    assert art.startswith("Acme corp")
    assert trace == []
    assert answers == {"q01": "Acme"}


def test_code_fenced_json():
    payload = {"artifact": "hello world", "reasoningTrace": []}
    text = "```json\n" + json.dumps(payload) + "\n```"
    art, trace, _ = _parse_output(text)
    assert art == "hello world"


def test_prose_then_json():
    """Reasoning models sometimes write a paragraph then the JSON."""
    payload = {"artifact": "x y z", "reasoningTrace": []}
    text = "Here is my reasoning. The answer is below.\n\n" + json.dumps(payload)
    art, _, _ = _parse_output(text)
    assert art == "x y z"


def test_nested_braces_in_strings_dont_truncate():
    """Regex parser used to truncate at the first `}`; raw_decode must not."""
    payload = {
        "artifact": "fancy",
        "reasoningTrace": [
            {"step_id": "n1", "action": "note", "observation": "{not json: {} {}}"},
        ],
    }
    text = "preamble " + json.dumps(payload) + " postamble"
    art, trace, _ = _parse_output(text)
    assert art == "fancy"
    assert trace[0]["observation"] == "{not json: {} {}}"


def test_first_object_without_artifact_is_skipped():
    """If the model emits diagnostic JSON before the answer, we should still
    find the artifact-bearing object."""
    decoy = json.dumps({"diagnostic": True, "thinking_tokens_used": 1024})
    payload = json.dumps({"artifact": "the real artifact", "reasoningTrace": []})
    text = decoy + "\n\n" + payload
    art, _, _ = _parse_output(text)
    assert art == "the real artifact"


def test_empty_text_raises():
    with pytest.raises(RuntimeError, match="no text"):
        _parse_output("")


def test_no_artifact_anywhere_raises():
    with pytest.raises(RuntimeError, match="could not parse"):
        _parse_output("just some prose without any JSON")


def test_iter_json_objects_skips_invalid():
    text = "junk { not json } more junk " + json.dumps({"a": 1}) + " trailing"
    objs = list(_iter_json_objects(text))
    assert any(o == {"a": 1} for o in objs)


def test_artifact_in_regex_fallback():
    """Even if JSON is broken, regex finds a `\"artifact\": \"...\"` line."""
    text = '{"artifact": "fallback-only", "reasoningTrace": [INVALID]'  # broken JSON
    art, trace, answers = _parse_output(text)
    assert art == "fallback-only"
    assert trace == []
    assert answers is None
