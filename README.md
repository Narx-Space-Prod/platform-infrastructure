# platform-infrastructure

Owner: Platform engineering.

Local Narx cluster bootstrap, shared Argo CD integration and retained inactive AWS scaffolding. Secure state-storage bootstrap, ECR/OIDC delivery identity preparation, provider-mocked tests and explicit local bootstrap tools. VPC, EKS, RDS, SQS and live plan/apply/destroy follow the cost review.

Project guide: [DOC.md](https://github.com/Narx-Space-Prod/platform-infrastructure/blob/main/DOC.md).
The guide distinguishes implemented code from activated infrastructure and live verification.

## Current state

Delivery remains disabled. Existing local dev/QA Argo Applications are empty bootstrap releases.
The dedicated Narx cluster and local production destination are prepared for reviewed operator activation;
merging does not create a cluster. See DOC.md for remaining GHCR and monitoring migration work.
All changes after repository initialization go through feature branches and pull requests.
These repositories are public on GitHub Free. Protected `main` requires a CODEOWNER
approval, passing CI checks and resolved conversations; administrators follow the same rules.
