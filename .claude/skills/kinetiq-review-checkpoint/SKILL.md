---
name: kinetiq-review-checkpoint
description: Hand a completed Kinetiq implementation or correction block to Codex for review only after the user confirms the verification checkpoint.
---

# Kinetiq review checkpoint

Use this skill when finishing an implementation block or a set of review corrections. Do not use it for questions, planning, status updates, or work that produced no reviewable repository change.

Before committing, freeze the review scope: record the block's base commit, list its changed paths, and confirm unrelated changes are excluded. Summarize that scope and its validation in the normal final response. End by asking the user exactly: **"¿Seguimos con la verificación de Codex?"** Do not start review in the same turn or interpret the implementation request as approval.

When the user confirms:

1. Inspect `git status --short --untracked-files=all` and verify no other agent or review is changing the checkout.
2. Review only the frozen implementation block. For uncommitted work, first ensure the working tree contains only that block. For committed work, use its recorded base commit; never substitute `origin/develop` merely because local commits are ahead.
3. If the base or scope is ambiguous, stop and ask the user instead of reviewing a cumulative branch diff.
4. Invoke one background `/codex:review` for that scope and tell the user to check `/codex:status`. Do not commit, push, start another implementation, or launch another review while it runs.
5. Treat findings as review input. Validate each one against the frozen scope before changing code; ignore findings outside it unless the user explicitly expands the block.

Run an adversarial review only when the user explicitly asks for it. Use a focused prompt and the same frozen scope.

After corrections, summarize and ask again before one verification pass over the original block plus its corrections. Do not begin a third pass unless the user explicitly requests it. A verification pass finding new unrelated work ends the checkpoint and is reported separately. Commit or push only after the agreed review completes and repository delivery rules authorize it. Review each Kinetiq repository from its own root; cross-repository claims require a separate explicit contract review.
