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

## 2. Stake (one-time)

If `setup` flagged "stake_meets_tier_1: false", stake 5,000,000 BOTCOIN — the
Tier 1 minimum:

```
/botcoin stake 5000000
```

Tiers 2-5 are 10M / 25M / 50M / 100M with 205 / 520 / 1075 / 2200 credits per
solve respectively (vs 100 for Tier 1).

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
