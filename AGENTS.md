# Agent Workflow

- Repository text, code comments and artifacts are English; conversation may be Spanish.
- This repository owns the Django modular product, clients, PostgreSQL records, Redis cache, business events and Alexa+ MCP. Pose inference, target tracking and engine evaluation belong to kinetiq-v-vision.
- Read [architecture](docs/architecture.md), [stack](docs/technology-stack.md), and relevant executable contracts before boundary changes.
- Follow [pull-request workflow](docs/runbooks/pull-requests.md): scoped branch, proportional validation, commit, push and PR to develop. Never merge or promote main without explicit authorization.
- Public material belongs in docs/. Private notes belong in ignored documents/. Read AGENTS.local.md when present for local context; never publish it.
- Use [agent skill routing](docs/runbooks/agent-skills.md) when the task matches a skill. Local graph indexes are not authoritative or publishable.
- Preserve unrelated changes and distinguish planned, implemented and verified behavior. Do not spawn subagents unless requested.
