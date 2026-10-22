# Narx Commerce: build and operate the project

This is the single project guide. Repository READMEs explain only their own entry point.
The project models application teams delivering a commerce system and a platform team
providing CI, infrastructure and GitOps. Team memberships represent a learning scenario;
they do not mean a company or real delivery team operates this environment.

## Current status

The project is in its foundation phase. The six repositories have been created. The first
PRs introduce ownership, reusable workflow validation, Terraform state storage and a
shared Helm chart. Application migration, release automation, local deployments and
AWS infrastructure are not implemented yet. No AWS resources have been provisioned.

The organisation uses GitHub Free and the repositories are private by choice. PRs and
CODEOWNERS record the intended review process, but GitHub cannot enforce protected
branches and required reviews for these private repositories until the organisation
upgrades to GitHub Team. Do not describe the current review policy as enforced.

## Repository map and ownership

| Repository | Owning team | Boundary |
| --- | --- | --- |
| `commerce-frontend` | Frontend | Customer storefront and admin interface |
| `commerce-catalogue` | Catalogue | Product data and inventory; owns its data |
| `commerce-orders` | Orders | Checkout, payments, order history, worker and outbox |
| `platform-ci` | Platform | Versioned reusable GitHub Actions workflows |
| `platform-infrastructure` | Platform | Terraform and this project guide |
| `platform-gitops` | Platform/release | Helm, Argo CD, environment releases and platform add-ons |

Each application service builds and releases independently. The orders worker lives
with the orders service because they share a business owner and event contracts;
it will be a separate deployment that can scale independently. Shared CI workflows
prevent copying whole pipelines into every repository. There is no separate cart
repository in this design; cart ownership and migration are to be settled with the
application implementation. Existing `Local-Narx-Space` repositories remain untouched.

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

Database ownership stays with each service: separate databases and credentials can
share one small RDS instance for cost control. Services must not query each other's
tables. The number and size of databases will be confirmed during app migration.

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

This is the target flow, not the current implementation. GitHub-hosted runners do
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

1. Review and merge foundation PRs; upgrade GitHub Team before enforcing private-repo
   branch protection. Required reviewers, no self-review, no force pushes, resolved
   conversations, passing checks and restricted workflow changes must be verified.
2. Inventory existing application code; preserve users/admin/order/payment behaviour;
   settle runtime versions, cart ownership, API contracts and database migrations.
3. Implement service tests, Dockerfiles, reusable build/scan/publish workflows and
   the event/outbox/worker flow. Add failure and duplicate-message tests.
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
