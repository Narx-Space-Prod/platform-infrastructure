# Narx Commerce: build and operate the project

This is the single project guide. Repository READMEs explain only their own entry point.
The project models application teams delivering a commerce system and a platform team
providing CI, infrastructure and GitOps. Team memberships represent a learning scenario;
they do not mean a company or real delivery team operates this environment.

## Current status

The agreed target is now fully local Narx Commerce with a dedicated Kubernetes cluster
for dev, QA and production, sharing only the existing Argo CD control plane. This is
separate from both the Jenkins Boutique project and the standalone `commerce-aws` project.

This change prepares the cluster definition, restricted registration helper and three
local Argo destinations. It does not create a new cluster or deploy real application
releases by merging. The previous dev/QA Applications are currently empty bootstrap
releases on `kind-mega-local`; they are not working storefront deployments. Shared
monitoring still includes the old Narx integration until an independent Narx stack is
ready. Existing Boutique applications and data are not migration targets.

Publishing and release reconciliation remain explicitly disabled. The GHCR migration
prepares publishing, trusted image verification and private cluster pulls; the final
reviewed builder SHA must still be pinned in callers and GitOps before activation.
ECR Terraform roots remain inactive reference scaffolding. Do not run AWS apply for
this local architecture.
GitHub release/observer Apps still need configuration, and real image signing, promotion,
checkout, rollback and notification exercises remain activation work.

The organisation uses GitHub Free and all six repositories are public. GitHub now
enforces `main` branch protection: PRs, one CODEOWNER approval, the repository's CI
checks, an up-to-date branch, resolved conversations and linear history are required.
New commits dismiss stale approvals, the latest push needs approval from someone
other than its pusher, and administrators follow these rules too. Force pushes and
branch deletion are blocked; no PR-approval bypass users, teams or apps are configured.
Organisation/repository administrators can still edit the settings; this is not an
immutable control against the organisation owner.

`code-reviewers` contains only `Code-S-12` and is named in every CODEOWNERS file.
Review approval and merge are separate actions: an authorised writer can merge only
after all required controls pass. PR authors cannot approve their own PR. Workflow
execution for PRs from external forks requires maintainer approval; organisation
members' ordinary PR checks run automatically. Execution approval does not approve
the code for merging. Default Actions tokens remain read-only and cannot approve PRs.

Before the visibility change, all Git refs including closed PR heads were scanned
with Gitleaks 8.30.1, along with 42 available Actions-run log archives and 22 build
artifacts; no secrets were detected. Two failed workflow runs had no job logs.
The tracked PEM is the public RDS CA bundle, and the tracked env file is only an
example. Generated local `.env` credentials remain ignored and were not published.
Public visibility also exposes Git history and Actions logs: never commit secrets,
real customer records or Terraform state. Future changes still need secret scanning;
this review is not a guarantee that later commits are safe.

## Repository map and ownership

| Repository | Owning team | Boundary |
| --- | --- | --- |
| `commerce-frontend` | Frontend | Customer storefront and admin interface |
| `commerce-catalogue` | Catalogue | Public product read API; reads the commerce core over HTTP |
| `commerce-orders` | Orders | Accounts, inventory, checkout, payments, orders, cart, outbox and receipt worker |
| `platform-ci` | Platform | Versioned reusable GitHub Actions workflows |
| `platform-infrastructure` | Platform | Terraform and this project guide |
| `platform-gitops` | Platform/release | Helm, Argo CD, environment releases and platform add-ons |

Each runtime component builds independently. The cart source is in `commerce-orders/cart`
and produces its own Python image. Orders API, outbox publisher and receipt worker
share one Java image, selected by `DELIVERY_ROLE=api|publisher|worker`. They run as
separate processes and can scale independently without rebuilding the application.
The three application repositories still produce four runtime images. Shared CI
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
| production | Dedicated local Narx Kubernetes cluster | Reviewed promotion, rollout and recovery exercises |

All three environments use separate namespaces and data on `kind-narx-commerce`.
The shared Argo CD runs in `kind-mega-local` and reaches only the registered Narx
namespaces. This is environment isolation within one Narx cluster, not independent
production infrastructure or high availability. Use the same immutable image digest
through all environments. AWS learning belongs to the separate `commerce-aws` project;
this local migration must not provision AWS services.

The commerce core owns PostgreSQL products, stock, accounts, orders and payments.
Catalogue reads products through HTTP and cart owns Redis keys. Services do not query
each other's databases. The core has not been decomposed into database-per-domain
microservices; any later split must be an explicit, tested architecture change.

## CI and CD: what happens after a push

An image is the sealed output of a tested build. Its digest identifies its contents.
Dev, QA and production receive the same image; rebuilding per environment would create
a different release and invalidate earlier verification. The GHCR migration is prepared
but delivery remains off until reviewed builder pins, package access and Apps are ready.

1. A developer opens a feature PR. Workflow lint/secret scanning run first. Component
   Docker builds run service tests through the runtime target, verify the non-root user,
   scan dependencies and generate an SBOM. Unfixed HIGH/CRITICAL findings also block.
   PR build jobs have contents:read only; no registry publication or release App key.
2. CODEOWNER approval and required checks are needed before merging to protected main.
   The merged commit is checked again. Changed components build; Orders/cart can run in
   parallel. Documentation-only changes skip image work while reporting the required check.
3. With DELIVERY_ENABLED=true, a main-only publisher downloads that run's exact tested
   image artifact. Its short-lived GITHUB_TOKEN receives packages:write and publishes
   `ghcr.io/narx-space-prod/commerce-COMPONENT:COMMIT`. It does not rebuild. It refuses
   a commit tag pointing to another image, reuses a matching image, and checks the final
   manifest config against the tested image. Authentication/outages fail closed.
4. GitHub OIDC gives Cosign a signing identity; it is not an AWS login. The publisher
   signs the digest and attests source provenance plus SBOM. Temporary registry login
   files are removed. GHCR permits tag mutation at the registry level, so deployment
   identity and verification use the digest, never a mutable tag such as latest.
5. The caller publishes a source release record only after its component jobs succeed.
   A separate release App requests GitOps reconciliation; scheduled reconciliation can
   recover a missed dispatch. Incomplete/failed main CI records do not qualify.
6. The GitOps verifier accepts only four exact Narx GHCR image paths, verifies source
   main CI, approved shared builder SHA, source commit, signature/provenance/SBOM and
   digest binding. All four components form the initial bundle. It opens a dev PR;
   it does not write directly to main. Trusted PR verification executes base code only
   and treats candidate release JSON as data.
7. After human review/merge, shared Argo CD applies dev on the separately registered
   Narx cluster and waits for health plus its PostSync smoke Job. A status-only observer
   App reports narx/deploy-dev for that GitOps revision. This evidence is needed before
   proposing QA with the same digests, then production after verified QA.
8. Dev, QA and production release PRs all require review under current protection. No
   automatic approval/bypass is configured. Production now targets commerce-production
   on narx-local, not AWS. QA/production frontend analysis protects the traffic switch.
   Failed desired state can propose a reviewed rollback; it never reverses database data.

Main image-transfer artifacts live one day and security evidence fourteen days. BuildKit
caches avoid duplicate test-image builds. Separate main-commit concurrency groups avoid
cancelling an earlier publication when a newer commit arrives.

Reusable workflows and actions are pinned by SHA. Merge platform-ci first, then pin
service callers and policy/builders.json to its reviewed main revision. Do not trust an
unmerged builder branch. The GitOps candidate verifier does not check out PR scripts,
even though pull_request_target has privileges to publish its status.

### Rollback and failure behaviour

A healthy deployment records the previous environment bundle and the GitOps revision
with trusted successful evidence. A QA/production failure proposes a rollback PR to
that recorded bundle. The reviewer approves, checks pass, and Argo applies the merged
rollback. This is automatic detection/proposal with reviewed recovery, not unattended
rollback execution. Dev does not automatically propose recovery. A first deployment
has no previous verified release to restore. Rollback never reverses SQL migrations,
refunds, stock changes or persistent data; migrations must remain backward compatible.
A failed rollback cannot repeatedly toggle releases because its previous pointer is empty.

Smoke tests check six readiness endpoints, INR catalogue data and the frontend response.
They do not prove a real checkout/payment transaction. Local integration tests cover
customer/admin/refund and queue-recovery behaviour using a simulator. A real provider
sandbox test and a controlled Kubernetes rollout failure remain activation checks.

If CI fails, inspect the failed job and fix through a PR. If Argo fails, inspect its
operation and hook Job before changing desired state. Never manually retag an image or
edit a Deployment behind GitOps to hide a failed rollout.

### What the Python code does

You do not need to memorise each line, but an operator should understand its inputs,
permissions, decisions and failure modes. `platform-gitops/scripts/delivery.py` is the
single release-policy entry point. `validate` checks bundle structure; `fixtures` makes
temporary CI-only image data; `reconcile` discovers signed builds and proposes release
or promotion PRs; `verify-candidate` applies trusted policy to PR data; `rollback`
proposes the recorded previous healthy bundle. External commands use argument lists,
and candidate files are never imported as Python. Unit tests mock GitHub/registry
responses; a temporary real Git remote also tests updating an existing PR branch.

`platform-infrastructure/local/bootstrap.py` handles local operator setup: namespace
and initial credentials for all three environments, restricted remote registration,
private GHCR pull credentials, and observer/notification configuration. It does not provision AWS. The existing
`tests/test_local_stack.py` exercises the complete disposable app. These scripts have
different trust boundaries and are kept separate rather than being copied into jobs.

Local verification of release policy and the full chart is available without AWS:

```bash
cd platform-gitops
python3 -m unittest discover -s tests -p 'test_delivery*.py' -v
python3 scripts/delivery.py validate
helm dependency build --skip-refresh charts/commerce
python3 scripts/delivery.py fixtures /tmp/commerce-validation.json
helm lint --strict charts/commerce -f environments/dev/runtime.yaml \
  -f /tmp/commerce-validation.json
helm template commerce charts/commerce -n commerce-dev \
  -f environments/dev/runtime.yaml -f /tmp/commerce-validation.json
# The generated images are fictional and must never be applied.
cd ../platform-infrastructure
terraform -chdir=delivery init -backend=false -input=false -lockfile=readonly
terraform -chdir=delivery validate
terraform -chdir=delivery test
```

The delivery root uses mocked plans only. The disposable full integration run on the
patched Orders, cart and catalogue images passed in 167.8 seconds, including queue
outage, duplicate, worker transaction rollback and DLQ recovery. Local image scans
reported zero HIGH/CRITICAL findings at that run; vulnerability databases change, so
CI scans again. This evidence does not replace live GHCR/signature or Argo tests.

### GitHub Apps and activation settings

Narx Commerce needs its own release and observer identities. The installed App named
`narx-commerce-release` (ID 5541020) is already used by the separate commerce-aws project;
its key must not be repurposed for this project. Create/install separate Apps for these
repositories, with webhooks disabled because dispatch/polling and Argo notifications
already supply the necessary communication paths.

| Identity | Suggested name | Repository permissions | Private-key destination |
| --- | --- | --- | --- |
| Release automation | narx-local-commerce-release | Contents read/write, Pull requests read/write, Metadata read | NARX_RELEASE_APP_PRIVATE_KEY in frontend, catalogue, orders and platform-gitops |
| Deployment evidence | narx-local-commerce-observer | Commit statuses read/write, Metadata read | argocd-notifications-secret/narx-github-privateKey via the helper |

Install on platform-gitops only while source repositories remain public. Private source
repositories would need explicitly scoped source Contents/Actions read access as well.
The release App can open/update PRs but cannot approve its own PR or bypass main rules.
The observer cannot modify code or open PRs. Store private keys outside repositories;
enter Actions secret values directly in GitHub or use gh secret set from the private
file. Never paste PEM contents in chat. App ID, installation ID and bot login are public
identifiers; the key is secret.

| Repositories | Variables and secrets |
| --- | --- |
| Three application repos | NARX_RELEASE_APP_ID, NARX_RELEASE_APP_PRIVATE_KEY secret, DELIVERY_ENABLED=false until ready |
| platform-gitops | Same release App ID/key, NARX_DEPLOYMENT_BOT_LOGIN for the observer, DELIVERY_ENABLED=false until ready |

Main-only GitHub environments remain registry-release for application publication and
registry-verification for release policy. Callers must explicitly grant packages:write
to the reusable service job; its untrusted build job overrides that with contents:read
only. The main publisher receives packages:write and signing id-token:write. GitOps
verification receives packages:read and no AWS OIDC permissions. No AWS account ID,
role or ECR login is needed for these workflows.

#### GHCR package permissions and local pulls

The prepared workflow supports private packages. Visibility is an owner decision;
first GHCR publication defaults to private even when the repository is public.
The four image packages are commerce-frontend, commerce-catalogue, commerce-orders and
commerce-cart under Narx-Space-Prod. The source label links each image to its source
repository, including cart to commerce-orders. An existing package created under a
different owner/repository must grant the publishing repository access explicitly.

For each private package, grant **platform-gitops** Read access in package Settings ->
Manage Actions access. This permits its ephemeral GITHUB_TOKEN to verify images and
Cosign evidence. Installation tokens from the release App are not registry credentials.
CI can publish with GITHUB_TOKEN; do not create a write:packages PAT for CI.

Kubernetes has no GitHub workflow token. Create a separate classic PAT with only
read:packages using a Narx-authorized operator identity, an intentional expiry and no
write/delete package permissions. Store it in a mode-600 private file outside all
repositories. This is a local registry pull credential, distinct from the release App
key, GitHub signing identity and environment database passwords. The helper transfers
it to the dedicated Narx cluster's ghcr-pull Secret via stdin without printing it.

```bash
# Supply the actual owner/file path. Do not put the token in command arguments.
python3 local/bootstrap.py refresh-registry --context kind-narx-commerce --environment dev \
  --registry-user YOUR_GITHUB_LOGIN --registry-token-file /secure/path/narx-ghcr-read-token
python3 local/bootstrap.py refresh-registry --context kind-narx-commerce --environment qa \
  --registry-user YOUR_GITHUB_LOGIN --registry-token-file /secure/path/narx-ghcr-read-token
python3 local/bootstrap.py refresh-registry --context kind-narx-commerce --environment production \
  --registry-user YOUR_GITHUB_LOGIN --registry-token-file /secure/path/narx-ghcr-read-token
```

Rotate before token expiry; update all three Secrets and verify a new pod can pull before
revoking the previous token. The file permission check prevents accidentally reading a
world/group-readable token file, but the operator must choose its actual scope correctly.
Revoking a token does not remove already cached images or stop running pods.

If the owner explicitly selects public images, change package visibility in GitHub and
set global.imagePullSecrets: [] in reviewed environment runtime values. Anonymous pulls
then work; do not store a PAT unnecessarily. Publication still requires the workflow token.

Keep all four DELIVERY_ENABLED flags false until the shared builder is reviewed/pinned,
package permissions and Narx Apps are configured, and the dedicated cluster is ready.
Enabling a variable does not publish old commits retroactively. Merge a reviewed caller
update to build all initial components, then verify four completed main release records
before expecting an initial dev PR. Do not claim private GHCR pulls/signatures were
live-tested merely because offline tests or workflow lint passed.

The delivery/ Terraform root still contains ECR/IAM scaffolding from the retired AWS
plan. It is inactive reference code and is not applied for this local architecture.
AWS infrastructure learning belongs to commerce-aws, not Narx Commerce.

### Dedicated local cluster and shared Argo CD

The agreed target is three independent projects. Narx Commerce runs dev, QA and
production on its own kind cluster, `narx-commerce`, with context
`kind-narx-commerce`. The existing Argo CD in `kind-mega-local` is the shared
management plane. Sharing Argo CD does not share application databases, namespaces,
monitoring storage, runtime credentials or release pipelines.

This migration is staged. The old `commerce-dev` and `commerce-qa` namespaces currently
exist in `kind-mega-local`, but contain no app pods or PVCs. Their Synced/Healthy Argo
status refers to empty bootstrap releases, not working applications. Shared Boutique
monitoring still contains the earlier Narx integration until the independent Narx
monitoring deployment is verified. No old resources are deleted by the bootstrap helper.

| Item | Target | Activation status |
| --- | --- | --- |
| Cluster | One dedicated kind node, pinned Kubernetes v1.34.0 image | Creation is an explicit operator command after review |
| Argo CD | Existing installation in `kind-mega-local` | Already running; keep its host cluster on |
| Workload AppProject | `narx-commerce-local`, Narx GitOps repository only | Reviewed manifest must be applied after cluster registration |
| Registered destination | `narx-local`, only three commerce namespaces | Bootstrap creates a dedicated namespace-scoped service account |
| Environments | `commerce-dev`, `commerce-qa`, `commerce-production` | Separate generated credentials and data volumes |
| Publishing/verification | GHCR with ephemeral CI tokens | Prepared; builder pins, Apps and package access still needed |
| Monitoring | Dedicated Narx stack on the Narx cluster | Pending; do not copy the Boutique monitoring Application |
| Notifications | Narx-owned webhook and observer key in shared Argo | Configure only after credentials are supplied |

The 7.5 GiB laptop cannot safely run both complete projects and three full Narx
environments at once. The cluster definition uses a single node to limit control-plane
overhead. It does not provide high availability or bound total host RAM. Before creating
it, check `free -h` and `docker stats --no-stream`. Free capacity by scheduling inactive
workloads through their owning configuration; keep the existing Argo CD cluster running.
Do not turn on all release files merely because namespace quotas exist.

#### 1. Create and inspect the dedicated cluster

Run from the reviewed `platform-infrastructure` main revision. Docker must be available,
port 16443 must be free, and `kind`, `kubectl`, Python and Helm must be installed.
The pinned node image reuses the known Kubernetes version; only the new node is created.
Kind may select the new context as current, so every operation below names its context.

```bash
free -h
docker stats --no-stream
kind get clusters
# Run once if narx-commerce does not already exist. No AWS service is contacted.
kind create cluster --name narx-commerce --config local/kind.yaml --wait 120s
kubectl --context kind-narx-commerce get nodes -o wide
kubectl --context kind-narx-commerce get storageclass
python3 local/bootstrap.py prepare --context kind-narx-commerce --environment dev
python3 local/bootstrap.py prepare --context kind-narx-commerce --environment qa
python3 local/bootstrap.py prepare --context kind-narx-commerce --environment production
```

The API host port listens only on loopback. Both local clusters use Docker's kind
network, allowing Argo CD to reach `https://narx-commerce-control-plane:6443` by
stable container DNS rather than the laptop's changing LAN IP. Independent clusters
can use overlapping pod/service CIDRs here because only their API endpoints are crossed.
This arrangement is for one host; it is not routing between production VPCs.

Kind's default kindnet does **not** enforce Kubernetes NetworkPolicies. Install and
verify an enforcing CNI before treating the policy YAML as a security boundary or
activating untrusted workloads. Cluster separation alone does not isolate Docker hosts.
`local/kind.yaml` deliberately describes the current bootstrap capability rather than
claiming a CNI installation it does not perform.

#### 2. Install platform prerequisites on the remote cluster

The shared Argo CD workload credential cannot create CRDs or ClusterRoles. Install
Rollouts CRDs as an operator before deploying QA/production. The release manifest is
checksum-locked in the GitOps repository; do not install its cluster-wide controller
because the application chart owns namespace-scoped controllers.

```bash
python3 -m pip install PyYAML==6.0.3
curl --fail --silent --show-error --location \
  https://github.com/argoproj/argo-rollouts/releases/download/v1.10.1/install.yaml \
  --output /tmp/narx-rollouts-install.yaml
printf '%s  %s\n' \
  149148429a6f8258b789003ffb9bc6698a526d611ecb1b185624217cf51bae7f \
  /tmp/narx-rollouts-install.yaml | sha256sum --check --strict
python3 - <<'PYTHON' | kubectl --context kind-narx-commerce apply --server-side -f -
import json, yaml
with open('/tmp/narx-rollouts-install.yaml') as source:
    resources = [doc for doc in yaml.safe_load_all(source)
                 if doc and doc.get('kind') == 'CustomResourceDefinition']
assert resources, 'No CRDs in the verified release'
print(json.dumps({'apiVersion':'v1','kind':'List','items':resources}))
PYTHON
kubectl --context kind-narx-commerce get crd rollouts.argoproj.io analysisruns.argoproj.io
```

An enforcing CNI, metrics-server for any enabled HPAs, and independently owned monitoring
are remaining platform activation tasks. The configuration above does not install them.

#### 3. Register only Narx workload namespaces in shared Argo CD

```bash
python3 local/bootstrap.py register-cluster \
  --context kind-narx-commerce --management-context kind-mega-local
# Check the remote identity has only the intended namespace access.
kubectl --context kind-narx-commerce auth can-i create deployments \
  -n commerce-dev --as system:serviceaccount:narx-system:argocd-manager
kubectl --context kind-narx-commerce auth can-i create clusterroles \
  --as system:serviceaccount:narx-system:argocd-manager
kubectl --context kind-narx-commerce auth can-i get secrets -n kube-system \
  --as system:serviceaccount:narx-system:argocd-manager
# Expected: yes, no, no. Confirm existing Applications still have no app pods/PVCs
# before retargeting; if data appeared meanwhile, stop and plan its migration.
kubectl --context kind-mega-local -n commerce-dev get pods,pvc
kubectl --context kind-mega-local -n commerce-qa get pods,pvc
kubectl --context kind-mega-local apply --server-side \
  --field-manager=narx-platform-bootstrap \
  -f ../platform-gitops/applications/local/commerce.json
kubectl --context kind-mega-local -n argocd get applicationsets,applications
```

The helper creates a dedicated service account in `narx-system`, and an administrative
Role/RoleBinding in each of the three **Narx workload namespaces only**. Its namespace
permissions include secrets and namespaced RBAC, as needed by an Argo namespace manager;
it cannot administer other namespaces or cluster-scoped resources. AppProject policy is
an additional control: it allows only the Narx repository, three explicit destinations
and the chart's permitted resource kinds. It does not grant Kubernetes permissions.

For this non-cloud cluster, Argo authenticates with a manually provisioned service-account
token. Kubernetes stores the token in the Narx cluster; the helper transfers it directly
in memory to the shared Argo cluster Secret via stdin, with CA validation enabled.
No token, kubeconfig private key or generated password is committed or printed. This
persistent credential is a lab choice, not a short-lived cloud workload identity. Limit
access to the shared `argocd` namespace. To rotate it, delete only
`narx-system/argocd-manager-token` on the Narx cluster and rerun registration immediately.
That briefly interrupts reconciliation and must be done in an operations window.

Registration is project-scoped and sets `clusterResources=false` plus the exact namespace
list. The helper refuses the Boutique cluster as a workload target or the same cluster
as both target and manager. It does not change the AppProject/ApplicationSet itself.
The separate platform/monitoring application will require reviewed platform credentials;
never widen this workload token to cluster-admin to work around a missing CRD.

Applications are bounded to a fixed dev/QA/production list. Resource preservation and
`applicationsSync=create-update` prevent an ApplicationSet list edit from silently
cascading application deletion. The release bundle remains non-deployable until real
verified images are published. Do not claim a working deployment from an empty sync.
If shared Argo CD is down, existing Narx pods continue running, but reconciliation,
GitHub deployment evidence and Argo notifications pause.

#### 4. Configure independent Narx notification credentials

Create a Narx webhook in the chosen Slack workspace/channel and place it in a private
file outside every repository, with mode 600. Do not reuse or extract Boutique's Secret.
The helper reads the provided file and merges only Narx notification settings into the
shared Argo CD. It sends no manual test message. A conflicting global webhook service
needs review; it will not be silently replaced.

```bash
python3 local/bootstrap.py configure-delivery-notifications --context kind-mega-local \
  --notifications-file ../platform-gitops/applications/notifications.json \
  --slack-webhook-file /secure/path/narx-slack-webhook
python3 local/bootstrap.py configure-observer --context kind-mega-local \
  --app-id 123456 --installation-id 12345678 \
  --private-key-file /secure/path/narx-deployments.pem \
  --notifications-file ../platform-gitops/applications/notifications.json
```

Use actual numeric Narx App identifiers. These are examples, not installed identities.
The observer App needs only commit-status publishing permissions on Narx GitOps.
The release App separately needs Contents and Pull requests write. Keys must be supplied
privately before delivery can be enabled; no Bootstrap command invents these credentials.

## Local monitoring and progressive delivery

Dev uses ordinary Deployments. QA and local production use frontend blue-green Rollouts
with pre/post functional analysis. Backends use ordinary rolling updates. Failed preview
analysis keeps the existing frontend active; failed post-switch analysis restores stable
traffic. A reviewed Git rollback proposal separately restores desired Git state.
Database migrations, refunds and orders are never reversed by image rollback.

`monitoring/local-values.yaml` contains the Narx-specific metrics, dashboards and alert
rules from the earlier integration. They are still attached to Boutique's shared stack
in the current live installation. The target is an independent Narx monitoring stack,
including its own storage, Grafana credentials, Alertmanager routes and logging. Its
chart ownership and remote-cluster deployment are pending; the workload registration
above intentionally cannot install cluster-scoped monitoring resources.

Do not apply the old Boutique multi-source monitoring Application as a Narx bootstrap
step. After independent Narx monitoring is healthy, remove only its earlier integration
from the Boutique monitoring desired state through that repository's own reviewed PR.
Keep Boutique monitoring, data and workloads. Before deleting old Narx namespaces,
recheck resources and agree retention if any data appeared since this migration audit.

### Inspect deployments, alerts and logs

```bash
# Workload commands target the separate Narx cluster.
kubectl --context kind-narx-commerce -n commerce-qa get rollouts,analysisruns,jobs,pods
kubectl --context kind-narx-commerce -n commerce-qa describe rollout commerce-frontend
kubectl --context kind-narx-commerce -n commerce-qa get service commerce-frontend commerce-frontend-preview -o yaml
kubectl --context kind-narx-commerce -n commerce-qa logs deployment/narx-rollouts --tail=100
# Argo CD resources stay on the management cluster.
kubectl --context kind-mega-local -n argocd get applications
# After real delivery, forward just the environment you are using.
kubectl --context kind-narx-commerce -n commerce-dev port-forward service/commerce-frontend 18080:80
# QA: namespace commerce-qa, local port 18081. Production: commerce-production, 18082.
```

Use loopback port-forwards and SSH forwarding for headless previews. The local profile
uses HTTP and `cookieSecure=false`; this is a lab access choice, not production TLS.
HTTPS/ingress setup remains a later explicit platform task. A local production namespace
teaches promotion/approvals and recovery; its single laptop/node is not highly available.

Existing monitoring queries use `project="narx-commerce"` to avoid mixing projects.
The new stack must preserve that identity and include production in namespace discovery.
Prometheus verifies operational health; functional Analysis Jobs remain the frontend
rollout gates. Real paid checkout/provider sandbox and firing/resolved Slack delivery
still need separate live verification after credentials and publishing are configured.

The disposable Rollouts fixture can be run against the dedicated cluster after CRDs
are installed. It uses a throwaway namespace and a local fixture image, not a release:

```bash
cd ../platform-gitops
helm dependency build --skip-refresh charts/commerce
NARX_ROLLOUT_TEST=1 NARX_KUBE_CONTEXT=kind-narx-commerce \
  python3 -m unittest discover -s tests -p test_rollout_local.py -v
```

### Session stop and restart

`kind delete cluster` destroys the node and its local-path database volumes; it is not
pause/resume. Retain a verified backup before deleting a cluster with real data. To
pause only Narx without deleting its volumes, `docker stop narx-commerce-control-plane`;
to resume, `docker start narx-commerce-control-plane`, then verify node readiness, Argo
reconciliation and application health. Argo will report the cluster unreachable while
stopped. Keep the shared Argo host cluster running for other projects.


## Order events, receipts and queue recovery

Payment confirmation remains synchronous. A verified provider capture, checked by
checkout verification or a signed webhook, updates the order to paid/confirmed and
inserts `order_outbox` in the **same PostgreSQL transaction**. A browser redirect alone
never confirms payment. The queue is not called in that transaction, so a queue outage
delays receipt generation while payment confirmation continues.

```mermaid
flowchart LR
    P[Verified captured payment] --> T[One database transaction]
    T --> O[Paid order and outbox event]
    O --> B[Outbox publisher]
    B --> Q[Order-paid queue]
    Q --> W[Receipt worker]
    W --> R[Receipt and inbox marker in one transaction]
    R --> D[Delete queue message after commit]
    Q -->|Five failed receives| X[Dead-letter queue]
```

The event contains `eventId`, `type=order.paid`, `version=1`, `orderId`, `amount`,
`currency=INR` and `paymentId`. It contains no customer name, address, email, card,
password or session token. `V5__order_delivery.sql` creates the outbox, inbox and
receipt tables. Existing paid orders are not backfilled; newly confirmed captures
create events. Payment/webhook retries do not create a second event for an order.

The worker creates an internal payment acknowledgement in `payment_receipts`, not
a tax invoice, email, shipment or fulfilment transition. Authenticated order detail
includes a `receipt` field when ready; it is null beforehand. The existing storefront
does not yet render that field. A later refund retains the original receipt as a
historical payment acknowledgement; refund status remains on the order.

| Process | Responsibility | Queue outage behaviour |
| --- | --- | --- |
| `api` (default) | Payment/order transaction and outbox insert | API stays ready if its database is ready |
| `publisher` | Send one due event, then mark published | Retry with exponential delay, capped at 60 seconds; never discard unsent events |
| `worker` | Validate event, create receipt and inbox marker, then delete message | Failed messages become visible again; queue redrives after five failed receives |

Publisher replicas select rows with `SKIP LOCKED`. Each send has a bounded SDK timeout;
a row lock is held during that send. This simple approach suits current throughput.
Higher-volume production systems should evaluate batches or a lease-based publisher
rather than holding database connections during remote sends. A crash after send but
before marking published can send the same event again. That is expected.

The worker validates the message against the canonical outbox event. Inbox uniqueness
and receipt creation commit together, so a crash after commit but before SQS deletion
causes a harmless duplicate. A database failure rolls both writes back. The receipt's
unique order/event constraints add another guard. This guarantee covers these database
writes; external email/shipping calls would need their own idempotency mechanism.

Default message visibility is 60 seconds. Processing uses a 10-second database
transaction timeout; the worker receives one message per poll and only acknowledges
after commit. `DELIVERY_VISIBILITY_SECONDS` must be at least 15 and at most 43200;
15 is used only to shorten the local retry exercise. Production should retain an
appropriate margin and add visibility extension before introducing slower work.

The local Compose stack uses ElasticMQ 1.7.1 pinned by digest. Its H2 queue storage
survives container restarts in `queue-data`; PostgreSQL survives in `database`.
A one-shot init service gives the queue volume to UID 10001; the queue itself runs
non-root. Neither SQS nor database ports are published. An explicit `DELIVERY_LOCAL=true`
permits dummy credentials only against the local endpoint. Without that flag, the
SDK uses its default credential chain and requires an HTTPS queue URL. EKS Pod Identity
and narrowly scoped queue IAM permissions still need provisioning and verification.

All three Java roles expose `/health/live`, `/health/ready` and `/actuator/prometheus`.
Background-role readiness checks the database and queue; liveness does not require
either dependency. Use those custom health paths in Helm. Worker/publisher HTTP ports
must remain internal and should not receive storefront traffic.

Publisher metrics include `commerce_outbox_pending`, `commerce_outbox_oldest_seconds`
and `commerce_outbox_publish_total{result="sent|failed"}`. Worker metrics include
`commerce_queue_consume_total{result="processed|duplicate|failed"}` and
`commerce_queue_poll_total{result="failed"}`. Outbox gauges refresh every 30 seconds.
Logs correlate event/order IDs without logging message bodies or credentials.
Prometheus alert rules, DLQ-depth and queue-age alarms, and dashboards are still pending.
An empty poll is normal; repeated processing failures or growing backlog need attention.

### Local failure exercise

Use a fresh disposable Compose project. This exercise stops/restarts only that project's
queue and worker, creates test accounts/orders and injects temporary database constraints.
It requires the queue-aware GitOps branch and the matching orders image. It is intentionally
separate from the ordinary customer-flow test; never run it on a shared database.

```bash
# From platform-gitops, after building the four application images.
DELIVERY_VISIBILITY_SECONDS=15 docker compose --project-name narx-events-validation \
  --env-file local/.env -f local/compose.yaml up --no-build -d --wait
NARX_LOCAL_TEST=1 NARX_QUEUE_TEST=1 NARX_COMPOSE_PROJECT=narx-events-validation \
  python3 -m unittest discover -s tests -p test_local_stack.py -v
# Remove this disposable exercise's database AND queue data when finished.
docker compose --project-name narx-events-validation --env-file local/.env \
  -f local/compose.yaml down --volumes
```

The test proves atomic payment/outbox rollback, payment success during a queue outage,
publication after recovery, duplicate publisher replay, atomic consumer rollback,
visibility retry, poison-message DLQ redrive and corrected replay without duplicate
receipts. It also retains the existing customer/admin/refund checks. ElasticMQ implements
a subset of SQS: these checks do not prove AWS IAM, encryption, retention or real-provider
behaviour. AWS integration tests remain required before cloud rollout.

### Recovery decisions

1. If outbox backlog grows, inspect publisher health/logs and queue reachability/permissions.
   Restore the dependency; due events retry automatically. Do not delete pending rows.
2. If receipts lag but outbox is clear, inspect the worker, queue age and DLQ.
   A worker restart recovers unacknowledged messages after the visibility timeout.
3. Inspect a DLQ message and its event ID under restricted operator access. Fix its schema,
   application or data failure first. Replay only trusted events, preserving `eventId`.
   Copy successfully before removing the DLQ message; retain operational evidence.
   Native SQS redrive will be tested on AWS; the local test explicitly copies/deletes.
4. If a queue was irrecoverably lost, an operator can replay a reviewed outbox event by
   clearing `published_at` and setting `next_attempt_at=CURRENT_TIMESTAMP` for that exact
   event ID. Receipts already created remain deduplicated. Do not mass-reset the table.
5. If an exercise fails, inspect logs, then remove its disposable volumes to clear injected
   constraints and test state. Regular `down` preserves data and does not reset the exercise.

Outbox/inbox/receipt history is retained for now. A retention/archival policy must be agreed
before real production traffic; do not prune canonical events while replay is still possible.
Dev/QA Kubernetes deployments will use isolated queues/data. They are not deployed yet.

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
# When reviewing an unmerged change, check out the corresponding PR branches in all four repos.
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
NARX_LOCAL_TEST=1 NARX_COMPOSE_PROJECT=narx-commerce python3 -m unittest discover -s tests -p test_local_stack.py -v
docker compose --env-file local/.env -f local/compose.yaml down
# Only for intentionally discarding this local preview's database and queue data:
# docker compose --env-file local/.env -f local/compose.yaml down --volumes
```

The test mutates its named local stack. Do not point it at a shared or production
database. PostgreSQL and queue data survive ordinary `down`; carts and simulator records do
not. Stopping and restarting the payment simulator does not constitute a provider
recovery test and can leave its old local orders needing a fresh checkout.

Migration verification: all four runtime Docker builds passed their application tests.
The opt-in full-stack test passed against an isolated local project, including denied
guest checkout, required delivery, customer/admin separation, INR product data, stock
reservation, idempotent checkout, invalid payment signature rejection, payment retries,
order isolation, product version conflicts, fulfilment and refund retries. This evidence
does not cover the real payment provider, Kubernetes releases or AWS. The separate
queue exercise above covers local message processing and recovery.

## Infrastructure workflow (inactive legacy AWS scaffolding)

Do not apply this scaffolding for the local-only architecture. AWS work belongs to
the standalone commerce-aws project. These sections explain retained code only.

Infrastructure PRs run formatting, validation, provider-mocked tests and a blocking
HIGH/CRITICAL Terraform security scan for both bootstrap and delivery roots. AWS-backed
plan/apply/destroy workflows still require scoped identities and the cloud cost review.
No current workflow can apply infrastructure. The existing lab state bucket uses SSE-S3;
its customer-managed-KMS scanner finding has a narrowly scoped exception expiring
2027-01-20 and must be reviewed before production state activation.

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

## Commands for inactive AWS scaffolding (reference only)

Do not execute AWS provisioning commands for the local Narx migration. The active
local bootstrap commands are in Dedicated local cluster and shared Argo CD above.

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

1. Review and merge dedicated-cluster bootstrap and local Argo destination changes.
   Check laptop capacity before creating the node. Install an enforcing CNI and required
   CRDs, prepare the namespaces, register the restricted workload identity, and retarget
   only the empty Narx Applications. Keep Boutique workloads and shared Argo CD intact.
2. Merge the GHCR publisher first; pin callers and the GitOps builder allowlist to its
   final reviewed main SHA. Configure package access and separate Narx release/observer
   Apps, then enable delivery deliberately.
3. Publish all four real component images and exercise dev -> QA -> local production
   with the same digests. Verify failed preview/post-switch recovery and reviewed
   rollback. No fake or mutable image references may activate a release.
4. Deploy independently owned Narx Prometheus/Grafana/Alertmanager and logging with
   its own credentials and storage. Verify targets, dashboard access and notifications,
   then remove the old Narx integration from Boutique through a separate reviewed PR.
5. Complete operator access/TLS, local data backup/restore and runtime security checks.
   Verify checkout/provider sandbox, queue retries/DLQ and release recovery. Record
   current evidence and remaining single-node/laptop limitations in this guide.

AWS provisioning belongs to the separate `commerce-aws` project. The retained Terraform
roots and ECR explanations are historical inactive code, not local activation commands.

## References

- [GitHub branch-protection availability](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- [Terraform S3 state and native lockfile](https://developer.hashicorp.com/terraform/language/backend/s3)
- [Terraform provider mocks](https://developer.hashicorp.com/terraform/language/tests/mocking)
- [GitHub OIDC for AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)
- [EKS subnet requirements](https://docs.aws.amazon.com/eks/latest/userguide/network-reqs.html)
- [SQS delivery semantics](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues-at-least-once-delivery.html)

- [ElasticMQ configuration and delivery limits](https://github.com/softwaremill/elasticmq)
- [SQS visibility timeout](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-visibility-timeout.html)
- [AWS Java SDK default credential chain](https://docs.aws.amazon.com/sdk-for-java/latest/developer-guide/credentials-chain.html)

- [Argo CD GitHub deployment statuses](https://argo-cd.readthedocs.io/en/stable/operator-manual/notifications/services/github/)
- [ECR pricing](https://aws.amazon.com/ecr/pricing/)
- [Cosign container signing](https://docs.sigstore.dev/cosign/signing/signing_with_containers/)
