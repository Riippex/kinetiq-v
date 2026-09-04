# Pull Request Workflow

Use short-lived codex/ branches from develop. main is a separate release boundary. Before work inspect git status; preserve unrelated changes and active work by other agents.

Complete a versioned task with proportional validation, explicit staging, a Conventional Commit, push and a reviewable PR targeting develop. Reuse an existing task branch/PR for follow-ups. Check the staged diff for private notes, local state, credentials, raw media and generated graph output. Do not use git add . without reviewing the full scope. Report the PR URL, base branch and actual checks state.

Merging, approving, closing, retargeting or promoting develop to main requires explicit owner authorization. Do not bypass reviews or invent branch protections that have not been configured. If the user asks for local-only work, keep it local. If remote authentication fails, preserve local work and report the exact blocker without changing credentials.

Public docs: docs/. Private working material: documents/, AGENTS.local.md and CLAUDE.local.md. Skills are versioned; assistant settings and graph indexes are local. Ignoring a tracked file does not untrack it: inspect git ls-files and remove only specifically authorized private paths from the index when necessary.
