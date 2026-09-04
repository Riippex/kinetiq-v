---
name: kinetiq-architecture
description: Implement or review Kinetiq module boundaries, APIs, events, persistence or deployment changes.
---

# kinetiq-architecture

Read docs/architecture.md and the affected contracts. Product is a Django modular monolith; Vision is a separate REST service. Domain dependencies point inward and business invariants are shared by GraphQL and MCP use cases. Follow module data ownership. Treat Redis as disposable, outbox delivery as at-least-once, and consumers as idempotent. For boundary changes update producer, contract, consumer and proportional verification together. Preserve the selected target through epochs and reject stale observations. Record deliberate architecture changes in docs rather than silently creating exceptions.
