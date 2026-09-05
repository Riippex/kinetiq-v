# Technology Stack

Status: application foundations are installed; feature implementation and infrastructure provisioning are pending. Runtime and dependency versions are locked in `package-lock.json` and `services/backend/uv.lock`.

| Area | Selected direction |
|---|---|
| Web | Next.js App Router, TypeScript |
| Mobile | React Native and Expo development builds |
| TV | Separate Fire OS and Vega applications with compatible shared packages |
| Product backend | Python, Django, Strawberry GraphQL; modular monolith |
| Persistence | PostgreSQL on RDS, Django ORM and migrations |
| Cache and live fan-out | Redis/ElastiCache and Django Channels |
| Alexa+ | Official Python MCP SDK, Streamable HTTP |
| Identity and media | Cognito and private S3 storage |
| Generative features | Bedrock behind a constrained provider adapter |
| Compute | ECR, ECS Fargate and HTTPS load balancing |
| Asynchronous processing | PostgreSQL outbox, EventBridge, SQS and idempotent workers |
| Infrastructure/delivery | Terraform modules and environment roots; GitHub Actions with OIDC |

The current development baseline uses Node.js 24.19, Next.js 16.3, React Native 0.86 with Expo SDK 57, Python 3.12 and Django 5.2 LTS. Mobile uses Expo Router. These versions describe the checked-in foundation and can change through reviewed dependency updates.

GraphQL and MCP invoke the same domain services. Next.js manages the browser-facing session and calls the backend; it does not write the database. Photo objects are private and accessed through authorized short-lived operations. Redis is disposable. Vision is a separate REST service with its own model lifecycle.

See [architecture](architecture.md), [coaching experience](coaching-experience.md), [routine planning](routine-planning.md) and [workflow](runbooks/pull-requests.md). No deployment, device compatibility or model-quality claim follows from selecting this stack.
