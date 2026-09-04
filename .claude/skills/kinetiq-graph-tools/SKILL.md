---
name: kinetiq-graph-tools
description: Choose graph tools for cross-file navigation, diff impact, or public documentation-to-code audits in Kinetiq. Skip isolated edits.
---

# kinetiq-graph-tools

Read docs/runbooks/graph-tools.md. Use codegraph for symbol/caller navigation, GitNexus for diff impact, and graphify for documentation/code relationships. Check tool availability, repository root, freshness and input exclusions before trusting results. Keep each repository's index separate; trace cross-service boundaries through contracts. Graphs are navigation evidence, not proof of runtime behavior. Do not include documents/, local instructions, media, models or credentials in indexing/export. Never disable ignore parsing. Inspect working-tree changes after index generation. If a tool is unavailable, use rg and source reads and report that limitation. Do not auto-install or enable remote embeddings merely to answer a navigation question.
