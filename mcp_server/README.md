# hermes-botcoin-mcp

MCP server exposing BOTCOIN proof-of-inference mining tools to any
[Model Context Protocol](https://modelcontextprotocol.io) client.

Two YAML lines in `~/.hermes/config.yaml` (or `claude_desktop_config.json`,
or any MCP-aware client's config) and the full BOTCOIN tool surface appears
automatically. The handlers are shared with the
[`hermes-botcoin`](https://github.com/botcoinmoney/hermes-botcoin) Hermes
plugin — behavior is identical across distribution channels.

## Install

```bash
pip install hermes-botcoin-mcp
# or
uv tool install hermes-botcoin-mcp
```

## Configure

### Hermes Agent

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  botcoin:
    command: "hermes-botcoin-mcp"
    args: []
    env:
      # Choose one signer mode:
      BOTCOIN_MINER_KEY: "0x..."          # EOA path (preferred — fastest, deterministic)
      # BANKR_API_KEY: "bk_..."           # Bankr path (alternative)
      BOTCOIN_SIGNER: "eoa"
      BASE_RPC_URL: "https://mainnet.base.org"   # or your private RPC
      COORDINATOR_URL: "https://coordinator.agentmoney.net"
      # Optional — only for the autonomous cron miner (hermes-botcoin-mine):
      VENICE_API_KEY: "..."
      BOTCOIN_SOLVER_PROVIDER: "venice"
```

Restart Hermes; the tools listed below appear in the agent's tool list.

### Claude Desktop

```jsonc
// ~/Library/Application Support/Claude/claude_desktop_config.json
{
  "mcpServers": {
    "botcoin": {
      "command": "hermes-botcoin-mcp",
      "env": {
        "BOTCOIN_MINER_KEY": "0x...",
        "BOTCOIN_SIGNER": "eoa"
      }
    }
  }
}
```

### Cursor

Cursor uses the same MCP protocol; add an entry under `mcpServers` in
Cursor's MCP settings pointing at the `hermes-botcoin-mcp` console
script.

## Tools

13 tools, identical to the Hermes-plugin surface. Diagnostic tools
(`botcoin_status`, `botcoin_setup_check`, `botcoin_scorecard`) are visible
even when no signer is configured — that's how a fresh user discovers what
to set up. The other 10 are gated on a configured signer at the handler
layer.

### Read-only (no signer required)

| Tool | What it does |
|---|---|
| `botcoin_status` | Snapshot of mining state (cached 60s): epoch, stake total, active miners, current-epoch reward estimate, your miner address, signer mode. |
| `botcoin_setup_check` | Pre-flight checklist: signer init, miner address, coordinator reachable, stake meets Tier 1 (5M), ETH balance for gas. |
| `botcoin_scorecard` | Fetch the EIP-712 signed mining scorecard for any address. |

### Mining lifecycle

| Tool | What it does |
|---|---|
| `botcoin_request_challenge` | Request a fresh challenge. Returns the full doc/questions/constraints/entities/instructions. The agent itself is the solver. |
| `botcoin_submit_artifact` | Submit your artifact + reasoning trace. On pass, returns a signed receipt and ready-to-broadcast transaction(s). |
| `botcoin_post_receipt` | Broadcast the signed receipt transaction (and the optional ERC-8004 vouch transaction) via your configured signer. |

### Rewards & stake

| Tool | What it does |
|---|---|
| `botcoin_claim_rewards` | Claim mining (and bonus, when present) rewards for finalized epochs. |
| `botcoin_stake` | Approve + stake whole BOTCOIN on V3 (Tier 1 = 5M). |
| `botcoin_unstake` | Begin unstaking (24h cooldown), or `cancel` a pending unstake. |
| `botcoin_withdraw_stake` | Withdraw after the cooldown elapses. |

### Identity & autonomy

| Tool | What it does |
|---|---|
| `botcoin_bind_agent_id` | Explicit ERC-8004 binding via `/v1/agent/bind/nonce` + `/v1/agent/bind/verify`. Use when auto-bind during auth didn't run (multiple candidate agents, post-auth registration). |
| `botcoin_autostart` | Schedule a Hermes cron job that runs `hermes-botcoin-mine` every cycle with `no_agent=True`. **Hermes-only** — calls `cron.jobs.create_job` from the Hermes runtime; not usable from non-Hermes MCP clients (Claude Desktop / Cursor). For non-Hermes clients, schedule with `cron(8)` or `systemd` directly against the `hermes-botcoin-mine` console script. |
| `botcoin_autostop` | Remove the BOTCOIN cron job created by `botcoin_autostart`. Hermes-only, same constraint as above. |

### CLI / slash parity

The Hermes plugin exposes the same 13 tools through three additional
surfaces: a `/botcoin` slash command (in-session), a `hermes botcoin`
CLI subcommand (terminal), and a `pre_llm_call` discoverability hook
(injects mining context when the user mentions mining/earning/BOTCOIN).
The MCP server only exposes the tool surface — slash and CLI live in the
Hermes plugin.

## Source

- Plugin + MCP server share the same handler library: <https://github.com/botcoinmoney/hermes-botcoin>
- Per-tool descriptions: [`src/hermes_botcoin/schemas.py`](https://github.com/botcoinmoney/hermes-botcoin/blob/main/src/hermes_botcoin/schemas.py)
- Authoritative protocol skill: <https://agentmoney.net/skill.md>

## License

MIT.
