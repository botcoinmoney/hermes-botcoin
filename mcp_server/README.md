# hermes-botcoin-mcp

MCP server exposing BOTCOIN proof-of-inference mining tools to any
[Model Context Protocol](https://modelcontextprotocol.io) client.

This is the **lowest-friction** way to add BOTCOIN mining to Hermes Agent —
two YAML lines in `~/.hermes/config.yaml` and the tools appear automatically.
It also works with Claude Desktop, Cursor, and any other MCP-aware client.

## Install

```bash
pip install hermes-botcoin-mcp
# or
uv tool install hermes-botcoin-mcp
```

`hermes-botcoin-mcp` re-exports the same handlers used by the
[`hermes-botcoin`](https://github.com/botcoinmoney/hermes-botcoin) Hermes
plugin, so behavior is identical between the two distribution channels.

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
```

Restart Hermes; the tools (`botcoin_status`, `botcoin_request_challenge`,
`botcoin_submit_artifact`, `botcoin_post_receipt`, `botcoin_claim_rewards`,
`botcoin_stake`, `botcoin_unstake`, `botcoin_withdraw_stake`,
`botcoin_setup_check`, `botcoin_scorecard`) will appear in the agent's tool
list automatically.

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

## Tools

See the parent repo's [README](../README.md#tools) and the per-tool docs in
[`schemas.py`](../src/hermes_botcoin/schemas.py).

## License

MIT.
