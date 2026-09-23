# Claude Code Workflow

Read and follow [AGENTS.md](AGENTS.md), [architecture](docs/architecture.md), and [delivery workflow](docs/runbooks/pull-requests.md).

Project skills are mirrored under .claude/skills/ from .agents/skills/. Read only matching skills. CLAUDE.local.md contains optional ignored machine/private context. Public docs live in docs/; documents/ is private. Never infer deployment or main-release approval from a skill.

After completing an implementation block or a set of corrections, always use the `kinetiq-review-checkpoint` skill. Freeze and report the exact review scope, then tell the user the block is ready for direct review in Codex. Do not invoke a Codex extension, slash command, background review or external reviewer from Claude.
