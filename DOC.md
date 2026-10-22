# Narx Commerce: build and operate the project

This is the single project guide. Repository READMEs explain only their own entry point.
The project models application teams delivering a commerce system and a platform team
providing CI, infrastructure and GitOps. Team memberships represent a learning scenario;
they do not mean a company or real delivery team operates this environment.

## Current status

The six foundation PRs are merged and their post-merge checks passed. They introduced
ownership, reusable workflow validation, Terraform state storage and a shared Helm chart.
Application migration PRs now add the commerce source, container builds, application
tests and an integrated local Docker preview. Review/merge those PRs before expecting
the source on main. Kubernetes deployments, SQS processing, release automation and AWS
infrastructure remain pending. No AWS resources have been provisioned.

The organisation uses GitHub Free and the repositories are private by choice. PRs and
CODEOWNERS record the intended review process, but GitHub cannot enforce protected
branches and required reviews for these private repositories until the organisation
upgrades to GitHub Team. Do not describe the current review policy as enforced.

## Repository map and ownership

| Repository | Owning team | Boundary |
| --- | --- | --- |
| `commerce-frontend` | Frontend | Customer storefront and admin interface |
| `commerce-catalogue` | Catalogue | Public product read API; reads the commerce core over HTTP |
| `commerce-orders` | Orders | Accounts, inventory, checkout, payments, orders and cart; planned worker/outbox |
| `platform-ci` | Platform | Versioned reusable GitHub Actions workflows |
| `platform-infrastructure` | Platform | Terraform and this project guide |
| `platform-gitops` | Platform/release | Helm, Argo CD, environment releases and platform add-ons |

Each runtime component builds independently. The cart source is in `commerce-orders/cart`
and produces its own Python image. The future worker will live with orders because
they share a business owner and event contracts; it will scale independently. The
three application repositories currently produce four runtime images. Shared CI
workflows prevent copying whole pipelines into every repository. Existing
`Local-Narx-Space` repositories remain untouched.

The source application keeps stock reservation and order insertion atomic in the
orders commerce core's PostgreSQL transaction. The migration deliberately retains
that boundary. The Go catalogue is a read facade, not an independent inventory database.
Splitting inventory into its own transactional service would require a reservation
protocol and compensation; it is not achieved merely by making another repository.

Developer: `subhankar12-spec`. Intended independent reviewer: `Code-S-12` through
the `code-reviewers` team. Service teams receive write access to their repositories;
the platform team receives write access to the platform repositories. Organisation
owners retain their GitHub administrative rights. A single person's multiple accounts
do not establish genuine independent review; the exercise models the control.

## Target environments

| Environment | Location | Purpose |
| --- | --- | --- |
| dev | Local Kubernetes | Fast integration feedback |
| qa | Local Kubernetes, isolated namespace and data | Release verification |
| production | AWS EKS during scheduled learning sessions | Cloud delivery and operations exercises |

EKS control-plane subnets span two AZs as AWS requires. Worker capacity and RDS will
be in one AZ for cost control. This is not AZ-resilient production availability.
Use the same immutable image digest through all environments. Local nodes must be
able to run the selected image architecture; confirm this before choosing Graviton.

Proposed AWS services: VPC, EC2-backed EKS, ECR, ALB, ACM, RDS PostgreSQL Single-AZ,
SQS with a dead-letter queue, IAM, Secrets Manager, S3, CloudWatch and AWS Budgets.
Evaluate NAT versus endpoint/network costs before choosing the network layout;
private nodes require an intentional outbound connectivity design. Use the existing
DNS provider unless a Route 53 hosted zone is needed.

The commerce core owns PostgreSQL products, stock, accounts, orders and payments.
Catalogue reads products through HTTP and cart owns Redis keys. Services do not query
each other's databases. The core has not been decomposed into database-per-domain
microservices; any later split must be an explicit, tested architecture change.

## Target delivery flow

1. Developer branches from `main` and opens a PR in the service repository.
2. Hosted GitHub Actions runners run unprivileged tests, lint and security checks.
   PR validation receives no deployment secrets and no AWS deployment permissions.
3. An independent reviewer approves; required checks pass; the PR is squash-merged.
4. The trusted main workflow builds one image, scans it and pushes it to ECR using
   a narrowly scoped AWS IAM role via GitHub OIDC. Each image is identified by digest.
5. Release automation changes the dev image digest through a GitOps PR. Argo CD
   running locally pulls the approved desired state and deploys it.
6. After dev verification, a QA promotion PR carries the same digest. The target
   policy is automatic merge for eligible QA promotions after required checks.
7. After QA verification, a production promotion PR requires human approval.
8. The EKS Argo CD instance reconciles the approved production configuration. Health
   and smoke tests verify the release. Failure handling must update desired state
   so Argo does not repeatedly restore a failed release.

Current application CI validates workflow syntax and builds runtime images through
their test stages. BuildKit caches avoid separate test-image builds and duplicate
test wrappers. PRs have read-only tokens and no AWS credentials. ECR publishing,
security scanning, signing and release promotion are still pending.

The numbered release flow is the target, not the current implementation. GitHub-hosted runners do
not directly access the local cluster. Local Argo CD pulls changes; trusted smoke
tests will run inside the local cluster. Do not expose an unauthenticated local
deployment endpoint or give an untrusted PR a self-hosted runner with cluster access.

Automatic QA promotion requires a trusted, narrowly scoped review/merge policy for
verified release changes. A blanket human-review rule would also block QA automation.
Design and test that exception before enabling auto-merge; do not grant a release bot
unrestricted bypass of production approval. No bot approval or merge exception exists yet.

Image pulls from private ECR require explicit authentication in local Kubernetes;
short-lived registry credentials will need automated refresh. EKS uses scoped node
permissions for image pulls. CI uses OIDC and application AWS access uses Pod Identity.
These mechanisms must be implemented and tested before claiming end-to-end delivery.

Reusable workflows are pinned by commit SHA. Each caller names the approved revision.
The first foundation PRs may point to the reviewed candidate SHA so their checks can
run before the central PR is merged; release workflows must use an approved revision.

## Queue behaviour to implement

The payment provider's verified webhook confirms payment; a browser redirect does
not. Store the payment/order change and an outbox event in one database transaction.
An outbox publisher sends that event to SQS. A worker performs asynchronous order
processing. A crash between sending and recording completion can produce duplicates,
so both publishing and consuming must tolerate retries.

Consumers record an event ID and make state changes transactionally. Delete a queue
message only after successful processing. Configure visibility timeout, bounded
retries, a dead-letter queue, backlog/oldest-message alerts and a redrive procedure.
Never place card data, passwords or complete customer records into queue messages.

Dev/QA use ElasticMQ with separate queues. It implements a subset of SQS behaviour;
real AWS integration checks must verify IAM, queue policies, retries and failure
handling. Payment integration remains in sandbox mode.

## Application source and local preview

The migration preserves the existing storefront, accounts, cart, admin, order history,
Razorpay test-mode integration, refunds and INR pricing. Source provenance and licenses
are recorded in the application READMEs. It does not import Jenkinsfiles, per-service
Helm copies or Jenkins report-converter scripts.
Checkout now requires authentication and delivery information. The old anonymous demo
path that created confirmed orders without payment is removed from the migrated app.

| Component | Source | Runtime port | Metrics |
| --- | --- | --- | --- |
| Frontend | `commerce-frontend/src` and `public` | 8080 | `/metrics` |
| Catalogue | `commerce-catalogue/*.go` | 8081 | `/metrics` |
| Orders/core | `commerce-orders/src` | 8083 | `/actuator/prometheus` |
| Cart | `commerce-orders/cart` | 8082 | `/metrics` |

All services expose `/health/live` and `/health/ready`. Catalogue refuses to return
the old hard-coded USD demo data if `COMMERCE_URL` is absent. Its readiness follows
the commerce dependency; liveness does not. Production Helm values will need each
component's real port and resources rather than the chart's generic defaults.

The Docker Compose preview is a developer convenience, not the Kubernetes dev/QA
delivery path. Clone the application repositories and `platform-gitops` as siblings:

```bash
mkdir -p narx-commerce
cd narx-commerce
gh repo clone Narx-Space-Prod/commerce-frontend
gh repo clone Narx-Space-Prod/commerce-catalogue
gh repo clone Narx-Space-Prod/commerce-orders
gh repo clone Narx-Space-Prod/platform-gitops
cd platform-gitops
# For an unmerged migration review, check out feat/application-migration in all four repos.
umask 077
python3 - <<'PY'
from pathlib import Path
import secrets
keys = ['DATABASE_PASSWORD', 'SESSION_SECRET', 'FIXTURE_PAYMENT_SECRET', 'FIXTURE_WEBHOOK_SECRET']
with Path('local/.env').open('x') as output:
    output.write(''.join(f'{key}={secrets.token_hex(32)}\n' for key in keys))
    output.write('PUBLIC_ORIGIN=http://localhost:18080\nAPP_PORT=18080\nAPP_BIND_ADDRESS=127.0.0.1\n')
PY
docker compose --parallel 1 --env-file local/.env -f local/compose.yaml build
docker compose --env-file local/.env -f local/compose.yaml up --no-build -d --wait
```

The secret-generation command refuses to overwrite an existing file. Open
`http://localhost:18080`. From a different computer, forward that port over SSH:

```bash
ssh -L 18080:127.0.0.1:18080 your-linux-user@your-linux-host
```

Then use `http://localhost:18080` on the computer running the browser. For deliberate
LAN exposure, change `APP_BIND_ADDRESS`, `APP_PORT` and `PUBLIC_ORIGIN` together in
the local env file. `PUBLIC_ORIGIN` must exactly match the browser's scheme, host and
port; otherwise state-changing requests correctly fail the origin check.

The preview uses a local payment simulator and says so in the browser confirmation.
It makes no Razorpay transaction. It verifies the application's signature checks,
state changes and refund handling but does not verify the real Razorpay sandbox.
Actual provider tests will use backend-only Razorpay test credentials in Kubernetes.
Fixture flags and fixture keys must never appear in AWS production configuration.

Register your own customer account; there is no default admin password. An operator
can grant that account admin access only in this local preview, using the exact email
registered above and a reviewed SQL command inside the PostgreSQL container. Do not
make the first registrant an administrator or add a public role-assignment endpoint.
For a local operator, open a SQL prompt and replace the example email with the account
you registered (there is no fixed admin account/password):

```bash
docker compose --env-file local/.env -f local/compose.yaml exec postgres psql -U commerce -d commerce
```

```sql
UPDATE customers SET role='admin' WHERE email='your-admin@example.com';
```

Then type `\q` to exit and sign in with that account at `/admin`.
The integration test promotes only its generated throwaway account, then exercises
customer/admin separation, product version conflicts, order processing and refunds.

```bash
NARX_LOCAL_TEST=1 NARX_COMPOSE_PROJECT=narx-commerce python3 -m unittest discover -s tests -v
docker compose --env-file local/.env -f local/compose.yaml down
# Only for intentionally discarding this local preview's PostgreSQL data:
# docker compose --env-file local/.env -f local/compose.yaml down --volumes
```

The test mutates its named local stack. Do not point it at a shared or production
database. PostgreSQL data survives ordinary `down`; carts and simulator records do
not. Stopping and restarting the payment simulator does not constitute a provider
recovery test and can leave its old local orders needing a fresh checkout.

Migration verification: all four runtime Docker builds passed their application tests.
The opt-in full-stack test passed against an isolated local project, including denied
guest checkout, required delivery, customer/admin separation, INR product data, stock
reservation, idempotent checkout, invalid payment signature rejection, payment retries,
order isolation, product version conflicts, fulfilment and refund retries. This evidence
does not cover the real payment provider, SQS processing, Kubernetes releases or AWS.

## Infrastructure workflow

Infrastructure PRs will run formatting, validation, mock tests, a security scan and
an AWS-backed plan when scoped credentials exist. The foundation only implements
formatting, validation and mocked state-security tests. It has no apply permission.

Before any deployment, select the AWS account and region, review a regional estimate,
and configure budget alerts. The target is INR 1,000/month through limited runtime;
this is not an enforced billing cap. EKS, worker nodes, ALB, RDS, storage, networking,
logs, taxes and retained resources all contribute. Scaling workers to zero does not
stop EKS cluster fees. EKS must be destroyed to stop its cluster-hour charges.

The eventual apply workflow must use a reviewed plan from the same commit, verify
the target AWS account, serialize state-changing operations, and require approval.
Destroy is a separate manual workflow with environment/account confirmation. It
must remove workloads and AWS load balancers before deleting the cluster and retain
the intentionally persistent state, images and database backup data. Include retained
storage costs in the estimate and test recovery into a newly created cluster.

## Commands available in this foundation

Clone the repositories you need:

```bash
gh repo clone Narx-Space-Prod/platform-infrastructure
gh repo clone Narx-Space-Prod/platform-gitops
gh repo clone Narx-Space-Prod/platform-ci
```

Use Terraform 1.16.x. The committed provider lock file pins the tested AWS provider.
The following checks use mocked AWS calls and do not create cloud resources:

```bash
cd platform-infrastructure
terraform fmt -check -recursive
terraform -chdir=bootstrap init -backend=false -input=false -lockfile=readonly
terraform -chdir=bootstrap validate
terraform -chdir=bootstrap test
```

The bootstrap root defines a private, versioned, encrypted state bucket and rejects
HTTP access. It deliberately prevents bucket destruction. Its tests use `mock_provider`
even though their command is named `apply`; this is not a real AWS apply.

After account/region/cost approval, a platform operator can bootstrap the bucket:

```bash
cp bootstrap/bootstrap.example.tfvars bootstrap/session.tfvars
# Edit session.tfvars with the selected region and a globally unique bucket name.
aws sts get-caller-identity
terraform -chdir=bootstrap plan -var-file=session.tfvars -out=bootstrap.tfplan
# Review account, region and the plan before the next command.
terraform -chdir=bootstrap apply bootstrap.tfplan
```

The root starts with local state to break the circular dependency of creating its
own backend. Keep that local state secure. After the bucket exists, add a reviewed
`backend "s3" {}` block inside `terraform {}` and run `terraform init -migrate-state`
with `bucket`, `region`, `key=bootstrap/terraform.tfstate` and `use_lockfile=true`.
Future roots use different keys, such as `production/terraform.tfstate`. S3 locking
requires `.tflock` object permissions; no DynamoDB lock table is needed. Never delete
bootstrap state while destroying a learning session. State lifecycle cleanup is a
separate operator decision, not part of session teardown.

Helm checks, with dummy image references only:

```bash
cd ../platform-gitops
# Dummy digest for rendering only; this image must never be deployed.
validation_digest="sha256:$(printf '%064d' 0)"
helm lint --strict charts/commerce-service -f environments/dev/values.yaml \
  --set image.repository=registry.invalid/validation-only/catalogue --set "image.digest=$validation_digest"
helm template catalogue charts/commerce-service -n commerce-dev -f environments/dev/values.yaml \
  --set image.repository=registry.invalid/validation-only/catalogue --set "image.digest=$validation_digest"
```

Environment values are chart validation fixtures, not application releases.
They cannot be used to deploy the app until CI publishes real images and GitOps
release records identify their repository and digest.

## Remaining implementation milestones

1. Foundation PRs are merged. Upgrade GitHub Team before enforcing private-repo
   branch protection. Required reviewers, no self-review, no force pushes, resolved
   conversations, passing checks and restricted workflow changes must be verified.
2. Review the application migration: source, licenses, runtime builds, unit tests and
   local integration checks. Existing Java 21/Spring Boot, Node 22, Go and Python 3.12
   runtimes are retained. Cart ownership is with the orders team; catalogue is a read API.
3. Implement image security scanning/signing/publishing and the event/outbox/worker
   flow. Add queue failure and duplicate-message tests; do not claim messaging is implemented yet.
4. Establish isolated local dev/QA, Argo CD, registry authentication, queue and data
   stores; verify releases through GitOps without Jenkins or direct CI cluster access.
5. Produce a regional cost estimate and Terraform VPC/EKS/ECR/RDS/SQS/IAM modules.
   Configure scoped identity, state, secrets and the gated plan/apply/destroy workflows.
6. Add production ingress/TLS, Prometheus/Grafana/Alertmanager, CloudWatch logs,
   service metrics, backup/restore, release notifications and recovery runbooks here.
7. Verify a full release, failed rollout, queue retry/DLQ, restore and complete teardown.
   Record evidence, measured cost and remaining limitations in this guide.

## References

- [GitHub private-repository protection availability](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- [Terraform S3 state and native lockfile](https://developer.hashicorp.com/terraform/language/backend/s3)
- [Terraform provider mocks](https://developer.hashicorp.com/terraform/language/tests/mocking)
- [GitHub OIDC for AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)
- [EKS subnet requirements](https://docs.aws.amazon.com/eks/latest/userguide/network-reqs.html)
- [SQS delivery semantics](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues-at-least-once-delivery.html)
