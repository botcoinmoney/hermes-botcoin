# Coordinator-Side Deliverables

Files in this directory must be hosted by the BOTCOIN coordinator at exactly the paths shown below for `hermes skills install …` to resolve. Hermes' `WellKnownSkillSource` (`tools/skills_hub.py:708-866`) requires the index to live at `/.well-known/skills/index.json` with skill files under `/.well-known/skills/<name>/<file>`.

## Hosting Map

| Local path | Public URL |
|---|---|
| `well-known-skills-index.json` | `https://coordinator.agentmoney.net/.well-known/skills/index.json` |
| `skills/botcoin-mining/SKILL.md` | `https://coordinator.agentmoney.net/.well-known/skills/botcoin-mining/SKILL.md` |
| `skills/botcoin-mining/scripts/botcoin_client.py` | `https://coordinator.agentmoney.net/.well-known/skills/botcoin-mining/scripts/botcoin_client.py` |

Serve them with `Content-Type: application/json` and `text/markdown; charset=utf-8` respectively. CORS headers are already enabled on `/.well-known/*` per the existing coordinator config — no change needed.

## Verifying

After hosting, test with:

```bash
hermes skills search https://coordinator.agentmoney.net/.well-known/skills/index.json
hermes skills install https://coordinator.agentmoney.net/.well-known/skills/index.json#botcoin-mining
```

The first command should print one result for `botcoin-mining`. The second should drop the SKILL.md and helper script into `~/.hermes/skills/<name-or-category>/botcoin-mining/`.

## Notes

- The existing `/.well-known/skill.md` (singular) used by Openclaw / agent-card.json is **not removed**. The new `/.well-known/skills/` (plural) is additive.
- Path validation: file paths under each skill must satisfy `_validate_bundle_rel_path` in `tools/skills_hub.py:121` — no `..`, no absolute paths.
- The helper script depends on `eth-account` only when the user picks EOA signing; the import is deferred so `python3 botcoin_client.py status` works on a fresh install.
