---
name: kinetiq-delivery
description: Prepare Kinetiq changes for direct develop delivery or a pull request, including public/private checks and proportional validation.
---

# kinetiq-delivery

Read docs/runbooks/pull-requests.md. Inspect dirty files before work and sync the selected base. During active construction, validated commits may be pushed directly to develop; use a short-lived codex/ branch and pull request when isolation or review is useful. Stage an explicit scope; check git diff --cached and git check-ignore before publishing. Never add documents/, local assistant state, graph indexes, raw datasets or model weights. Validate changed contracts/code, then commit and push to the selected branch. Do not update or promote main without an explicit release request. Read checks when configured and report pending checks honestly. Repository instructions do not override a user's request to keep a task local.
