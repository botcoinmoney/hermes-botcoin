"""Multi-provider LLM solver for headless / cron mining.

This module is **only** used when there is no Hermes agent in the loop —
i.e. ``hermes-botcoin-mine`` (the cron console script) or ``hermes botcoin
mine --loop --solver=...``. In normal interactive Hermes use the agent
solves with whatever provider Hermes is configured for, and this module is
never imported.

Supported providers (chosen via ``BOTCOIN_SOLVER_PROVIDER`` or the matching
``--solver`` flag):

* ``venice`` — **Recommended.** Venice.ai's OpenAI-compatible API at
  ``https://api.venice.ai/api/v1``. No data retention, OpenAI-compatible,
  excellent reasoning models. Set ``VENICE_API_KEY``. Default model:
  ``zai-org-glm-5.1`` (200k context, deep reasoning). The solver passes
  ``venice_parameters.include_venice_system_prompt: false`` so our system
  prompt isn't shadowed by Venice's defaults, and ``response_format`` is
  set to JSON mode for clean parsing.
* ``anthropic`` — Anthropic Messages API (extended thinking enabled).
* ``openai`` — OpenAI Chat Completions with JSON mode.
* ``openrouter`` — OpenAI-compatible /chat/completions surface.
* ``deepseek`` — OpenAI-compatible /chat/completions surface.

Each provider expects its own API key in env (``VENICE_API_KEY``,
``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``, ``OPENROUTER_API_KEY``,
``DEEPSEEK_API_KEY``). The function never logs the key. The solver returns
``(artifact, trace, model_version_string)``.

Schema source-of-truth: https://agentmoney.net/skill.md (verified 2026-05-07).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "You are an autonomous BOTCOIN miner solving a proof-of-inference challenge. "
    "Read the document, answer every question, derive every constraint, and produce "
    "a single-line artifact that satisfies ALL constraints simultaneously. Then build "
    "a structured v3 reasoning trace (extract_fact + compute_logic steps with string "
    "step_id values like \"e1\", \"c1\") that cites paragraph_N references. "
    "Respond with a single JSON object and nothing else: "
    '{"artifact": "<single-line>", "reasoningTrace": [<steps>], '
    '"submittedAnswers": {"q01": "...", "q05": "...", ...}} — '
    "include submittedAnswers when the challenge requires it."
)


def build_solver_prompt(challenge: dict) -> str:
    """Render the challenge into the canonical solver prompt.

    Mirrors https://agentmoney.net/skill.md so any change there can be
    reflected here in lockstep.
    """
    doc = challenge.get("doc", "")
    questions = challenge.get("questions") or []
    constraints = challenge.get("constraints") or []
    entities = challenge.get("entities") or challenge.get("companies") or []
    instructions = challenge.get("solveInstructions", "")
    trace_ref = challenge.get("traceReference") or challenge.get("documentMap")
    trace_sub = challenge.get("traceSubmission") or {}

    def _norm(x: Any) -> str:
        if isinstance(x, dict):
            return str(x.get("text") or x.get("key") or x)
        return str(x)

    q_lines = "\n".join(f"Q{i + 1}: {_norm(q)}" for i, q in enumerate(questions))
    c_lines = "\n".join(f"C{i + 1}: {_norm(c)}" for i, c in enumerate(constraints))
    trace_block = (
        "\n\n## TraceReference (use these paragraphs for citations)\n" + json.dumps(trace_ref, indent=2)
        if trace_ref
        else ""
    )
    answers_block = ""
    if trace_sub.get("required"):
        min_steps = trace_sub.get("minSteps", 3)
        max_steps = trace_sub.get("maxSteps", 200)
        cite_method = trace_sub.get("citationMethod", "paragraph_N")
        cite_rate = trace_sub.get("citationTargetRate", 0.8)
        trace_block += (
            f"\n\n## Trace requirements (binding)\n"
            f"- Min {min_steps} / max {max_steps} steps. ≥1 extract_fact + ≥1 compute_logic.\n"
            f"- citationMethod: {cite_method}. citationTargetRate: {cite_rate}.\n"
            f"- Each cited paragraph must contain BOTH the entity AND the value."
        )
    if "submittedAnswers" in (trace_sub.get("submitFields") or []) or "submittedAnswers" in (
        instructions or ""
    ):
        answers_block = (
            '\n\n## submittedAnswers (required)\n'
            "Include a flat object keyed by question ID matching the format the payload "
            "uses (typically `q01`, `q02`, …): "
            '`{"q01": "EntityName", "q05": "247", ...}`. ≥6/10 must be correct.'
        )

    return (
        "You are solving a BOTCOIN mining challenge. Produce ONE single-line artifact "
        "that satisfies every listed constraint, plus a v3 reasoning trace.\n\n"
        f"## Document (paragraphs are pre-numbered as paragraph_N — cite those exact labels)\n{doc}\n\n"
        f"## Questions\n{q_lines}\n\n"
        f"## Valid entity names\n{json.dumps(entities)}{trace_block}\n\n"
        f"## Constraints\n{c_lines}\n\n"
        f"## Solve instructions (authoritative for this challenge)\n{instructions}{answers_block}\n\n"
        "## Output format — exactly one JSON object\n"
        '{"artifact": "<single-line artifact>", "reasoningTrace": [<steps>], '
        '"submittedAnswers": {"q01": "...", ...}}\n\n'
        "## Trace step shape (the coordinator validates this strictly)\n"
        '- extract_fact: {"step_id":"e1","action":"extract_fact",'
        '"targetEntity":"<entity from entities[]>","attribute":"<canonical-attr>",'
        '"valueExtracted":<value>,"source":"paragraph_N"}\n'
        '- compute_logic: {"step_id":"c1","action":"compute_logic",'
        '"operation":"<one of: add, sum, subtract, multiply, divide, mod, max, min, '
        'average, next_prime, round, round_nearest, abs_diff, ratio, count, '
        'compare_equal, compare_greater_than, compare_less_than>",'
        '"inputs":[<prior step_id strings or literal numbers>],"result":<value>}\n'
        "Step IDs are STRINGS (e.g. \"e1\", \"c1\"), not integers. inputs reference "
        "PRIOR step_ids by string, not by position. Cite the paragraph that contains "
        "BOTH the entity AND the extracted value."
    )


# ---------------------------------------------------------------------------
# HTTP helpers


def _http_post_json(url: str, *, headers: dict, body: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(
        url=url,
        data=json.dumps(body).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _retry_http(call, *, attempts: int = 5, base_wait: float = 30.0):
    for i in range(attempts):
        try:
            return call()
        except urllib.error.HTTPError as exc:
            body_preview = ""
            try:
                body_preview = exc.read().decode("utf-8", errors="replace")[:600]
            except Exception:
                pass
            if exc.code == 429:
                wait = base_wait + i * 15
            elif 500 <= exc.code <= 599:
                wait = base_wait + i * 20
            elif exc.code in (401, 403):
                raise RuntimeError(f"LLM auth/billing error {exc.code}: {body_preview}") from exc
            elif exc.code == 400:
                # Surface the actual error body — provider 400s carry the reason
                # (model_not_found, invalid param, rate-limit-like throttling, …).
                raise RuntimeError(f"LLM 400: {body_preview}") from exc
            else:
                raise RuntimeError(f"LLM HTTP {exc.code}: {body_preview}") from exc
            logger.info("LLM HTTP %s — waiting %.0fs (attempt %d/%d)", exc.code, wait, i + 1, attempts)
            time.sleep(wait)
        except (TimeoutError, OSError) as exc:
            if i >= 2:
                raise RuntimeError("LLM timeout 3x — giving up") from exc
            logger.info("LLM timeout — retrying (%d/%d)", i + 1, attempts)
            time.sleep(15)
    raise RuntimeError("LLM retry budget exhausted")


# ---------------------------------------------------------------------------
# Provider implementations


def _solve_anthropic(prompt: str, *, model: str, max_tokens: int, thinking_budget: int) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY (or CLAUDE_API_KEY) is required for the anthropic solver")

    body: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }
    # Opus 4.7+ uses adaptive thinking + output_config.effort.
    # Older models (4.6 and earlier) used the {type: enabled, budget_tokens} shape.
    is_opus_47_plus = (
        ("opus-4-7" in model)
        or ("claude-4-7" in model)
        or model.startswith("claude-opus-4-7")
    )
    if thinking_budget > 0:
        if is_opus_47_plus:
            body["thinking"] = {"type": "adaptive"}
            # Map old "thinking_budget" to effort levels.
            effort = "high" if thinking_budget >= 8000 else "medium" if thinking_budget >= 2000 else "low"
            body["output_config"] = {"effort": effort}
        else:
            # Anthropic minimum budget_tokens is 1024 for legacy thinking.
            body["thinking"] = {"type": "enabled", "budget_tokens": max(1024, thinking_budget)}

    def _call():
        return _http_post_json(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            body=body,
            timeout=600,
        )

    data = _retry_http(_call)
    out = ""
    for block in data.get("content", []) or []:
        if isinstance(block, dict) and block.get("type") == "text":
            out += block.get("text", "")
    if not out:
        # Diagnose: log stop reason + content block types so empty responses
        # don't look like silent failures.
        types = [b.get("type") for b in (data.get("content") or []) if isinstance(b, dict)]
        stop = data.get("stop_reason")
        usage = data.get("usage", {})
        raise RuntimeError(
            f"anthropic returned no text content. stop_reason={stop} "
            f"content_types={types} usage={usage}"
        )
    return out


def _solve_openai(prompt: str, *, model: str, max_tokens: int, thinking_budget: int) -> str:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for the openai solver")
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }

    def _call():
        return _http_post_json(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            body=body,
            timeout=300,
        )

    data = _retry_http(_call)
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"openai: empty response: {data}")
    return choices[0].get("message", {}).get("content", "")


def _solve_venice(
    prompt: str,
    *,
    model: str,
    max_tokens: int,
    enable_web_search: str = "off",
    disable_thinking: bool = False,
) -> str:
    """Venice.ai solver — recommended for BOTCOIN mining.

    Venice is OpenAI-compatible (`https://api.venice.ai/api/v1/chat/completions`)
    with privacy-by-default semantics (no data retention) and several reasoning
    models with visible thinking. We pass ``venice_parameters`` to:

    - ``include_venice_system_prompt: false`` — our system prompt isn't
      shadowed by Venice's default persona;
    - ``enable_web_search`` — defaults to ``"off"`` because the doc is the
      authoritative source; the prompt warns the model not to trust web
      content for solving;
    - ``disable_thinking`` — only set on reasoning models when speed > quality.
    """
    api_key = os.environ.get("VENICE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "VENICE_API_KEY is required for the venice solver. Get one at https://venice.ai/settings/api"
        )

    venice_params: dict[str, Any] = {
        "include_venice_system_prompt": False,
        "enable_web_search": enable_web_search,
    }
    if disable_thinking:
        venice_params["disable_thinking"] = True

    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "venice_parameters": venice_params,
    }

    def _call():
        return _http_post_json(
            "https://api.venice.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            body=body,
            timeout=600,  # reasoning models can be slow on long docs
        )

    data = _retry_http(_call)
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"venice: empty response: {data}")
    msg = choices[0].get("message", {})
    # Some Venice reasoning models return both `reasoning_content` and `content`.
    # We only need the structured JSON, which lives in `content`.
    return msg.get("content", "") or msg.get("reasoning_content", "")


def _solve_openai_compatible(
    prompt: str,
    *,
    model: str,
    max_tokens: int,
    base_url: str,
    env_key: str,
) -> str:
    api_key = os.environ.get(env_key)
    if not api_key:
        raise RuntimeError(f"{env_key} is required for this solver")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }

    def _call():
        return _http_post_json(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            body=body,
            timeout=300,
        )

    data = _retry_http(_call)
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"openai-compatible empty response: {data}")
    return choices[0].get("message", {}).get("content", "")


# ---------------------------------------------------------------------------
# Output parsing


def _iter_json_objects(text: str):
    """Yield every top-level JSON object in ``text`` using ``raw_decode``.

    Reasoning models love wrapping their structured output in markdown code
    fences, prose explanations, or both. Regex-based extraction can truncate
    nested braces — :class:`json.JSONDecoder.raw_decode` walks character by
    character starting from each `{` and yields a parsed object as soon as
    one validates, then continues past the consumed span.
    """
    decoder = json.JSONDecoder()
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c != "{":
            i += 1
            continue
        try:
            obj, end = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            i += 1
            continue
        if isinstance(obj, dict):
            yield obj
        i = end


def _parse_output(text: str) -> tuple[str, list[dict[str, Any]], Any]:
    """Parse ``(artifact, reasoningTrace, submittedAnswers)`` from solver text."""
    if not text:
        raise RuntimeError("solver returned no text")

    # 1. Strip code fences if the model wrapped in ```json ... ```
    stripped = text.strip()
    if stripped.startswith("```"):
        # Drop the opening fence line and the trailing fence
        without_open = stripped.split("\n", 1)[1] if "\n" in stripped else stripped[3:]
        if without_open.rstrip().endswith("```"):
            without_open = without_open.rstrip()[:-3]
        stripped = without_open.strip()

    # 2. Try a direct parse of the whole stripped string
    candidates: list[dict] = []
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            candidates.append(parsed)
    except json.JSONDecodeError:
        pass

    # 3. Walk every embedded JSON object and prefer the first one with `artifact`.
    for obj in _iter_json_objects(text):
        candidates.append(obj)

    for parsed in candidates:
        if not isinstance(parsed.get("artifact"), str):
            continue
        artifact = parsed["artifact"].strip()
        trace = parsed.get("reasoningTrace") or parsed.get("reasoningLog") or []
        answers = parsed.get("submittedAnswers")
        if artifact and isinstance(trace, list):
            return artifact, trace, answers

    # 4. Regex fallback for a quoted artifact in malformed JSON
    m = re.search(r"\"artifact\"\s*:\s*\"((?:[^\"\\]|\\.)*)\"", text)
    if m:
        artifact = m.group(1).encode("utf-8").decode("unicode_escape").strip()
        if artifact:
            return artifact, [], None
    raise RuntimeError(f"could not parse artifact from solver output: {text[:600]}")


# ---------------------------------------------------------------------------
# Public entry


# Sensible default models per provider — keeps the cron CLI usable with just
# a provider flag set. Override with --model or BOTCOIN_SOLVER_MODEL.
DEFAULT_MODELS = {
    "venice": "zai-org-glm-5.1",        # 200k ctx, deep reasoning, recommended
    "anthropic": "claude-opus-4-7",
    "openai": "gpt-5.1",
    "openrouter": "anthropic/claude-opus-4.7",
    "deepseek": "deepseek-reasoner",
}


def solve_challenge(
    challenge: dict,
    *,
    provider: str = "venice",
    model: Optional[str] = None,
    max_tokens: int = 16000,
    thinking_budget: int = 12000,
) -> tuple[str, list[dict[str, Any]], Any, str]:
    """Solve ``challenge`` using ``provider`` / ``model``.

    Returns ``(artifact, reasoning_trace, submitted_answers, model_version_string)``.
    """
    prompt = build_solver_prompt(challenge)
    provider = provider.lower()
    model = model or DEFAULT_MODELS.get(provider) or "claude-opus-4-7"

    if provider == "venice":
        text = _solve_venice(prompt, model=model, max_tokens=max_tokens)
        version = f"venice/{model}"
    elif provider == "anthropic":
        text = _solve_anthropic(
            prompt, model=model, max_tokens=max_tokens, thinking_budget=thinking_budget
        )
        version = f"anthropic/{model}"
    elif provider == "openai":
        text = _solve_openai(
            prompt, model=model, max_tokens=max_tokens, thinking_budget=thinking_budget
        )
        version = f"openai/{model}"
    elif provider == "openrouter":
        text = _solve_openai_compatible(
            prompt, model=model, max_tokens=max_tokens,
            base_url="https://openrouter.ai/api/v1",
            env_key="OPENROUTER_API_KEY",
        )
        version = f"openrouter/{model}"
    elif provider == "deepseek":
        text = _solve_openai_compatible(
            prompt, model=model, max_tokens=max_tokens,
            base_url="https://api.deepseek.com/v1",
            env_key="DEEPSEEK_API_KEY",
        )
        version = f"deepseek/{model}"
    else:
        raise RuntimeError(f"unsupported solver provider: {provider!r}")

    artifact, trace, answers = _parse_output(text)
    return artifact, trace, answers, version
