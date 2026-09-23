---
name: kinetiq-review-checkpoint
description: Freeze a completed Kinetiq implementation or correction block so the user can hand its exact scope to Codex for direct review.
---

# Kinetiq review checkpoint

Use this skill when finishing an implementation block or a set of review corrections. Do not use it for questions, planning, status updates, or work that produced no reviewable repository change.

Before committing, freeze the review scope: record the block's base commit, list its changed paths, and confirm unrelated changes are excluded. After committing, report the repository root, base commit, head commit, included commits, changed paths, dirty-tree state, validation results and known limitations. End by telling the user that the block is ready for direct review in Codex.

The implementation agent must not invoke a Codex extension, slash command, background review or external reviewer. Claude's responsibility ends with producing the bounded handoff and preserving the checkout for review.

When Codex receives the user's review request:

1. Inspect `git status --short --untracked-files=all` and verify no other agent or review is changing the checkout.
2. Review only the frozen implementation block. For uncommitted work, first ensure the working tree contains only that block. For committed work, use its recorded base commit; never substitute `origin/develop` merely because local commits are ahead.
3. If the base or scope is ambiguous, stop and ask the user instead of reviewing a cumulative branch diff.
4. Perform the review directly in the active Codex task, using the relevant Kinetiq review skills and proportional validation. Do not delegate the review back to Claude or require a Claude plugin.
5. Report findings ordered by severity with concrete file references, distinguish introduced defects from pre-existing debt, and state whether the block can be marked Verified.

Run an adversarial review only when the user explicitly asks for it. Use a focused prompt and the same frozen scope.

After corrections, Codex may run one verification pass over the original block plus its corrections when the user reports that the corrections are ready. A verification pass finding new unrelated work ends the checkpoint and is reported separately. Commit or push only when repository delivery rules authorize it. Review each Kinetiq repository from its own root; cross-repository claims require a separate explicit contract review.
