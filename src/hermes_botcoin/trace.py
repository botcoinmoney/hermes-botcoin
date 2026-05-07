"""Reasoning-trace normalization to the canonical v3 schema.

Authoritative reference: https://agentmoney.net/skill.md (mirrored at
https://coordinator.agentmoney.net/.well-known/skill.md). Last verified
2026-05-07.

Canonical shape:

  - Each step is a JSON object with **`step_id`** (unique string, e.g. "e1",
    "c1") and an `action` field. NOT an integer `step`.
  - `extract_fact` carries `targetEntity`, `attribute`, `valueExtracted`,
    `source` (in `paragraph_N` form).
  - `compute_logic` carries `operation` (one of the validated ops listed
    in :data:`SUPPORTED_OPS`), `inputs` (list of prior `step_id` strings or
    literal numbers), and `result`.
  - Custom action types (`revision`, `backtrack`, `note`, `verify`, etc.)
    are passed through verbatim — they are not validated server-side but
    are recorded.

This module is permissive on input (accepts legacy integer-step traces,
missing `step_id`s, `step`/`task` artefacts from the older miner) and
strict on output. The output is always exactly what the coordinator expects.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional


SUPPORTED_OPS = {
    "add", "sum", "subtract", "multiply", "divide", "mod", "max", "min",
    "average", "next_prime", "round", "round_nearest", "abs_diff", "ratio",
    "count", "compare_equal", "compare_greater_than", "compare_less_than",
}


def _slug_for_action(action: str, used: set[str], idx: int) -> str:
    """Derive a step_id when one isn't provided.

    Convention used by the official skill examples:
      - extract_fact → e1, e2, ...
      - compute_logic → c1, c2, ...
      - revision → rev1, rev2, ...
      - other → s1, s2, ...
    """
    prefix = {
        "extract_fact": "e",
        "compute_logic": "c",
        "revision": "rev",
        "backtrack": "back",
        "note": "n",
        "verify": "v",
    }.get(action, "s")
    candidate = f"{prefix}{idx}"
    n = idx
    while candidate in used:
        n += 1
        candidate = f"{prefix}{n}"
    return candidate


def normalize_trace(trace: Optional[Iterable[Any]]) -> list[dict[str, Any]]:
    """Return a coordinator-compatible v3 trace.

    The coordinator validates strictly: every `extract_fact` must carry
    `targetEntity`/`attribute`/`valueExtracted`/`source`; every
    `compute_logic` must use one of :data:`SUPPORTED_OPS` and reference
    prior `step_id`s as strings (or literal numbers).

    This function:
      - assigns a string `step_id` when missing (or coerces an integer one
        to a stable string);
      - rewrites `compute_logic.inputs` so any integer "1-indexed step"
        references from the legacy miner schema become the new string
        `step_id`s;
      - drops `step` and `task` fields the v3 schema doesn't use;
      - never reorders steps.
    """
    if not trace:
        return []
    raw = [r for r in trace if isinstance(r, dict)]
    if not raw:
        return []

    # First pass: assign / sanitize step_id strings, build position→id and id→id maps.
    used_ids: set[str] = set()
    pos_to_id: dict[int, str] = {}
    legacy_step_to_id: dict[int, str] = {}  # legacy integer "step" → string step_id
    legacy_step_id_to_id: dict[str, str] = {}  # original step_id → final step_id (passthrough most of the time)
    interim: list[dict[str, Any]] = []

    for i, row in enumerate(raw):
        action = str(row.get("action", "extract_fact"))
        sid_raw = row.get("step_id")
        sid: str
        if isinstance(sid_raw, str) and sid_raw.strip():
            sid = sid_raw.strip()
        elif isinstance(sid_raw, (int, float)):
            sid = f"s{int(sid_raw)}"
        else:
            sid = _slug_for_action(action, used_ids, i + 1)
        # Disambiguate collisions
        base = sid
        n = 1
        while sid in used_ids:
            n += 1
            sid = f"{base}_{n}"
        used_ids.add(sid)
        pos_to_id[i] = sid

        # Capture legacy integer "step" mapping if present
        legacy_step = row.get("step")
        if isinstance(legacy_step, (int, float)):
            legacy_step_to_id[int(legacy_step)] = sid
        # Capture original step_id mapping (no-op rename, but keeps inputs lookup correct
        # if we ever rename above)
        if isinstance(sid_raw, str) and sid_raw.strip():
            legacy_step_id_to_id[sid_raw.strip()] = sid

        out: dict[str, Any] = {"step_id": sid, "action": action}
        if action == "extract_fact":
            out["targetEntity"] = str(row.get("targetEntity", "") or "")
            out["attribute"] = str(row.get("attribute", "") or "")
            out["valueExtracted"] = row.get("valueExtracted")
            out["source"] = str(row.get("source", "") or "")
        elif action == "compute_logic":
            op = str(row.get("operation", "") or "")
            if op == "roundNearest":  # camelCase fix
                op = "round_nearest"
            out["operation"] = op
            out["inputs"] = list(row.get("inputs") or [])
            out["result"] = row.get("result")
        else:
            # Pass through every other field for custom action types.
            for k, v in row.items():
                if k in ("action", "step", "task", "step_id"):
                    continue
                out[k] = v
        interim.append(out)

    # Second pass: rewrite compute_logic.inputs to use the new string step_ids.
    for row in interim:
        if row.get("action") != "compute_logic":
            continue
        fixed: list[Any] = []
        for x in row.get("inputs") or []:
            # 1) Original string step_id → final step_id (usually identity)
            if isinstance(x, str) and x in legacy_step_id_to_id:
                fixed.append(legacy_step_id_to_id[x])
                continue
            # 2) Legacy integer 1-indexed step number → string step_id
            if isinstance(x, (int, float)) and int(x) in legacy_step_to_id:
                fixed.append(legacy_step_to_id[int(x)])
                continue
            # 3) Literal numeric value — keep as-is
            if isinstance(x, (int, float)):
                fixed.append(x)
                continue
            # 4) Anything else (descriptive strings, dicts) — keep as-is.
            #    The coordinator may reject these, but normalize_trace's job
            #    is to preserve solver intent, not invent values.
            fixed.append(x)
        row["inputs"] = fixed

    return interim


def serialize_submitted_answers(answers: Any) -> Optional[dict[str, str]]:
    """Coerce ``submittedAnswers`` to the coordinator's flat-object shape.

    The skill mandates ``{"q01": "EntityName", "q05": "247", ...}`` (string
    values, question-id keys). Accepts:
      - dict already in the right shape (passes through)
      - list/tuple — converts to ``q01``/``q02``/... by 1-indexed position
      - None / empty — returns None so callers can omit the field entirely.
    """
    if not answers:
        return None
    if isinstance(answers, dict):
        return {str(k): "" if v is None else str(v) for k, v in answers.items() if k}
    if isinstance(answers, (list, tuple)):
        return {f"q{i + 1:02d}": "" if v is None else str(v) for i, v in enumerate(answers)}
    return None
