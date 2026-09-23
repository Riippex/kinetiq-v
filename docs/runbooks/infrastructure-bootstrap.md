# Infrastructure Bootstrap and IAM Boundary

This runbook explains the two-tier deployment design introduced to correct
Kinetiq V Block 7 (KV-701/KV-702), and the manual steps required once, before
the automated `Deploy` workflow can run at all.

## Why two tiers

The `kinetiq-v-hackathon-github-deployer` IAM role that GitHub Actions
assumes (via OIDC) is deliberately scoped to only what a routine app
deployment needs: push images to the two ECR repositories, register/update
ECS task definitions, run the migration and worker tasks, and update the
backend/web services -- see `infra/terraform/modules/iam/main.tf`'s
`github_deployer_permissions` policy for the exact statements.

It cannot, and must not, run `terraform apply` against the full
`infra/terraform/environments/hackathon` configuration: that would require
create/update/delete permissions across every module (VPC, RDS,
ElastiCache, Cognito, S3, IAM roles, EventBridge/SQS, CloudWatch, the ALB
and its listeners/certificates) -- permissions indistinguishable in
practice from account-administrator access. A leaked or compromised
GitHub Actions run should be able to push a bad image or roll back a
service; it should never be able to touch networking, IAM, identity or
database configuration.

So:

- **Infrastructure provisioning and changes** (creating or modifying
  anything under `infra/terraform/environments/hackathon` beyond an ECS
  task definition's image) are a **manual, human-run process**, using your
  own AWS credentials (a real IAM user or role with the permissions below,
  never the root account), following Section 5 of
  `docs/runbooks/aws-deployment-costs.md` (`terraform plan -out=tfplan`,
  review the saved plan, `terraform apply tfplan` -- never
  `-auto-approve`).
- **Image builds and ECS deployments** (a new commit becoming the running
  app) are automated, via `workflow_dispatch` on the `Deploy` GitHub
  Actions workflow, gated by the `hackathon` GitHub Environment and the
  OIDC role's environment-scoped trust policy (see below).

## One-time bootstrap (manual, before the first `terraform apply`)

Performed once by a human operator with their own sufficiently-privileged
(but not root) AWS credentials.

1. **Create the Terraform remote-state bucket.** Section 4 of
   `docs/runbooks/aws-deployment-costs.md` has the exact `aws s3api`
   commands. This bucket is never managed by the Terraform configuration
   it backs (a deliberate chicken-and-egg: the bucket must exist before
   `terraform init` can use it as a backend), so it is also never destroyed
   by `terraform destroy` and must be removed manually if you want it gone.

2. **Register a domain and delegate it to Route53.** Required: the
   hackathon environment has no HTTP-only mode (`domain_name` has no
   default; `terraform plan` refuses to run without it). This Terraform
   configuration does not purchase a domain or create a hosted zone for
   you (`data "aws_route53_zone"` in
   `infra/terraform/modules/compute/main.tf` looks up an **existing**
   public zone by name) -- register the domain with any registrar, create
   a public Route53 hosted zone for it, and point the registrar's
   nameservers at that zone, before setting `domain_name` in
   `terraform.tfvars`.

3. **Run the first `terraform apply`** for the whole stack (networking
   through compute), following the plan/review/apply steps in Section 5 of
   `docs/runbooks/aws-deployment-costs.md`. This is what actually creates
   the `github_deployer` IAM role and its OIDC trust relationship -- until
   this step has run once, there is no role for the GitHub Actions
   workflow to assume at all.

4. **Record the deployer role's ARN as a GitHub secret, and the domain as
   a GitHub variable.** After the apply above:
   ```powershell
   terraform -chdir=infra/terraform/environments/hackathon output -raw github_deployer_role_arn
   ```
   Set this as the `AWS_DEPLOY_ROLE_ARN` **secret** on the `hackathon`
   GitHub Environment (Settings > Environments > hackathon > Environment
   secrets) -- not a repository-level secret, since the trust policy below
   only allows workflow runs that went through this exact Environment.
   Also set a `KINETIQ_DOMAIN_NAME` **variable** (Environment variables,
   not secrets -- it is not sensitive) on the same Environment, with the
   exact same value as `domain_name` in `terraform.tfvars`. `deploy.yml`'s
   `verify` job reads this to health-check the real HTTPS origin directly,
   never the ALB's own DNS name.

5. **Configure the `hackathon` GitHub Environment's protection rules**
   (Settings > Environments > hackathon):
   - **Required reviewers**: add at least one. This is the actual human
     approval boundary for every deploy -- the workflow YAML enforces the
     *shape* of the boundary (every job in `.github/workflows/deploy.yml`
     carries `environment: hackathon`), but the reviewer list itself is
     repository configuration, not something Terraform or the workflow
     file can set.
   - **Prevent self-review**: where your GitHub plan supports it (this is
     plan-dependent -- on some plans/repo visibility combinations, the
     person who dispatched the run can also be an eligible reviewer for
     it), configure required reviewers such that the person triggering a
     deploy cannot be its sole approver. If your plan does not expose this
     control, treat requiring **at least two** required reviewers as the
     practical equivalent, and document that the "prevent self-review"
     control itself was unavailable at the time of setup.
   - **Deployment branches**: restrict to `develop` only ("Selected
     branches and tags" > add `develop`). This is enforced by GitHub
     itself before the job even starts, and is the stronger of the two
     `develop`-only controls -- `guard-branch` in `deploy.yml` (checking
     `github.ref` and failing loudly otherwise) is the second, workflow-level
     one, kept as defense in depth, not a substitute for this setting.

6. **GitHub OIDC immutable subject -- verify before relying on the trust
   policy.** `infra/terraform/modules/iam/main.tf`'s OIDC trust policy
   currently uses GitHub's long-standing name-based subject format:
   ```
   repo:<org>/<repo>:environment:hackathon
   ```
   If this repository is subject to a GitHub OIDC policy requiring
   numeric owner/repository IDs in the subject claim instead of (or
   alongside) names, **this configuration does not guess that format** --
   it is explicitly left blocked pending verification, because guessing
   wrong would produce a trust policy that looks correct but is either
   silently broken (deploys fail) or, worse, silently wrong in a way that
   is not obviously wrong. Before the first real `terraform apply`:
   - Retrieve the two numeric IDs (`iam/variables.tf` already accepts
     them as `github_repository_id` / `github_repository_owner_id`,
     currently unused):
     ```bash
     gh api repos/<owner>/<repo> --jq .id
     gh api users/<owner> --jq .id   # user-owned repository
     gh api orgs/<owner> --jq .id    # organization-owned repository
     ```
   - Confirm the *actual* subject claim format GitHub currently issues for
     this repository by decoding a real OIDC token from an actual
     workflow run, rather than trusting documentation that may be stale by
     the time you read it. Add a temporary debug step to a workflow run
     through the `hackathon` Environment:
     ```yaml
     - name: Decode the actual OIDC token claims
       run: |
         TOKEN=$(curl -sLS -H "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" \
           "$ACTIONS_ID_TOKEN_REQUEST_URL&audience=sts.amazonaws.com" | jq -r .value)
         echo "$TOKEN" | cut -d. -f2 | base64 -d 2>/dev/null | jq .
       env:
         ACTIONS_ID_TOKEN_REQUEST_TOKEN: ${{ env.ACTIONS_ID_TOKEN_REQUEST_TOKEN }}
         ACTIONS_ID_TOKEN_REQUEST_URL: ${{ env.ACTIONS_ID_TOKEN_REQUEST_URL }}
     ```
     (requires `permissions: id-token: write`, already set on
     `deploy.yml`). Inspect the printed `sub` claim directly -- this is
     the ground truth, not a guess.
   - If the real `sub` format differs from what the trust policy currently
     matches, update the `StringEquals` condition on
     `aws_iam_role.github_deployer` in `infra/terraform/modules/iam/main.tf`
     to the real format (wiring in `var.github_repository_id` /
     `var.github_repository_owner_id` as needed) **before** relying on
     this role for anything -- remove the temporary debug step afterward.
   - Until this is verified, treat the deploy role's trust policy as
     **unverified against current GitHub OIDC requirements**, not as a
     known-working configuration.

7. **Verify the OIDC trust is otherwise exact.** A workflow run on any
   branch, pull request or tag that does *not* go through the `hackathon`
   Environment cannot assume this role, regardless of what the workflow
   file says -- confirm this by attempting `aws sts get-caller-identity`
   from a PR-triggered workflow run; it must fail.

## Ongoing IAM hygiene

- Never attach `AdministratorAccess`, `PowerUserAccess`, or any policy
  with `Resource: "*"` combined with a mutating `Action` (anything other
  than `Describe*`/`List*`/`Get*`) to the `github_deployer` role. If a
  future feature genuinely needs the automated workflow to touch a new
  resource type, add a narrowly scoped statement for exactly that
  resource, following the existing pattern in
  `infra/terraform/modules/iam/main.tf`.
- The `ecs:cluster` condition on `ECSDeployBoundToCluster` and the
  `s3:prefix` condition on the task roles' S3 access are load-bearing:
  removing them turns a same-account-scoped permission into a
  cross-cluster or cross-bucket-prefix one. Do not simplify them away.
- Terraform state itself (in the bootstrap S3 bucket) contains the
  database password, Redis auth token and Django secret key in plaintext
  (Terraform does not encrypt values within the state file body, only
  the bucket's server-side encryption protects it at rest). Anyone with
  read access to that bucket can read every credential this stack
  manages -- scope IAM policies for human operators accordingly, and
  never grant broader-than-necessary `s3:GetObject` on it.
