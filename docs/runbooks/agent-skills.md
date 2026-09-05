# Agent Skill Routing

Canonical skills live in .agents/skills/. Byte-identical copies under .claude/skills/ support Claude Code. Edit the canonical skill, then run tools/sync-agent-skills.ps1. The script updates only matching Kinetiq skills and does not delete unrelated skills.

| Skill | When to use |
|---|---|
| kinetiq-architecture | Module, API, event, data ownership or deployment boundaries |
| kinetiq-graph-tools | Cross-file navigation, diff impact, docs-to-code audits |
| kinetiq-delivery | Preparing direct develop commits or task PRs |
| kinetiq-aws-review | Terraform, IAM, deployment costs and managed MLflow |
| kinetiq-product-slice | An end-to-end product behavior across client, API and persistence |

Use installed Amazon Vega skills for Vega manifests, SDK setup, navigation/focus and build work when relevant. They are external dependencies, not copied into this repository. If unavailable consult official platform documentation and report missing tooling. Developer MCPs assist development; the runtime Alexa+ MCP remains application code.
