# AWS Deployment Costs and Infrastructure Runbook

Updated September 2026. This runbook accompanies the Kinetiq V Terraform infrastructure (`infra/terraform/`) for Milestone M7 (AWS delivery, work item KV-701).

> [!IMPORTANT]
> **Safety Invariant**: A valid Terraform configuration or planned state is **not** an authorization to deploy. In accordance with KV-701 acceptance criteria, live cloud infrastructure must never be provisioned from unreviewed plans.

---

## 1. Architecture and Resource Mapping

Kinetiq V's AWS deployment consists of two independent repositories and Terraform states:
1. **`kinetiq-v` (This repository)**: Owns product infrastructure (networking, PostgreSQL on RDS, ElastiCache Redis, S3 private media, Cognito identity, ECR repos, ECS Fargate services for backend/web/worker, Application Load Balancer, EventBridge/SQS, and CloudWatch monitoring).
2. **`kinetiq-v-vision` (Vision repository)**: Owns vision inference infrastructure, MLflow tracking, OpenCV pipelines, and benchmark workloads.

### Component Inventory (`infra/terraform/modules/`)

| Module | Resources | Purpose | Network Tier |
|---|---|---|---|
| `networking` | VPC, 2 Public Subnets, 2 Private App Subnets, 2 Private Data Subnets, 1 IGW, 1 NAT GW + EIP, Route Tables | Core network isolation | Dual AZ (`us-east-1a`, `us-east-1b`) |
| `security` | 4 Security Groups (ALB, ECS Tasks, RDS, ElastiCache) | Least-privilege ingress/egress | VPC |
| `database` | RDS PostgreSQL 17 (`db.t4g.micro`), Subnet Group, Parameter Group (forced SSL), Secrets Manager credentials | Relational product state | Private Data (isolated) |
| `cache` | ElastiCache Redis 7 (`cache.t4g.micro`), Subnet Group, Parameter Group, in-transit & at-rest encryption, Secrets Manager token | Cache, Channels live fan-out, pairing | Private Data (isolated) |
| `storage` | S3 Media Bucket (`kinetiq-media-${env}-${account}`), SSE-S3, Public Access Block, CORS, Lifecycle rules | Private athlete progress photos | S3 (Private HTTPS) |
| `identity` | Cognito User Pool, Hosted UI Domain (required by the OAuth authorization-code flow), Resource Server (`kinetiq/coach`), Web & Mobile App Clients | Customer auth, OIDC for Alexa+ MCP | AWS Managed Identity |
| `ecr` | 2 ECR Repositories (`backend`, `web`), vulnerability scan on push, lifecycle rules | Container image registry | ECR |
| `compute` | ECS Cluster (Fargate & Fargate Spot), ALB (HTTPS required -- `domain_name` has no HTTP-only fallback; HTTP always redirects to HTTPS), ACM certificate (auto-issued and DNS-validated for `domain_name`, or bring-your-own via `certificate_arn`) + Route53 validation/alias records, 2 Target Groups, 4 Task Definitions (backend, web, worker, migrate), 2 ECS Services (backend, web) + 1 EventBridge Scheduler schedule (media-cleanup, a one-shot batch job -- see note below) | Application execution | Public (ALB) / Private App (Tasks) |
| `messaging` | EventBridge Custom Bus, EventBridge DLQ, SQS Consumer Queue, Consumer DLQ, Event Rules | Transactional outbox event fan-out -- **provisioned but currently idle**: no application code publishes real events or consumes this queue yet (see note below) | AWS Managed Messaging |
| `monitoring` | 4 CloudWatch Log Groups (14-day retention), AWS Budgets budget ($50/mo limit with 4 alert thresholds) | Observability & spend control | CloudWatch / Budgets |
| `iam` | ECS Execution Role, Backend Task Role, Worker Task Role, GitHub Actions OIDC Deployer Role (environment-scoped trust, no full-stack `terraform apply` permissions), EventBridge Scheduler Execution Role | Least-privilege IAM policies & CI/CD trust | IAM |

> [!NOTE]
> The media-cleanup worker is a scheduled ECS task, not a service: the command it runs (`process_media_cleanup`) processes whatever is due and exits, so running it as a continuously-restarting service would crash-loop forever. `messaging`'s EventBridge/SQS resources match the outbox-consumer design in `docs/architecture.md`, but no publisher or consumer code exists in `services/backend` yet (the only wired event publisher is a log-only stub) -- implementing one is a separate, application-layer feature, not part of this infrastructure.

---

## 2. Itemized Cost Breakdown (us-east-1, Hackathon Environment)

All prices reflect standard AWS on-demand pricing in `us-east-1` (N. Virginia) as of late 2026.

| Component | Sizing / Configuration | Hourly Rate | Estimated Monthly (730 hrs) | Cost Mitigation Applied |
|---|---|---|---|---|
| **NAT Gateway** | 1 NAT Gateway (shared across AZs) | $0.045 / hr | ~$32.85 | `single_nat_gateway = true` (saves ~$33/mo vs multi-AZ) |
| **RDS PostgreSQL** | `db.t4g.micro` (2 vCPU Arm, 1 GB RAM), Single-AZ, 20 GB gp3 | $0.016 / hr + $0.115/GB-mo | ~$13.98 | Single-AZ + Arm Graviton2 instance; 20 GB minimum storage |
| **ElastiCache Redis** | `cache.t4g.micro` (0.5 GB RAM), Single node, Redis 7 | $0.016 / hr | ~$11.68 | Single-node dev cluster; Graviton2 instance |
| **ECS Fargate Compute** | 2 always-on services (backend, web: 0.25 vCPU/0.5GB each) on Fargate Spot, running 730 hrs/mo | ~$0.0073 / hr total | ~$5.35 | `use_fargate_spot = true` (~70% discount off standard); worker is now a scheduled task (see Section 1), not a 3rd always-on service |
| **EventBridge Scheduler (media-cleanup)** | 1 task (0.25 vCPU/0.5GB) on Fargate Spot, running only for its own duration each time the schedule fires (default every 15 min) | Usage-based | Low, scales with actual cleanup work rather than 730 always-on hours; not separately itemized here since it depends on run duration | Scheduled task instead of an always-restarting service |
| **Application Load Balancer** | 1 ALB, 2 target groups, <5 LCUs for hackathon | $0.0225 / hr + LCU | ~$17.50 | Shared ALB for both Web and API routing rules |
| **Secrets Manager** | 3 active secrets (Database, Redis, Django Secret Key) | $0.40 / secret / mo | $1.20 | Centralized JSON credentials to minimize secret count |
| **CloudWatch Logs** | 4 log groups, 14-day retention, <2 GB monthly ingestion | Free tier / minimal | ~$0.50 | 14-day retention cap; debug logging disabled in production |
| **Amazon S3** | Private media + Terraform state (<1 GB) | Free tier / minimal | ~$0.05 | S3 lifecycle rules abort incomplete multipart uploads after 7 days |
| **Amazon Cognito** | User pool (<50,000 MAU) + Hosted UI domain | $0.00 | $0.00 | Covered by AWS Free Tier |
| **Amazon Route53 + ACM** | Required (`domain_name` has no HTTP-only fallback -- see Section 1): 1 public hosted zone + DNS-validated certificate | $0.50 / mo per hosted zone (the zone itself is billed to whoever owns it; if you create it outside this Terraform for `domain_name`, it is the same $0.50/mo either way) + $0.00 for the ACM certificate | $0.50 | Reused if you already have a hosted zone for another purpose in the same account -- no per-record charge for the two records this adds |
| **Amazon EventBridge & SQS** | Custom bus + queues (<1M events/month) -- currently idle, no publisher/consumer exists yet | $0.00 | $0.00 | Covered by AWS Free Tier |
| **Amazon Bedrock** | Claude 3 Haiku routine coaching generation (~50 requests/mo) | On-demand tokens | ~$0.20 | Constrained generation prompts; small token usage |
| **Total Steady-State** | **Complete Hackathon Environment** | **~$0.115 / hr** | **~$83.81 / month** | **Budget configured at $50/mo with notifications** |

> [!NOTE]
> This total is a component-by-component estimate from published on-demand rates, not a guarantee: it excludes data-transfer charges, the media-cleanup scheduled task's own (small, usage-based) runtime, and any Bedrock usage beyond the ~50 requests/mo assumption, and any AWS pricing change since this was last reviewed. Verify current `us-east-1` pricing for RDS, ElastiCache, Fargate and the NAT Gateway before relying on this figure for budgeting. Every other line above, including Route53/ACM, is already included in the $83.81 total -- there is nothing configured by default that this total omits.

> [!TIP]
> **Active Testing Strategy**: If resources are only run during active testing periods (e.g., 6 hours per day, 5 days a week = ~130 hrs/month), the ECS/ALB/RDS/ElastiCache hourly-rate components above drop to roughly ~130 hrs of billing instead of ~730 -- but the NAT Gateway, Secrets Manager and any RDS storage or ECR/S3 storage already in use are billed independently of hours-running and do **not** shrink this way. This is a meaningful reduction, not a specific guaranteed monthly figure -- recompute it from the table above for your actual usage pattern rather than relying on a single quoted number.

---

## 3. Spend Controls and AWS Budgets

To prevent unexpected costs or run-away charges during the hackathon:
1. **AWS Budget**: Automatically configured in `infra/terraform/modules/monitoring` at `$50.00 USD / month`.
2. **Threshold Alerts**:
   - **50% of budget ($25)**: Email alert on actual spend.
   - **80% of budget ($40)**: Email alert on actual spend.
   - **100% of budget ($50)**: High-priority email alert on actual spend.
   - **100% forecasted ($50)**: Email alert if projected monthly spend exceeds the limit.
3. **AWS Free Tier Credits**: Note that AWS promotional credits do not function as a hard spend stop. Budgets and CloudWatch alarms remain the active notification mechanism.

---

## 4. Remote State S3 Bucket Bootstrap

Terraform state for the `hackathon` environment is managed in a dedicated, private, versioned S3 bucket with native S3 locking (`use_lockfile = true`, supported in Terraform 1.10+ without requiring DynamoDB).

Before running `terraform init` against remote state for the first time, bootstrap the bucket using the AWS CLI:

```powershell
# Set your preferred state bucket name and region
$BUCKET_NAME="kinetiq-v-terraform-state-hackathon"
$REGION="us-east-1"

# 1. Create S3 bucket
aws s3api create-bucket `
    --bucket $BUCKET_NAME `
    --region $REGION

# 2. Block all public access
aws s3api put-public-access-block `
    --bucket $BUCKET_NAME `
    --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

# 3. Enable bucket versioning (critical for state safety and recovery)
aws s3api put-bucket-versioning `
    --bucket $BUCKET_NAME `
    --versioning-configuration Status=Enabled

# 4. Enable default AES256 server-side encryption
aws s3api put-bucket-encryption `
    --bucket $BUCKET_NAME `
    --server-side-encryption-configuration '{"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}'
```

---

## 5. Review and Deployment Workflow

When the project owner decides to apply infrastructure changes:

1. **Format and Validate**:
   ```powershell
   terraform fmt -check -recursive infra/terraform
   terraform -chdir=infra/terraform/environments/hackathon init
   terraform -chdir=infra/terraform/environments/hackathon validate
   ```

2. **Generate and Inspect Plan**:
   ```powershell
   terraform -chdir=infra/terraform/environments/hackathon plan -out=tfplan-hackathon
   ```
   *Carefully review the proposed additions and verify resource counts and costs.*

3. **Apply (Only Upon Explicit Confirmation)**:
   ```powershell
   terraform -chdir=infra/terraform/environments/hackathon apply tfplan-hackathon
   ```

---

## 6. Teardown and Cost-Reduction Runbook

When pausing active hackathon development or completing the project. Neither
option below is actually zero cost while any resource remains provisioned;
figures are read directly from the Section 2 table, not estimated.

### Option A: Complete Teardown (removes essentially all ongoing charges)
```powershell
# 1. Generate destroy plan
terraform -chdir=infra/terraform/environments/hackathon plan -destroy -out=tfplan-destroy

# 2. Execute destroy upon confirmation
terraform -chdir=infra/terraform/environments/hackathon apply tfplan-destroy
```
*Caveats -- this is not literally $0.00, and none of the following is destroyed by Terraform:*
- *S3 media bucket and ECR repositories retain their objects/images if `force_destroy` is false (the current default): `aws_s3_bucket`/`aws_ecr_repository` destroy will fail until emptied. Empty the S3 bucket with `aws s3 rm s3://<bucket-name> --recursive` and delete ECR images with `aws ecr batch-delete-image` first, or `terraform destroy` will not complete.*
- *If `skip_final_snapshot = false`, RDS leaves a final snapshot behind (small ongoing storage charge) that must be deleted separately with `aws rds delete-db-snapshot`.*
- *The remote-state S3 bucket (`kinetiq-v-terraform-state-hackathon`, Section 4) is never touched by this destroy -- it is bootstrapped outside this Terraform run and holds a negligible (~$0.01-0.02/mo) but nonzero storage cost until manually deleted.*

### Option B: Partial Suspend (preserve DB & state, stop compute & NAT)
This does **not** cut costs by ~80%: the NAT Gateway, ALB and ElastiCache
keep running and billing regardless of ECS desired-count or RDS being
stopped, because none of those three are addressed by this option. Using
the exact Section 2 per-component figures, only ECS Fargate compute
(~$5.35/mo) and RDS compute (not its storage, which AWS continues to bill
while stopped -- roughly ~$13.98/mo of the RDS line stops accruing) are
actually avoided here; NAT (~$32.85), ALB (~$17.50), ElastiCache (~$11.68),
Secrets Manager (~$1.20), CloudWatch (~$0.50) and Route53/ACM (~$0.50) do
not. Against the reconciled $83.81/mo total, that is a reduction of
roughly **(5.35 + 13.98) / 83.81 ≈ 23%**, not 80% -- to actually stop NAT/
ALB/ElastiCache billing, use Option A instead.

1. Scale the ECS services to 0 (the worker no longer has a service to scale
   -- it is a scheduled task, see Section 1, and already only runs, and is
   only billed, for the few seconds/minutes its schedule fires):
   ```powershell
   aws ecs update-service --cluster kinetiq-v-hackathon-cluster --service kinetiq-v-backend-hackathon --desired-count 0
   aws ecs update-service --cluster kinetiq-v-hackathon-cluster --service kinetiq-v-web-hackathon --desired-count 0
   ```
2. Stop the RDS instance temporarily (can be stopped for up to 7 days before AWS auto-starts it again; storage charges continue while stopped):
   ```powershell
   aws rds stop-db-instance --db-instance-identifier kinetiq-v-hackathon-db
   ```
3. To also stop the NAT Gateway, ALB and ElastiCache charges without a full
   destroy, those resources must themselves be removed (NAT Gateway and its
   EIP, the ALB, and the ElastiCache replication group) -- at that point
   most of the stack is gone and Option A's `terraform destroy` is the
   simpler, equally reversible (`terraform apply` re-creates everything)
   path.
