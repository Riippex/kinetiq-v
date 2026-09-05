# Delivery Workflow

During active construction, use develop as the integration branch and push validated commits directly when shared review is unnecessary. Sync develop before starting and before pushing. A short-lived codex/ branch and pull request to develop remain available when isolation, review, or parallel work makes them useful. main is a separate release boundary. Before work inspect git status; preserve unrelated changes and active work by other agents.

Complete a versioned task with proportional validation, explicit staging, a Conventional Commit, and a push to develop or the selected task branch. Reuse an existing task branch and pull request for follow-ups when that path was chosen. Check the staged diff for private notes, local state, credentials, raw media and generated graph output. Do not use git add . without reviewing the full scope. Report the destination branch and actual checks state; include the pull-request URL when one exists.

Direct integration into develop is authorized for the active construction phase. Updating main, merging develop into main, or publishing a release requires explicit owner authorization. Do not bypass configured repository protections or invent protections that have not been configured. If the user asks for local-only work, keep it local. If remote authentication fails, preserve local work and report the exact blocker without changing credentials.

Public docs: docs/. Private working material: documents/, AGENTS.local.md and CLAUDE.local.md. Skills are versioned; assistant settings and graph indexes are local. Ignoring a tracked file does not untrack it: inspect git ls-files and remove only specifically authorized private paths from the index when necessary.
