---
name: kinetiq-aws-review
description: Plan or review Kinetiq Terraform, IAM, deployment or managed MLflow changes and their cost implications.
---

# kinetiq-aws-review

Read docs/technology-stack.md and docs/architecture.md. Map each resource to its owning repository/state and identify exact runtime/CI principals. Scope permissions and PassRole to concrete resources. Include workers, MLflow operating hours, networking and persistence in estimates. Credits are not a spend cap. Verify supported versions and regional prices before apply. Check OIDC trust, state handling, rollback/migrations and service readiness. A plan or installed CLI is not a deployment. Do not use a root profile for routine operations.
