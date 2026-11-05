# platform-infrastructure

Owner: Platform engineering.

Local Narx cluster bootstrap, shared Argo CD integration and retained inactive AWS scaffolding. Private GHCR pull credentials, restricted Argo registration and provider-mocked checks for retained inactive Terraform roots. VPC, EKS, RDS, SQS and live plan/apply/destroy follow the cost review.

Project guide: [DOC.md](https://github.com/Narx-Space-Prod/platform-infrastructure/blob/main/DOC.md).
The guide distinguishes implemented code from activated infrastructure and live verification.

## Current state

The dedicated local cluster is active. Dev, QA and production use the same verified
private image bundle; all three are Synced/Healthy and their real smoke hooks passed.
GitHub deployment-success statuses and dedicated Slack sends were verified. Independent
monitoring, metrics/HPA and failure-recovery exercises remain unfinished. See DOC.md.
All changes after repository initialization go through feature branches and pull requests.
These repositories are public on GitHub Free. Protected `main` requires a CODEOWNER
approval, passing CI checks and resolved conversations; administrators follow the same rules.

Private cluster pulls use the independent ghcr-pull Secret created by local/bootstrap.py
refresh-registry from a mode-600 read:packages token file outside the repository. CI
publishes with ephemeral GITHUB_TOKEN credentials; no AWS login or publishing PAT is
needed. See DOC.md for App separation, package read grants and activation order.

Independent monitoring bootstrap (render-only by default): `python3 local/observability.py --context kind-narx-commerce --integration-values ../platform-gitops/monitoring/local-values.yaml`. See DOC.md for reviewed installation, capacity limits, credentials, verification and retained resources.
