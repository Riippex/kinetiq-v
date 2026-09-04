# Graph Tool Routing

| Task | Preferred tool |
|---|---|
| Symbols, callers, imports during implementation | codegraph |
| Current diff impact and graph queries | GitNexus |
| Public docs, contracts and implementation relationships | graphify |

Check the installed version/help, correct repository root and index freshness. Index the two repositories independently; cross-repository claims require explicit contract/source verification. These tools are optional accelerators; use rg and source inspection if unavailable. Their capabilities vary by installed version. Do not assume an index watcher or MCP is active.

Local CLI checks confirmed codegraph and gitnexus are installed on the development host. Graphify was found as a local Claude skill. This does not install those tools for a fresh clone or another assistant. No index is claimed to exist yet.

For codegraph inspect init/status/sync help before indexing. For GitNexus the inspected CLI supports analyze --index-only --skip-agents-md; verify those flags on other machines. Prefer index-only behavior to avoid generated instruction or package edits. Keep gitignore parsing enabled and use .gitnexusignore. Inspect git status/diff after any initial index operation; do not keep unrelated generated metadata automatically.

For graphify stage only reviewed public source/docs/contracts as input, with outputs in ignored graphify-out/. Do not point broad extraction at the whole workspace where ignored private notes remain readable. Verify exclusions for every tool: Git ignore is a publication rule, not a universal tool access boundary. No remote embeddings or external upload is configured by this workflow.

Indexes .codegraph/, .gitnexus/ and graphify-out/ stay ignored. Rebuild after relevant source/branch changes; verify findings against source. Runtime authorization, ownership and delivery guarantees cannot be proven by graph edges alone.
