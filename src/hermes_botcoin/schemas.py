"""JSON schemas for every BOTCOIN tool.

The schemas are written to be self-explanatory inside an LLM context window —
descriptions explicitly tell the model what to do, including the exact
artifact / reasoning-trace shape for ``botcoin_submit_artifact``. Keep them
in sync with the live coordinator skill at
https://coordinator.agentmoney.net/.well-known/skill.md.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Read-only / status tools


BOTCOIN_STATUS_SCHEMA = {
    "name": "botcoin_status",
    "description": (
        "Snapshot of the BOTCOIN mining state for the configured miner. Returns: "
        "current epoch, epoch end timestamp, current epoch reward estimate, total "
        "BOTCOIN staked across all miners, active miner count, the local miner "
        "address, configured signer mode (eoa|bankr|null), and a `configured` flag. "
        "Cached for 60s. Cheap — call it whenever the user asks about mining state."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "force_refresh": {
                "type": "boolean",
                "description": "Skip the 60s cache and re-fetch from the coordinator.",
                "default": False,
            }
        },
        "required": [],
    },
}

BOTCOIN_SETUP_CHECK_SCHEMA = {
    "name": "botcoin_setup_check",
    "description": (
        "Diagnose whether this Hermes session is fully configured for BOTCOIN mining. "
        "Returns a structured checklist: signer_mode, env vars present, coordinator "
        "reachable, miner stake on Base meets Tier 1 minimum (5,000,000 BOTCOIN), "
        "ETH balance for gas, and any actionable next steps. Run this BEFORE "
        "attempting your first mine; safe to call any time."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}

BOTCOIN_SCORECARD_SCHEMA = {
    "name": "botcoin_scorecard",
    "description": (
        "Fetch the EIP-712 signed mining scorecard for an address (defaults to the "
        "configured miner). Useful for ERC-8004 reputation context — pass the result "
        "as evidence of past mining activity."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "address": {
                "type": "string",
                "description": "0x-prefixed Base address. Defaults to the configured miner.",
            },
            "as_of": {
                "type": "integer",
                "description": "Optional historical snapshot pin (Unix seconds).",
            },
        },
        "required": [],
    },
}


# ---------------------------------------------------------------------------
# Mining tools


BOTCOIN_REQUEST_CHALLENGE_SCHEMA = {
    "name": "botcoin_request_challenge",
    "description": (
        "Request a fresh BOTCOIN mining challenge from the coordinator. Returns the "
        "full challenge: doc (numbered prose paragraphs), questions, constraints, "
        "valid entity list, solveInstructions, challengeId, challengeManifestHash, "
        "and traceSubmission rules. **You** are the solver — read the doc, satisfy "
        "every constraint, then call botcoin_submit_artifact with your artifact + "
        "reasoning trace. Coordinator rate limit: ~1 request per miner per 60s."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "client_nonce": {
                "type": "string",
                "description": "Optional client nonce (max 64 chars). Auto-generated if omitted.",
            }
        },
        "required": [],
    },
}

BOTCOIN_SUBMIT_ARTIFACT_SCHEMA = {
    "name": "botcoin_submit_artifact",
    "description": (
        "Submit your solved artifact + reasoning trace for verification.\n\n"
        "**Artifact**: a single-line string that satisfies EVERY constraint in the "
        "challenge response simultaneously (exact word count, required substrings, "
        "derived prime number, equation `A+B=C`, acrostic, forbidden letter, etc.). "
        "Trim whitespace before submitting.\n\n"
        "**Reasoning trace (v3)**: a JSON array of steps. Each step has a string "
        "`step_id` (e.g. `\"e1\"`, `\"c1\"`) and an `action`:\n"
        "- `extract_fact`: `{step_id, action: \"extract_fact\", targetEntity, attribute, "
        "  valueExtracted, source}`. `attribute` must be the canonical domain attribute "
        "  named in the challenge payload's `solveInstructions` / `traceReference`. "
        "  `source` is `paragraph_N` matching the doc's numbered paragraphs.\n"
        "- `compute_logic`: `{step_id, action: \"compute_logic\", operation, inputs, "
        "  result}`. `operation` ∈ {add, sum, subtract, multiply, divide, mod, max, min, "
        "  average, next_prime, round, round_nearest, abs_diff, ratio, count, "
        "  compare_equal, compare_greater_than, compare_less_than}. `inputs` is a list "
        "  of prior `step_id` strings and/or literal numbers — NOT integer step "
        "  positions.\n"
        "- Custom actions (`revision`, `backtrack`, `note`, `verify`, ...) are passed "
        "  through verbatim and useful for documenting retries.\n\n"
        "Min 3 steps; max 200; need at least one `extract_fact` and one `compute_logic`. "
        "Citations are verified — the cited paragraph must contain BOTH the entity AND "
        "the value.\n\n"
        "**`submitted_answers`** (when the challenge requires it — see `solveInstructions`): "
        "a flat object keyed by question ID such as `{\"q01\": \"EntityName\", \"q05\": "
        "\"247\", \"q19\": \"Floquet\"}`. Entity-name answers are case-insensitive. "
        "Integer answers must be the exact number as a string. ≥6/10 correct to pass.\n\n"
        "On success the coordinator returns a signed receipt, a `transaction` (mining "
        "receipt calldata), and a `vouchTransaction` (ERC-8004 reputation calldata). "
        "Pass both to botcoin_post_receipt to record on-chain.\n\n"
        "On failure with `retryAllowed: true` (multi-pass mode), you may resubmit using "
        "the SAME challengeId, nonce, and challengeManifestHash with a FRESH artifact and "
        "trace (and optionally a `revision` step at the start documenting what changed)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "challenge_id": {"type": "string"},
            "nonce": {
                "type": "string",
                "description": "The exact nonce returned by botcoin_request_challenge.",
            },
            "challenge_manifest_hash": {
                "type": "string",
                "description": "The exact challengeManifestHash from the challenge response.",
            },
            "artifact": {
                "type": "string",
                "description": "Your single-line artifact string. No leading/trailing whitespace.",
            },
            "reasoning_trace": {
                "type": "array",
                "description": (
                    "Ordered list of trace steps with string `step_id`s. Min 3, max 200. "
                    "See the tool description for the exact v3 step shapes."
                ),
                "items": {"type": "object"},
            },
            "model_version": {
                "type": "string",
                "description": "Identifier of the model that produced the artifact (e.g. anthropic/claude-opus-4-7, venice/zai-org-glm-5.1).",
            },
            "submitted_answers": {
                "type": ["object", "array"],
                "description": (
                    "Question answers when required by the challenge. PREFER a flat object "
                    "keyed by question ID (e.g. {\"q01\": \"EntityName\"}). An array is also "
                    "accepted and mapped to q01/q02/... by 1-indexed position."
                ),
            },
            "pool": {
                "type": "boolean",
                "description": "Set true when mining for a pool contract (wraps the receipt for pool execution).",
                "default": False,
            },
        },
        "required": [
            "challenge_id",
            "nonce",
            "challenge_manifest_hash",
            "artifact",
            "reasoning_trace",
            "model_version",
        ],
    },
}

BOTCOIN_POST_RECEIPT_SCHEMA = {
    "name": "botcoin_post_receipt",
    "description": (
        "Broadcast the coordinator-signed transactions returned by botcoin_submit_artifact "
        "to Base. Always pass the `transaction` object (the mining receipt — synchronous, "
        "blocks until confirmation). When the submit response also includes a "
        "`vouchTransaction` (ERC-8004 reputation registry), pass it as `vouch_transaction` "
        "to fire-and-forget broadcast it in the same call. Returns the receipt tx hash "
        "(confirmed) and, when applicable, the vouch tx hash (submitted)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "transaction": {
                "type": "object",
                "description": "The `transaction` object from the submit response: {to, chainId, value, data}.",
                "properties": {
                    "to": {"type": "string"},
                    "chainId": {"type": "integer"},
                    "value": {"type": ["string", "integer"]},
                    "data": {"type": "string"},
                },
                "required": ["to", "chainId", "data"],
            },
            "vouch_transaction": {
                "type": "object",
                "description": (
                    "Optional `vouchTransaction` from the submit response. When provided, "
                    "broadcast non-blocking (waitForConfirmation=false) so the receipt is "
                    "the only thing that gates the next mining round."
                ),
                "properties": {
                    "to": {"type": "string"},
                    "chainId": {"type": "integer"},
                    "value": {"type": ["string", "integer"]},
                    "data": {"type": "string"},
                },
            },
            "wait_for_confirmation": {
                "type": "boolean",
                "default": True,
                "description": "Block on the receipt tx (recommended). The vouch tx is always non-blocking.",
            },
        },
        "required": ["transaction"],
    },
}


# ---------------------------------------------------------------------------
# Reward / stake tools


BOTCOIN_CLAIM_REWARDS_SCHEMA = {
    "name": "botcoin_claim_rewards",
    "description": (
        "Claim BOTCOIN rewards for one or more finalized epochs. Fetches the "
        "calldata from the coordinator and broadcasts via the configured signer. "
        "Bonus rewards (if any) are claimed in the same call when `include_bonus=true`."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "epoch_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "List of finalized epoch IDs to claim. e.g. [41, 42].",
            },
            "include_bonus": {
                "type": "boolean",
                "default": True,
                "description": "Also claim bonus epoch rewards (when present) in a separate tx.",
            },
            "pool_target": {
                "type": "string",
                "description": "Pool contract address to wrap the claim through (advanced).",
            },
        },
        "required": ["epoch_ids"],
    },
}

BOTCOIN_STAKE_SCHEMA = {
    "name": "botcoin_stake",
    "description": (
        "Stake BOTCOIN on the V3 mining contract to become eligible for mining. "
        "Tier 1 minimum is 5,000,000 BOTCOIN; tiers 2-5 are 10M / 25M / 50M / 100M "
        "with 205 / 520 / 1075 / 2200 credits per solve respectively. Two transactions "
        "are sent: ERC-20 approve, then stake. Returns both tx hashes."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "amount": {
                "type": "string",
                "description": (
                    "Amount of BOTCOIN to stake, expressed as a decimal string in "
                    "whole tokens (e.g. \"5000000\" for Tier 1)."
                ),
            }
        },
        "required": ["amount"],
    },
}

BOTCOIN_UNSTAKE_SCHEMA = {
    "name": "botcoin_unstake",
    "description": (
        "Begin unstaking. Removes mining eligibility immediately and starts a 24h "
        "cooldown. Use botcoin_withdraw_stake after the cooldown ends. To cancel "
        "before cooldown, pass `cancel: true`."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "cancel": {
                "type": "boolean",
                "default": False,
                "description": "Cancel a pending unstake and restore mining eligibility.",
            }
        },
        "required": [],
    },
}

BOTCOIN_WITHDRAW_STAKE_SCHEMA = {
    "name": "botcoin_withdraw_stake",
    "description": (
        "Withdraw previously-unstaked BOTCOIN after the 24h cooldown has elapsed. "
        "If withdrawableAt is in the future, this tool returns the wait time and "
        "does NOT submit a tx."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}


ALL_TOOLS = [
    ("botcoin_status", BOTCOIN_STATUS_SCHEMA, "⛏"),
    ("botcoin_setup_check", BOTCOIN_SETUP_CHECK_SCHEMA, "🩺"),
    ("botcoin_scorecard", BOTCOIN_SCORECARD_SCHEMA, "🪪"),
    ("botcoin_request_challenge", BOTCOIN_REQUEST_CHALLENGE_SCHEMA, "🧩"),
    ("botcoin_submit_artifact", BOTCOIN_SUBMIT_ARTIFACT_SCHEMA, "✅"),
    ("botcoin_post_receipt", BOTCOIN_POST_RECEIPT_SCHEMA, "📜"),
    ("botcoin_claim_rewards", BOTCOIN_CLAIM_REWARDS_SCHEMA, "💰"),
    ("botcoin_stake", BOTCOIN_STAKE_SCHEMA, "🔒"),
    ("botcoin_unstake", BOTCOIN_UNSTAKE_SCHEMA, "🔓"),
    ("botcoin_withdraw_stake", BOTCOIN_WITHDRAW_STAKE_SCHEMA, "🏦"),
]
