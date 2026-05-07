# BUILD_PLAN.md — End-to-End BOTCOIN × Hermes Architecture

A targeted, day-by-day plan that takes the project from "no Hermes presence" to "shipping on three independent distribution channels with autonomous mining". The plan is deliberately narrow: every day produces a shippable artifact and at least one publicly verifiable outcome.

The plan tracks **three release tracks in parallel**, all of which are shipped from this single repo:

* **T1** — **Coordinator-side well-known skill** (`/.well-known/skills/index.json` + `botcoin-mining/SKILL.md`). No Hermes-side change required.
* **T2** — **`hermes-botcoin` plugin** (this repo's root). Installed via `hermes plugins install botcoinmoney/hermes-botcoin --enable`.
* **T3** — **`hermes-botcoin-mcp` MCP server** (`mcp_server/`). Installed via `pip install hermes-botcoin-mcp` + two YAML lines.

After day 8 we open upstream PRs to `NousResearch/hermes-agent` (the optional-skills addition and, separately, the bundled-plugin proposal). Those gates are intentionally outside the 8-day window — they depend on review cadence we don't control.

---

## Day 0 — Repo bootstrap (this turn)

✅ Already complete in this repo:

* `LICENSE` (MIT, matching Hermes upstream).
* `pyproject.toml` with the `hermes_agent.plugins` entry point so `pip install hermes-botcoin` is also a valid path.
* `plugin.yaml` declaring `requires_env` so `hermes plugins install` interactively prompts for secrets and writes them to `~/.hermes/.env`.
* `src/hermes_botcoin/{coordinator, signer, auth, status, trace, schemas, tools, slash, cli, hooks, mining, solver, plugin_entry}.py` — full library, no stubs.
* `__init__.py` at repo root delegating to `plugin_entry.register`.
* `mcp_server/` package with FastMCP server, README, and standalone `pyproject.toml` for PyPI.
* `skills/mining-strategy/SKILL.md` bundled with the plugin.
* `coordinator-deliverables/` — drop-in `index.json`, `SKILL.md`, and standalone `botcoin_client.py` for the coordinator team.
* `tests/` covering trace normalization, signer mode dispatch, schema invariants, coordinator helpers.
* `README.md`, `after-install.md`, `BUILD_PLAN.md`, `VERIFIED_ASSUMPTIONS.md`.

End-of-day exit gate: `python -m py_compile $(find src tests mcp_server coordinator-deliverables -name '*.py')` succeeds and `pytest -q` passes.

---

## Day 1 — Live e2e mining test against the nookplot wallet (5M staked)

**Goal**: prove the full library works against the real coordinator with the nookplot agent's pre-staked wallet, before any user-facing surface.

1. Verify nookplot has its EVM key (or Bankr key) usable as `BOTCOIN_MINER_KEY` / `BANKR_API_KEY`.
2. Smoke test, in order:
   * `hermes-botcoin-mine --solver anthropic --max-attempts 1 --quiet` (autonomous path).
   * `python coordinator-deliverables/skills/botcoin-mining/scripts/botcoin_client.py mine --solver anthropic --max-attempts 1` (skill helper path).
   * Manual `python -c "from hermes_botcoin.tools import handle_setup_check; print(handle_setup_check())"` (tool path).
3. Capture the on-chain receipt hashes — they are the proof we shipped.
4. Diff the trace the solver produced vs the canonical `traceReference` from the challenge to confirm citation accuracy. Tighten `solver.py` prompt if any constraint slot rate is below 80% across 5 runs.
5. **Reconcile MINER_README.md** — confirm with the coordinator team that Tier 1 is 5M (not 25M as the legacy README says), then update `scripts/MINER_README.md` in the protocol repo so the documentation has one source of truth. The MINER must be rebuilt against `BOTCOIN_DOCS.md` + the live `/.well-known/skill.md`, **not** `scripts/miner.py`.

End-of-day exit gate: at least 3 successful end-to-end mines on the nookplot wallet, each producing a receipt tx hash on Base.

---

## Day 2 — Coordinator-side well-known skill (T1 ships)

**Goal**: any Hermes user, anywhere, can install BOTCOIN mining today with one CLI command — no plugin, no PyPI.

1. Coordinator team takes the three files from `coordinator-deliverables/`:
   * `well-known-skills-index.json` → host at `/.well-known/skills/index.json`.
   * `skills/botcoin-mining/SKILL.md` → host at `/.well-known/skills/botcoin-mining/SKILL.md`.
   * `skills/botcoin-mining/scripts/botcoin_client.py` → host at `/.well-known/skills/botcoin-mining/scripts/botcoin_client.py`.
2. Confirm `Content-Type` is `application/json` and `text/markdown; charset=utf-8` respectively. CORS already permissive on `/.well-known/*`.
3. Smoke test with a fresh Hermes install on a clean machine:

   ```bash
   hermes skills search https://coordinator.agentmoney.net/.well-known/skills/index.json
   hermes skills install https://coordinator.agentmoney.net/.well-known/skills/index.json#botcoin-mining
   ls ~/.hermes/skills/blockchain/botcoin-mining/SKILL.md
   python ~/.hermes/skills/blockchain/botcoin-mining/scripts/botcoin_client.py status
   ```
4. Update `BOTCOIN_DOCS.md` (in the protocol repo) and the AgentMoney homepage to mention the one-line install URL.
5. Tweet from @botcoinmoney: "BOTCOIN mining is now a one-line install in Hermes Agent: `hermes skills install …#botcoin-mining`. Source-of-truth skill, helper script included, zero plugin install needed."

End-of-day exit gate: a brand-new Hermes user, on a freshly provisioned VM, can mine their first attempt cycle in under 10 minutes from `hermes skills install` to first transaction hash.

---

## Day 3 — Repo public + plugin path live (T2 ships)

**Goal**: `hermes plugins install botcoinmoney/hermes-botcoin --enable` works end-to-end.

1. Push this repo to `https://github.com/botcoinmoney/hermes-botcoin` (public).
2. Tag `v0.1.0`. GitHub release notes pulled from `BUILD_PLAN.md` Day 0.
3. Validate the install path: on a clean machine, `hermes plugins install botcoinmoney/hermes-botcoin --enable`, work through the env prompts, restart Hermes, run `/botcoin setup`. Confirm the `pre_llm_call` hook fires when the user types "how do I earn money?".
4. Add a CI workflow (`.github/workflows/ci.yml`) running `pytest -q` and `python -m py_compile` on every push, plus a basic ruff check.
5. Open an issue tracker template for users who hit setup snags; pin a "common errors" issue with the seven entries from the [Pitfalls](./skills/mining-strategy/SKILL.md#common-failure-modes) table in the bundled skill.
6. Submit the repo to:
   * `0xNyk/awesome-hermes-agent` — pull request adding BOTCOIN under the `Crypto / Web3` section.
   * `hermesatlas.com` — community map submission.

End-of-day exit gate: green CI on `main`, plus a verified `hermes plugins install` walkthrough video (private link to the team) showing the full flow from prompt to receipt tx.

---

## Day 4 — MCP server published (T3 ships)

**Goal**: BOTCOIN mining as a one-line `mcp_servers:` entry, usable in any MCP-aware client.

1. Build `mcp_server/` separately:

   ```bash
   cd mcp_server && python -m build && twine upload dist/*
   ```

   Publish `hermes-botcoin-mcp` to PyPI.
2. Bump `mcp_server/README.md` with the exact YAML stanza for Hermes, Claude Desktop, and Cursor.
3. Confirm the MCP server runs against the nookplot wallet end-to-end (same smoke test as Day 1, but driven through `mcp` instead of the plugin).
4. Add a top-level `mcp_servers:` install snippet to the project README.
5. Reach out to the maintainer of `gizdusum/hermes-blockchain-oracle` (Solana MCP precedent) for cross-promotion — both projects benefit from a single "blockchain MCP servers for Hermes" landing page.

End-of-day exit gate: `pip install hermes-botcoin-mcp` resolves, `hermes-botcoin-mcp` runs, and the tools surface inside Hermes after a config reload.

---

## Day 5 — Discoverability hooks polished + ERC-8004 wired

**Goal**: BOTCOIN tools surface to users *before* they ask, and successful mines compound an on-chain reputation signal.

1. `pre_llm_call` hook: capture concrete metrics (avg injections per session, click-through to `/botcoin setup`) — instrument with structured logging into `~/.hermes/logs/botcoin.log` (append-only, opt-out via `BOTCOIN_DISABLE_DISCOVERABILITY=1`).
2. Tighten the trigger list: include `passive income`, `crypto agent`, `agent earnings`, while suppressing on second/third turns when a snap was already injected within 10 minutes.
3. ERC-8004 binding: if the user has an `agentId`, plumb it through `BOTCOIN_AGENT_ID` and exercise the auth-time bind path. Add a `botcoin_bind_agent_id` tool for explicit binds. Verify the scorecard reflects the bound `agentId`.
4. Land `/botcoin scorecard` in the slash UX with a pretty-printed ASCII summary alongside the JSON dump.

End-of-day exit gate: the discoverability hook fires on at least 90% of mining-relevant test prompts and never on unrelated prompts (regression-checked with a 50-prompt fixture in `tests/test_hooks.py`).

---

## Day 6 — Autonomous cron miner + safety rails

**Goal**: a user can type one slash command and walk away — the agent mines in the background, hard cost ceilings, durable logs, fail-loud-on-balance-drop.

1. New tool `botcoin_autostart`: when called, programmatically creates a Hermes cron job (via the `cronjob` agent tool already in `tools/cronjob_tools.py`) running `hermes-botcoin-mine --max-attempts 1 --cooldown 90 --quiet` every 90s with `no_agent=True`.
2. Add a hard ceiling: `BOTCOIN_MAX_ATTEMPTS_PER_DAY` env (default 100) — the cron script reads `~/.hermes/cron/output/<job-id>/*.md` to count today's attempts and exits early when exceeded.
3. Add `botcoin_autostop`: removes the job, logs final per-day cost.
4. Wire delivery: `deliver: telegram` (or whichever messaging adapter is configured) so successful solves fire a notification with the receipt hash + epoch credit count.
5. `/botcoin mine start|stop` slash subcommands wrap (1) and (3).

End-of-day exit gate: nookplot agent runs unattended for 24 hours under the cron miner, reports per-attempt metrics, never busts the cost ceiling, never spams on rate limits.

---

## Day 7 — `optional-skills/blockchain/botcoin-mining/` upstream PR

**Goal**: BOTCOIN ships in the Hermes repo as an officially listed optional skill, alongside `base/` and `solana/`.

1. Open a PR against `NousResearch/hermes-agent` adding `optional-skills/blockchain/botcoin-mining/` with the same `SKILL.md` + `scripts/botcoin_client.py` we host on the well-known endpoint, but tweaked for `youssefea`-style attribution conventions (author = `botcoinmoney`).
2. PR description includes:
   * Demo: `hermes skills install official/blockchain/botcoin-mining` → first solve in <2 minutes (linked GIF).
   * Mention the existing `optional-skills-catalog.md` precedent (Mercury, Hermes Blockchain Oracle, Base, Solana).
   * MIT license, no new dependencies (helper script is stdlib-only unless EOA mode is used).
3. Wait for review. Address feedback. (Plan day budget: 1 day to draft, 0 days for review — the merge happens whenever Nous merges.)

End-of-day exit gate: PR opened, CI green on the upstream repo's PR pipeline, a maintainer has tagged it for review.

---

## Day 8 — Multi-channel discoverability blitz + post-mortem

**Goal**: maximize organic discovery before the natural news cycle ends.

1. Submit to:
   * `skills.sh` index (the `SkillsShSource` in `tools/skills_hub.py`) — coordinate via the `0xNyk/awesome-hermes-agent` listing's metadata.
   * `Hermes Atlas` (`hermesatlas.com`).
   * `awesome-hermes-agent` repo (PR adds entry to README).
   * `awesome-mcp-servers` (or equivalent) for the MCP path.
   * `awesome-erc-8004` (links us to the reputation registry ecosystem).
2. Publish a single canonical "How to integrate BOTCOIN with Hermes" guide on `agentmoney.net/blog/` covering all three install paths + the cron mode.
3. Tweet thread from @botcoinmoney showing all three install paths (skill, plugin, MCP) and the autonomous miner running with a live receipt feed.
4. Post-mortem doc (`POSTMORTEM.md` in this repo): what worked, what surprised us, three measurable success metrics over the next 30 days (active miners installed via Hermes, total attempts via the plugin, total BOTCOIN claimed via Hermes).
5. File any cleanup issues for the v0.2.0 milestone (e.g. browser-based wallet signer, one-click stake-from-Hermes flow via Bankr swap path, `/botcoin pool` for joining an existing pool).

End-of-day exit gate: all three install paths are listed in at least three external indexes; the `hermesatlas.com` and `awesome-hermes-agent` PRs are merged or pending; the post-mortem captures a measurable starting baseline.

---

## After Day 8: v0.2.0 candidates

These are explicitly out of scope for the 8-day plan — they fold into the next iteration:

* Bundled core PR — submit `plugins/botcoin/` as a `kind: backend` plugin to `NousResearch/hermes-agent`. Higher bar than the skill PR; only attempt after the skill PR lands.
* Browser-wallet signer (WalletConnect / EIP-1193) for users who don't want to expose a private key locally.
* `botcoin_swap` tool for "I have ETH, get me to Tier 1" via Bankr or a DEX router on Base.
* Pool builder helper: `hermes botcoin pool deploy` / `pool join <addr>` per the BOTCOIN protocol's pool spec.
* RL training loop for `mining-strategy` skill effectiveness (Atropos / Tinker — both already core deps via `[rl]` extra in Hermes).

---

## Cross-cutting principles

* **One library, three channels.** Plugin, MCP server, and well-known skill all share `src/hermes_botcoin/` (or, in the skill's case, fall back to a stdlib-only helper that calls the same coordinator endpoints with the same retry semantics).
* **Nothing on disk that isn't reproducible.** Every piece of code in this repo is reproducible from `BOTCOIN_DOCS.md` + `coordinator.agentmoney.net/.well-known/skill.md` — no hand-curated state.
* **The agent is the solver.** In every interactive path, the user's existing Hermes-configured LLM is the one solving challenges. The plugin only spends user-supplied API keys in *explicitly autonomous* contexts (`hermes-botcoin-mine`, cron jobs).
* **No core-file edits to Hermes upstream.** Per the May 2026 rule in `AGENTS.md` line 509, every Hermes change is additive: new optional skill, new bundled plugin (later), or external repos.
* **Secrets stay in `~/.hermes/.env`.** Logged keys are rejected by `tools.py` error wrappers (defensive but explicit).
