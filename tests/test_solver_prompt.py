"""Solver prompt rendering — make sure the canonical schema is taught correctly."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hermes_botcoin.solver import (  # noqa: E402
    DEFAULT_MODELS,
    SYSTEM_PROMPT,
    build_solver_prompt,
)


def test_default_models_cover_all_providers():
    for p in ["venice", "anthropic", "openai", "openrouter", "deepseek"]:
        assert p in DEFAULT_MODELS
        assert DEFAULT_MODELS[p]


def test_venice_default_model_pinned():
    assert DEFAULT_MODELS["venice"] == "zai-org-glm-5.1"


def test_system_prompt_teaches_canonical_step_id():
    assert "step_id" in SYSTEM_PROMPT
    assert "submittedAnswers" in SYSTEM_PROMPT


def test_solver_prompt_includes_all_challenge_sections():
    challenge = {
        "doc": "[paragraph_1] Acme Corp is based in Berlin. [paragraph_2] CEO is Mary Smith.",
        "questions": ["Q1", "Q2"],
        "constraints": ["C1", "C2"],
        "entities": ["Acme Corp"],
        "solveInstructions": "Use canonical attribute names.",
        "traceReference": {"paragraph_1": ["Acme Corp.hqCity"]},
        "traceSubmission": {
            "required": True,
            "minSteps": 3,
            "maxSteps": 200,
            "citationMethod": "paragraph_N",
            "citationTargetRate": 0.8,
            "submitFields": ["miner", "challengeId", "submittedAnswers"],
        },
    }
    out = build_solver_prompt(challenge)
    for marker in ["paragraph_1", "Acme Corp", "Q1", "C1", "step_id",
                   "compute_logic", "extract_fact", "TraceReference",
                   "Trace requirements", "submittedAnswers"]:
        assert marker in out, f"missing: {marker}"


def test_solver_prompt_omits_trace_block_when_not_required():
    challenge = {"doc": "x", "questions": [], "constraints": [],
                 "entities": [], "solveInstructions": "",
                 "traceSubmission": {"required": False}}
    out = build_solver_prompt(challenge)
    assert "Trace requirements (binding)" not in out
