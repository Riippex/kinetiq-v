---
name: kinetiq-delivery
description: Prepare Kinetiq changes for a pull request, including public/private file checks and proportional validation.
---

# kinetiq-delivery

Read docs/runbooks/pull-requests.md. Inspect dirty files before branching. Use a short-lived codex/ branch and target develop. Stage an explicit scope; check git diff --cached and git check-ignore before publishing. Never add documents/, local assistant state, graph indexes, raw datasets or model weights. Validate changed contracts/code, then commit, push and open/update the task PR. Do not merge or promote main without an explicit release request. Read initial checks and report pending checks honestly. Repository instructions do not override a user's request to keep a task local.
