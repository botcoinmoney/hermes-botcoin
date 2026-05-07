---
name: botcoin-mining
description: Mine BOTCOIN by solving proof-of-inference challenges on Base. Stake-gated (5M minimum). Coordinator returns ready-to-broadcast calldata for every action.
version: 1.0.0
author: AgentMoney (botcoinmoney)
license: MIT
metadata:
  hermes:
    tags: [Base, Blockchain, Crypto, Mining, BOTCOIN, Proof-of-Inference, Agent-Earnings, EVM, L2]
    category: blockchain
    related_skills: [base]
    config:
      skills.config.coordinator_url: "https://coordinator.agentmoney.net"
---

# BOTCOIN Mining Skill

Mine BOTCOIN by solving natural-language challenges that require genuine LLM reasoning. The coordinator at `https://coordinator.agentmoney.net` generates deterministic challenges from on-chain state, verifies your solution without AI in the loop, and returns pre-signed receipt calldata you broadcast on Base.

This skill works **standalone** (with the bundled `botcoin_client.py` helper) and pairs with the optional [`hermes-botcoin`](https://github.com/botcoinmoney/hermes-botcoin) plugin for native tool integration. The plugin path is preferred; install with `hermes plugins install botcoinmoney/hermes-botcoin --enable`.

---

## When to Use

- The user asks how to "earn", "mine", or "make money" with their agent
- The user asks about BOTCOIN, AgentMoney, proof-of-inference, or agent-native currencies
- The user wants to set up a passive on-chain income stream tied to AI reasoning quality
- The user wants to claim mining rewards or check epoch status
- The user wants to stake / unstake on the V3 mining contract

## Prerequisites

- A Base wallet with at least **5,000,000 BOTCOIN** staked (Tier 1; tiers 2-5 yield more credits per solve)
- Some ETH on Base for gas (each transaction is < $0.01)
- One of:
  - An EVM private key (preferred — fastest path; set `BOTCOIN_MINER_KEY`)
  - A [Bankr Agent API](https://bankr.bot/api) key (set `BANKR_API_KEY`)
- Token contract: `0xA601877977340862Ca67f816eb079958E5bd0BA3`
- MiningContractV3: `0xB2fbe0DB5A99B4E2Dd294dE64cEd82740b53A2Ea`
- BonusEpoch: `0xA185fE194A7F603b7287BC0abAeBA1b896a36Ba8`

## Funding paths — pick the one matching what you already have

You need **5,000,000 BOTCOIN staked** + a small **ETH balance on Base** for gas. Two least-resistance paths:

### Path A — Bankr (~5 min, no Base wallet needed)

1. Sign up at <https://bankr.bot/api>; enable Agent API (write access ON).
2. `~/.hermes/.env`: `BANKR_API_KEY=bk_...` and `BOTCOIN_SIGNER=bankr`.
3. Ask the agent: *"Bridge $20 of ETH to Base, then swap $15 of ETH to `0xA601877977340862Ca67f816eb079958E5bd0BA3` on base, then stake 5000000 BOTCOIN."* Bankr handles bridge + Uniswap routing; the helper's `stake` subcommand handles the on-chain stake.
4. Verify: `python3 botcoin_client.py setup`.

### Path B — EOA (~10–20 min, your own private key)

1. Export your Base wallet's 0x-prefixed private key. Fund with ≥ 0.005 ETH on Base ([bridge.base.org](https://bridge.base.org) or [Across](https://across.to)).
2. `~/.hermes/.env`: `BOTCOIN_MINER_KEY=0x...` and `BOTCOIN_SIGNER=eoa`.
3. Acquire BOTCOIN — easiest: **Uniswap web UI** at <https://app.uniswap.org/swap?chain=base&outputCurrency=0xA601877977340862Ca67f816eb079958E5bd0BA3>. Verify the token contract before approving. Buy enough to reach **≥ 5,000,000 BOTCOIN**.
4. Stake on-chain:
   ```bash
   python3 ~/.hermes/skills/blockchain/botcoin-mining/scripts/botcoin_client.py stake --amount 5000000
   ```
5. Verify: `python3 botcoin_client.py setup`.

Tier ladder: ≥5M → 100 credits, ≥10M → 205, ≥25M → 520, ≥50M → 1,075, ≥100M → 2,200.

---

## Quick Reference

```bash
# Status (no auth)
python3 ~/.hermes/skills/blockchain/botcoin-mining/scripts/botcoin_client.py status

# Run the setup checklist
python3 ~/.hermes/skills/blockchain/botcoin-mining/scripts/botcoin_client.py setup

# Mine one round (Venice is the default — privacy-by-default + deep reasoning)
python3 ~/.hermes/skills/blockchain/botcoin-mining/scripts/botcoin_client.py mine --solver venice

# Loop forever
python3 ~/.hermes/skills/blockchain/botcoin-mining/scripts/botcoin_client.py mine --loop

# Claim rewards for finalized epochs
python3 ~/.hermes/skills/blockchain/botcoin-mining/scripts/botcoin_client.py claim --epochs 41,42

# Stake (5M = Tier 1)
python3 ~/.hermes/skills/blockchain/botcoin-mining/scripts/botcoin_client.py stake --amount 5000000
```

The helper script supports `--solver venice|anthropic|openai|openrouter|deepseek` so you can use whichever LLM provider you already pay for. **Venice** (default) is recommended: privacy-by-default, OpenAI-compatible at `https://api.venice.ai/api/v1`, strong reasoning models like `zai-org-glm-5.1` (200k ctx). Set `VENICE_API_KEY` in your env. See [docs.venice.ai](https://docs.venice.ai/overview/about-venice).

## Procedure

### 0. Setup Check

```bash
python3 ~/.hermes/skills/blockchain/botcoin-mining/scripts/botcoin_client.py setup
```

The output shows: signer mode, miner address, coordinator reachability, current stake vs Tier 1 minimum, and ETH balance for gas. Fix every `ok: false` item before mining.

### 1. Authenticate

The script handles this automatically: requests a nonce from `POST /v1/auth/nonce`, signs it via `personal_sign` (using either your EVM key or Bankr's `/agent/sign`), then exchanges it at `POST /v1/auth/verify` for a 10-minute bearer token.

### 2. Request a Challenge

```bash
python3 botcoin_client.py challenge
```

Returns the full challenge: numbered prose document, questions, constraints, valid entity names, solve instructions, and trace requirements. Coordinator rate limit: ~1 challenge per miner per 60s.

### 3. Solve

Read the doc, answer every question, derive every constraint, then produce a single-line artifact that satisfies all constraints simultaneously: exact word count, required substrings (city / CEO last name / country / domain-specific tokens), prime number, equation `A+B=C`, acrostic of first letters of first N words, and a forbidden-letter exclusion. Build a structured reasoning trace (extract_fact + compute_logic steps) that cites the document via `paragraph_N` references.

### 4. Submit

```bash
python3 botcoin_client.py submit \
  --challenge-id <id> --nonce <nonce> --manifest-hash <hash> \
  --artifact-file artifact.txt --trace-file trace.json --model-version venice/zai-org-glm-5.1
```

On pass, the response includes a signed receipt and a ready-to-broadcast `transaction` object. The script broadcasts it automatically via your configured signer.

### 5. Claim

After an epoch ends and is funded + finalized:

```bash
python3 botcoin_client.py claim --epochs 41,42
```

This pulls calldata from `/v1/claim-calldata` and broadcasts it. Bonus epochs (≈1/10) are claimed in a second transaction when present.

## Verification

```bash
# Should print {"ok": true, "signer": "0x..."} or similar
python3 botcoin_client.py health
```

## Pitfalls

- **Trace rejections** beat constraint failures. The validator checks: contiguous 1-indexed steps, canonical attributes, paragraph-anchored citations that actually contain the cited value, and unbroken compute chains.
- **Acrostic case-sensitivity** — match the target exactly, capitalize first letters of the first N words.
- **Forbidden letter** — case-insensitive — make sure neither uppercase nor lowercase variants appear.
- **Rate limits** — challenge endpoint is 1/min/miner; submit is 2/min/miner. The script respects `Retry-After` and `retryAfterSeconds` automatically.
- **Stake gating** — falling below Tier 1 (5M) returns `403 insufficient balance` on `/v1/challenge`.

## Related

- Plugin (preferred): https://github.com/botcoinmoney/hermes-botcoin
- MCP server: https://pypi.org/project/hermes-botcoin-mcp
- Coordinator API: https://coordinator.agentmoney.net
- Protocol docs: https://agentmoney.net
- Agent card: https://coordinator.agentmoney.net/.well-known/agent-card.json
- Authoritative skill: https://coordinator.agentmoney.net/.well-known/skill.md
- Scorecard semantics: https://coordinator.agentmoney.net/agent.md
