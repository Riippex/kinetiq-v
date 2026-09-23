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
| `identity` | Cognito User Pool, Resource Server (`kinetiq/coach`), Web & Mobile App Clients | Customer auth, OIDC for Alexa+ MCP | AWS Managed Identity |
| `ecr` | 2 ECR Repositories (`backend`, `web`), vulnerability scan on push, lifecycle rules | Container image registry | ECR |
| `compute` | ECS Cluster (Fargate & Fargate Spot), ALB (HTTP/HTTPS), 2 Target Groups, 4 Task Definitions (backend, web, worker, migrate), 3 ECS Services | Application execution | Public (ALB) / Private App (Tasks) |
| `messaging` | EventBridge Custom Bus, EventBridge DLQ, SQS Consumer Queue, Consumer DLQ, Event Rules | Transactional outbox event fan-out | AWS Managed Messaging |
| `monitoring` | 4 CloudWatch Log Groups (14-day retention), AWS Budgets budget ($50/mo limit with 4 alert thresholds) | Observability & spend control | CloudWatch / Budgets |
| `iam` | ECS Execution Role, Backend Task Role, Worker Task Role, GitHub Actions OIDC Deployer Role | Least-privilege IAM policies & CI/CD trust | IAM |

---

## 2. Itemized Cost Breakdown (us-east-1, Hackathon Environment)

All prices reflect standard AWS on-demand pricing in `us-east-1` (N. Virginia) as of late 2026.

| Component | Sizing / Configuration | Hourly Rate | Estimated Monthly (730 hrs) | Cost Mitigation Applied |
|---|---|---|---|---|
| **NAT Gateway** | 1 NAT Gateway (shared across AZs) | $0.045 / hr | ~$32.85 | `single_nat_gateway = true` (saves ~$33/mo vs multi-AZ) |
| **RDS PostgreSQL** | `db.t4g.micro` (2 vCPU Arm, 1 GB RAM), Single-AZ, 20 GB gp3 | $0.016 / hr + $0.115/GB-mo | ~$13.98 | Single-AZ + Arm Graviton2 instance; 20 GB minimum storage |
| **ElastiCache Redis** | `cache.t4g.micro` (0.5 GB RAM), Single node, Redis 7 | $0.016 / hr | ~$11.68 | Single-node dev cluster; Graviton2 instance |
| **ECS Fargate Compute** | 3 tasks (backend: 0.25 vCPU/0.5GB, web: 0.25 vCPU/0.5GB, worker: 0.25 vCPU/0.5GB) on Fargate Spot | ~$0.011 / hr total | ~$8.03 | `use_fargate_spot = true` (~70% discount off standard $26.66/mo) |
| **Application Load Balancer** | 1 ALB, 2 target groups, <5 LCUs for hackathon | $0.0225 / hr + LCU | ~$17.50 | Shared ALB for both Web and API routing rules |
| **Secrets Manager** | 3 active secrets (Database, Redis, Django Secret Key) | $0.40 / secret / mo | $1.20 | Centralized JSON credentials to minimize secret count |
| **CloudWatch Logs** | 4 log groups, 14-day retention, <2 GB monthly ingestion | Free tier / minimal | ~$0.50 | 14-day retention cap; debug logging disabled in production |
| **Amazon S3** | Private media + Terraform state (<1 GB) | Free tier / minimal | ~$0.05 | S3 lifecycle rules abort incomplete multipart uploads after 7 days |
| **Amazon Cognito** | User pool (<50,000 MAU) | $0.00 | $0.00 | Covered by AWS Free Tier |
| **Amazon EventBridge & SQS** | Custom bus + queues (<1M events/month) | $0.00 | $0.00 | Covered by AWS Free Tier |
| **Amazon Bedrock** | Claude 3 Haiku routine coaching generation (~50 requests/mo) | On-demand tokens | ~$0.20 | Constrained generation prompts; small token usage |
| **Total Steady-State** | **Complete Hackathon Environment** | **~$0.117 / hr** | **~$86.00 / month** | **Budget configured at $50/mo with notifications** |

> [!TIP]
> **Active Testing Strategy**: If resources are only run during active testing periods (e.g., 6 hours per day, 5 days a week = ~130 hrs/month), the monthly cost drops to **~$15.20/month**!

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

## 6. Zero-Cost Teardown Runbook

When pausing active hackathon development or completing the project:

### Option A: Complete Teardown (Zero Recurring Cost)
```powershell
# 1. Generate destroy plan
terraform -chdir=infra/terraform/environments/hackathon plan -destroy -out=tfplan-destroy

# 2. Execute destroy upon confirmation
terraform -chdir=infra/terraform/environments/hackathon apply tfplan-destroy
```
*Note: S3 media bucket and ECR repositories will retain objects if `force_destroy` is false. To delete retained objects before destroy, empty the S3 bucket using `aws s3 rm s3://<bucket-name> --recursive`.*

### Option B: Partial Suspend (Preserve DB & State, Stop Compute & NAT)
To preserve database records and certificates while cutting ~80% of ongoing costs:
1. Scale ECS services to 0:
   ```powershell
   aws ecs update-service --cluster kinetiq-v-hackathon-cluster --service kinetiq-v-backend-hackathon --desired-count 0
   aws ecs update-service --cluster kinetiq-v-hackathon-cluster --service kinetiq-v-web-hackathon --desired-count 0
   aws ecs update-service --cluster kinetiq-v-hackathon-cluster --service kinetiq-v-worker-hackathon --desired-count 0
   ```
2. Stop the RDS instance temporarily (can be stopped for up to 7 days before AWS auto-starts):
   ```powershell
   aws rds stop-db-instance --db-instance-identifier kinetiq-v-hackathon-db
   ```
