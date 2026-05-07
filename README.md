# hermes-botcoin

Native [BOTCOIN](https://agentmoney.net) mining for [Hermes Agent](https://github.com/NousResearch/hermes-agent).

> ⚠️ **Naming clarification**: this is **BOTCOIN by AgentMoney** — proof-of-inference mining on Base (token `0xA601877977340862Ca67f816eb079958E5bd0BA3`). Not affiliated with the unrelated `Botcoin` RandomX coin (`BOTCoinNetwork`).

## What this gives you

- **10 first-class tools** the Hermes agent can call: `botcoin_status`, `botcoin_setup_check`, `botcoin_scorecard`, `botcoin_request_challenge`, `botcoin_submit_artifact`, `botcoin_post_receipt`, `botcoin_claim_rewards`, `botcoin_stake`, `botcoin_unstake`, `botcoin_withdraw_stake`.
- **`/botcoin` slash command** for in-session UX: `/botcoin status`, `/botcoin setup`, `/botcoin claim 41,42`, `/botcoin stake 5000000`, `/botcoin unstake`, `/botcoin withdraw`, `/botcoin scorecard`.
- **`hermes botcoin <subcmd>` CLI** for terminal use and scripting.
- **`hermes-botcoin-mine` console script** — drop-in for `hermes cron` jobs (`no_agent=True`) for fully autonomous mining without LLM-loop overhead, with a multi-provider solver (`venice` (default) `| anthropic | openai | openrouter | deepseek`).
- **`pre_llm_call` discoverability hook** — when the user mentions mining/earning/BOTCOIN, the agent gets a fresh status block injected into context (cached 60s).
- **Bundled `botcoin:mining-strategy` skill** for the deep playbook, loadable on demand.
- **Two signer paths**: EOA (preferred — `eth-account` + Base RPC) or Bankr Agent API. Auto-detected, override with `BOTCOIN_SIGNER`.

## Two ways to install

### A — Native plugin (recommended)

```bash
hermes plugins install botcoinmoney/hermes-botcoin --enable
```

Hermes will:
1. `git clone --depth 1` this repo into `~/.hermes/plugins/botcoin/`.
2. Walk `requires_env` from `plugin.yaml` and prompt you for the secrets you don't already have (`BANKR_API_KEY` xor `BOTCOIN_MINER_KEY`, plus optional `BOTCOIN_MINER_ADDRESS`, `COORDINATOR_URL`, `BASE_RPC_URL`). Secrets land in `~/.hermes/.env` — they never reach an LLM.
3. Add `botcoin` to `plugins.enabled` in `~/.hermes/config.yaml`.
4. Show you `after-install.md` with verification steps.

Restart Hermes. Run `/botcoin setup` to confirm everything is wired up.

### B — MCP server

If you'd rather run BOTCOIN as an MCP server (also works with Claude Desktop, Cursor, and any other MCP client):

```bash
pip install hermes-botcoin-mcp        # see mcp_server/
```

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  botcoin:
    command: hermes-botcoin-mcp
    env:
      BOTCOIN_MINER_KEY: "0x..."
      BOTCOIN_SIGNER: eoa
```

## Configuration

All secrets and overrides live in `~/.hermes/.env`. The `requires_env` block in `plugin.yaml` is the source of truth.

| Variable | Required | Purpose |
|---|---|---|
| `BOTCOIN_SIGNER` | no | `eoa` or `bankr`. Auto-detected when omitted. |
| `BOTCOIN_MINER_KEY` | (eoa) | 0x-prefixed EVM private key for the miner wallet. |
| `BANKR_API_KEY` | (bankr) | Bankr Agent API key with write access. |
| `BOTCOIN_MINER_ADDRESS` | no | Override the miner address (else derived). |
| `BOTCOIN_AGENT_ID` | no | ERC-8004 agent identifier to bind to your miner during auth. |
| `COORDINATOR_URL` | no | Defaults to `https://coordinator.agentmoney.net`. |
| `BASE_RPC_URL` | no | Defaults to `https://mainnet.base.org`. Set a private RPC for better rate limits. |
| `BOTCOIN_SOLVER_PROVIDER` | no (cron) | LLM provider for autonomous mining: **`venice`** (recommended), `anthropic`, `openai`, `openrouter`, `deepseek`. |
| `BOTCOIN_SOLVER_MODEL` | no (cron) | Model id. Defaults: venice → `zai-org-glm-5.1`; anthropic → `claude-opus-4-7`; openai → `gpt-5.1`; openrouter → `anthropic/claude-opus-4.7`; deepseek → `deepseek-reasoner`. |
| `VENICE_API_KEY` | (cron, recommended) | [venice.ai/settings/api](https://venice.ai/settings/api). Privacy-by-default (no data retention), OpenAI-compatible. |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `OPENROUTER_API_KEY` / `DEEPSEEK_API_KEY` | (cron) | Whichever matches your `BOTCOIN_SOLVER_PROVIDER`. |

### Why Venice for autonomous mining

[Venice.ai](https://docs.venice.ai/overview/about-venice) is the recommended inference provider for the cron miner because it aligns with BOTCOIN's protocol values:

- **No data retention** — your reasoning traces aren't kept by the inference provider, matching the protocol's "verifiable inference" stance.
- **OpenAI-compatible API** at `https://api.venice.ai/api/v1` — `Authorization: Bearer $VENICE_API_KEY`, JSON mode, function calling.
- **Strong reasoning models for long-context challenges** — `zai-org-glm-5.1` (200k ctx, "deep reasoning and production agents", recommended default), `deepseek-ai-DeepSeek-R1`, `qwen3-4b` (visible thinking), and Venice's own reasoning lineup.
- **`venice_parameters`** for fine control: we pass `include_venice_system_prompt: false` so Venice's default persona doesn't shadow our solver prompt, and `enable_web_search: "off"` because the challenge document is the only valid source.
- **Pricing options** that scale: pay-as-you-go USD, Pro subscription with $10 free credits on upgrade, or DIEM token staking for permanent compute access — pick whichever fits your mining cadence.

The plugin uses the canonical Venice OpenAI-compatible chat completions endpoint:

```
POST https://api.venice.ai/api/v1/chat/completions
Authorization: Bearer $VENICE_API_KEY
Content-Type: application/json

{
  "model": "zai-org-glm-5.1",
  "messages": [{"role": "system", ...}, {"role": "user", ...}],
  "max_tokens": 16000,
  "response_format": {"type": "json_object"},
  "venice_parameters": {
    "include_venice_system_prompt": false,
    "enable_web_search": "off"
  }
}
```

In **interactive** Hermes mining the agent itself solves with whatever provider Hermes is already configured for — no extra LLM key is needed.

## Tools

### Read-only

| Tool | What it does |
|---|---|
| `botcoin_status` | Snapshot of mining state (cached 60s): epoch, stake total, active miners, current-epoch reward estimate, your miner address, signer mode. |
| `botcoin_setup_check` | Pre-flight checklist: signer init, miner address, coordinator reachable, stake meets Tier 1 (5M), ETH balance for gas. |
| `botcoin_scorecard` | Fetch the EIP-712 signed mining scorecard for any address. |

### Mining

| Tool | What it does |
|---|---|
| `botcoin_request_challenge` | Request a fresh challenge. Returns the full doc/questions/constraints/entities/instructions. **The agent is the solver.** |
| `botcoin_submit_artifact` | Submit your artifact + reasoning trace. On pass, returns a signed receipt and ready-to-broadcast transaction. |
| `botcoin_post_receipt` | Broadcast the signed receipt transaction via your configured signer. |

### Rewards & stake

| Tool | What it does |
|---|---|
| `botcoin_claim_rewards` | Claim mining (and bonus, when present) rewards for finalized epochs. |
| `botcoin_stake` | Approve + stake whole BOTCOIN on V3 (Tier 1 = 5M). |
| `botcoin_unstake` | Begin unstaking (24h cooldown), or `cancel` a pending unstake. |
| `botcoin_withdraw_stake` | Withdraw after the cooldown elapses. |

## Autonomous mining via `hermes cron`

Once configured, schedule it from Hermes:

```bash
hermes cron add \
  --name "BOTCOIN miner" \
  --schedule "every 90s" \
  --no-agent \
  --script "hermes-botcoin-mine --solver venice --max-attempts 1 --quiet"
```

`no_agent=True` skips the LLM loop on every cron tick — only the explicit
solver call inside `hermes-botcoin-mine` pays for inference. Output is
delivered via Hermes' built-in cron `deliver:` config (Telegram, Discord,
local file, etc.).

## Architecture

```
                ┌─────────────────────────────┐
                │     Hermes Agent CLI/TUI    │
                └────────┬────────────────────┘
        register(ctx)    │
                ┌────────▼─────────┐
                │   plugin_entry   │  tools / slash / CLI / hooks / skill
                └────────┬─────────┘
                         │
                ┌────────▼─────────┐
                │      tools.py    │ ← agent calls these
                └────┬───────┬─────┘
                     │       │
                ┌────▼──┐ ┌──▼─────┐
                │ auth  │ │ signer │  EOA (eth-account + Base RPC) | Bankr
                └────┬──┘ └──┬─────┘
                     │       │
                ┌────▼───────▼─────┐
                │   coordinator    │  HTTP client over coordinator.agentmoney.net
                └──────────────────┘

(MCP path: same handlers, exposed via FastMCP in mcp_server/.)
```

The Hermes agent is the solver in interactive mode. The `solver.py` /
`mining.py` / `cron_entry()` triplet is **only** used in autonomous /
headless / cron contexts.

## Discoverability

Beyond the install paths, the project ships three additional surfaces:

1. **Coordinator-side well-known skill** at `https://coordinator.agentmoney.net/.well-known/skills/index.json#botcoin-mining` — installable with `hermes skills install <url>` and includes a self-contained Python helper that needs no plugin install.
2. **`pre_llm_call` hook** — when the user mentions mining-related keywords, the model gets fresh BOTCOIN context.
3. **Pip entry-point** (`hermes_agent.plugins`) so `pip install hermes-botcoin` is also a valid install path.

## Development

```bash
git clone https://github.com/botcoinmoney/hermes-botcoin
cd hermes-botcoin
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```

The repository hosts:

| Path | Purpose |
|---|---|
| `plugin.yaml`, `__init__.py` | Hermes-plugin entry (used by `hermes plugins install`). |
| `src/hermes_botcoin/` | Canonical library — used by both the plugin and MCP server. |
| `mcp_server/` | Separate PyPI package (`hermes-botcoin-mcp`). |
| `skills/mining-strategy/` | Bundled deep-skill SKILL.md. |
| `coordinator-deliverables/` | Drop-in files for the BOTCOIN coordinator (well-known skills index + SKILL.md + helper script). |
| `BUILD_PLAN.md` | Day-by-day build & ship plan. |
| `VERIFIED_ASSUMPTIONS.md` | Source-of-truth verifications against the Hermes repo. |
| `tests/` | Unit tests for trace normalization, signer dispatch, schemas. |

## License

MIT — see `LICENSE`.

## Acknowledgements

Built on the [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin SDK by Nous Research, also MIT.
