"""pre_llm_call discoverability — recall on mining-relevant prompts; precision
on unrelated prompts. Auditor required behavioral coverage beyond smoke.

A 50-prompt fixture (25 relevant + 25 unrelated) bounds keyword-list drift."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hermes_botcoin import hooks  # noqa: E402
from hermes_botcoin.status import StatusSnapshot  # noqa: E402


_RELEVANT = [
    "How can I mine botcoin?",
    "Tell me how to earn BOTCOIN",
    "What is botcoin?",
    "How does proof of inference work?",
    "Set me up to earn passive income from my agent",
    "Can my agent stake BOTCOIN?",
    "Is there an agent native currency I can mine?",
    "Walk me through the BOTCOIN mining flow",
    "I want to claim my mining rewards",
    "What's my staked balance on AgentMoney?",
    "Bind my ERC-8004 agentId to the miner",
    "Start the autonomous botcoin miner",
    "Stop mining for now",
    "How many BOTCOIN credits did I earn this epoch?",
    "Pull my BOTCOIN scorecard",
    "I'd like to set up agent earnings",
    "Help me become a BOTCOIN miner",
    "Show me agentmoney mining strategy",
    "Can I solve a challenge for BOTCOIN?",
    "Submit a receipt to the V3 mining contract",
    "Estimate the next epoch reward for botcoin",
    "Move my staked BOTCOIN up a tier",
    "I have ETH on Base — can I get into BOTCOIN mining?",
    "What does it take to start mining BOTCOIN today?",
    "Is bot coin still mineable as of this epoch?",
]

_UNRELATED = [
    "Refactor this Python function for readability",
    "Explain how transformer attention works",
    "Generate a haiku about autumn rain",
    "Translate the previous paragraph to French",
    "What's a good React state-management pattern?",
    "Write a SQL query for the top 10 customers by revenue",
    "Plan a 30 minute beginner workout",
    "Summarize this PDF in three bullets",
    "Compose an email declining a meeting politely",
    "Compare Postgres MVCC to MySQL InnoDB locking",
    "What's the time complexity of merge sort?",
    "Write a regex for ISO 8601 timestamps",
    "Recommend a recipe with chicken and rice",
    "Convert 75 Fahrenheit to Celsius",
    "How do I create a new git branch?",
    "Explain how OAuth 2.0 PKCE works",
    "Outline the plot of Hamlet",
    "Suggest a name for a baby boy",
    "Weather forecast for Berlin tomorrow",
    "Help me plan a trip to Tokyo",
    "Write a haiku about cats sleeping in sunbeams",
    "Implement quicksort in Rust",
    "Explain Bayesian inference in two sentences",
    "What's the capital of Australia?",
    "Refactor this CSS to use flexbox",
]


def _snap(*, configured: bool = True) -> StatusSnapshot:
    return StatusSnapshot(
        configured=configured,
        signer_mode="eoa" if configured else None,
        miner="0x" + "a" * 40 if configured else None,
        epoch_id="42" if configured else None,
        epoch_ends_at=1778122278 if configured else None,
        epoch_reward_estimate="50000.0" if configured else None,
        active_miners=5 if configured else None,
        total_staked="123000000.0" if configured else None,
        coordinator_url="https://coordinator.agentmoney.net",
    )


def _fires(prompt: str, *, configured: bool = True, is_first_turn: bool = False) -> bool:
    with patch.object(hooks, "get_status", return_value=_snap(configured=configured)):
        out = hooks.pre_llm_call(user_message=prompt, is_first_turn=is_first_turn)
    return out is not None


def test_relevant_prompts_recall_at_least_90pct():
    fired = sum(1 for p in _RELEVANT if _fires(p, configured=True, is_first_turn=False))
    recall = fired / len(_RELEVANT)
    assert recall >= 0.90, f"recall={recall:.2f} on relevant prompts (fired {fired}/{len(_RELEVANT)})"


def test_relevant_prompts_recall_when_unconfigured():
    fired = sum(1 for p in _RELEVANT if _fires(p, configured=False, is_first_turn=False))
    recall = fired / len(_RELEVANT)
    assert recall >= 0.85, f"recall={recall:.2f} on relevant prompts when unconfigured"


def test_unrelated_prompts_zero_false_positives_mid_session():
    fired = [p for p in _UNRELATED if _fires(p, configured=True, is_first_turn=False)]
    assert not fired, f"hook fired on unrelated prompts: {fired}"


def test_unconfigured_unrelated_zero_false_positives_anywhere():
    for first_turn in (True, False):
        fired = [p for p in _UNRELATED
                 if _fires(p, configured=False, is_first_turn=first_turn)]
        assert not fired, (
            f"unconfigured-mode false positives on first_turn={first_turn}: {fired}"
        )


def test_first_turn_when_configured_always_fires():
    for prompt in (None, "", "hi", "what's up"):
        assert _fires(prompt, configured=True, is_first_turn=True), prompt


def test_hook_returns_context_dict():
    with patch.object(hooks, "get_status", return_value=_snap(configured=True)):
        out = hooks.pre_llm_call(user_message="how do I mine botcoin", is_first_turn=False)
    assert isinstance(out, dict)
    assert "context" in out
    assert isinstance(out["context"], str)
    assert "BOTCOIN" in out["context"]


def test_hook_no_throw_when_status_blows_up():
    def boom(*_a, **_k):
        raise RuntimeError("coordinator down")
    with patch.object(hooks, "get_status", side_effect=boom):
        out = hooks.pre_llm_call(user_message="mine some botcoin", is_first_turn=False)
    assert out is None
