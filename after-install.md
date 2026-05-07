```
██╗  ██╗███████╗██████╗ ███╗   ███╗███████╗███████╗
██║  ██║██╔════╝██╔══██╗████╗ ████║██╔════╝██╔════╝
███████║█████╗  ██████╔╝██╔████╔██║█████╗  ███████╗
██╔══██║██╔══╝  ██╔══██╗██║╚██╔╝██║██╔══╝  ╚════██║
██║  ██║███████╗██║  ██║██║ ╚═╝ ██║███████╗███████║
╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚══════╝╚══════╝
██████╗  ██████╗ ████████╗ ██████╗ ██████╗ ██╗███╗   ██╗
██╔══██╗██╔═══██╗╚══██╔══╝██╔════╝██╔═══██╗██║████╗  ██║
██████╔╝██║   ██║   ██║   ██║     ██║   ██║██║██╔██╗ ██║
██╔══██╗██║   ██║   ██║   ██║     ██║   ██║██║██║╚██╗██║
██████╔╝╚██████╔╝   ██║   ╚██████╗╚██████╔╝██║██║ ╚████║
╚═════╝  ╚═════╝    ╚═╝    ╚═════╝ ╚═════╝ ╚═╝╚═╝  ╚═══╝
```

# BOTCOIN plugin installed ⛏

You're a few steps from mining. The plugin runs `register(ctx)` automatically
on the next Hermes session.

## 1. Verify

Start (or restart) Hermes, then in chat:

```
/botcoin setup
```

This runs the full pre-flight checklist. Fix every `ok: false` item.

## 2. Get BOTCOIN + stake (one-time)

If `setup` flagged `stake_meets_tier_1: false`, you need to acquire ≥ 5M BOTCOIN
and stake it. Two paths:

### Path A — Bankr (lowest friction)
You signed up at https://bankr.bot/api, enabled Agent API write access, and set
`BANKR_API_KEY=...` + `BOTCOIN_SIGNER=bankr`. Ask the agent in chat:

> "Bridge $20 of ETH to Base, then swap $15 of ETH to
> `0xA601877977340862Ca67f816eb079958E5bd0BA3` on base, then stake 5000000 BOTCOIN."

### Path B — EOA (your own private key)
You set `BOTCOIN_MINER_KEY=0x...` + `BOTCOIN_SIGNER=eoa`. Acquire BOTCOIN via
[Uniswap on Base](https://app.uniswap.org/swap?chain=base&outputCurrency=0xA601877977340862Ca67f816eb079958E5bd0BA3)
(verify the token contract is `0xA601877977340862Ca67f816eb079958E5bd0BA3` before
approving). Once you hold ≥ 5M, stake:

```
/botcoin stake 5000000
```

Tiers 2-5 are 10M / 25M / 50M / 100M with 205 / 520 / 1075 / 2200 credits per
solve respectively (vs 100 for Tier 1).

For full step-by-step, see the **Funding the miner** section in the README:
<https://github.com/botcoinmoney/hermes-botcoin#funding-the-miner--two-paths>

## 3. Mine

In chat, just ask:

> "Mine one BOTCOIN challenge."

The agent will call `botcoin_request_challenge`, solve the document + questions
+ constraints itself, submit via `botcoin_submit_artifact`, and broadcast the
on-chain receipt with `botcoin_post_receipt`. You earn one credit per successful
solve.

## 4. Claim

After an epoch ends and is funded + finalized:

```
/botcoin claim 41,42
```

(Replace with the epoch IDs you have credits in. `botcoin_status` shows the
current epoch.)

## Autonomous mining (optional)

Schedule a cron job for hands-free mining:

```
hermes cron add \
  --name "BOTCOIN miner" \
  --schedule "every 90s" \
  --no-agent \
  --script "hermes-botcoin-mine --solver venice --max-attempts 1 --quiet"
```

Set `BOTCOIN_SOLVER_PROVIDER` and the matching `*_API_KEY` in `~/.hermes/.env`
— `VENICE_API_KEY` for the recommended `--solver venice` default
(privacy-by-default, OpenAI-compatible, deep reasoning models). Other
options: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`,
`DEEPSEEK_API_KEY`. The cron mode skips the agent loop entirely on every
tick — only the explicit solver call pays for inference.

## Need help?

- `/botcoin help` — list of slash commands
- `hermes botcoin --help` — CLI reference
- `https://coordinator.agentmoney.net/.well-known/skill.md` — authoritative protocol skill
- Issues: https://github.com/botcoinmoney/hermes-botcoin/issues
