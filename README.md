# platform-infrastructure

Owner: Platform engineering.

AWS infrastructure and its plan/apply/destroy workflows. Secure state-storage bootstrap, ECR/OIDC delivery identity preparation, provider-mocked tests and explicit local bootstrap tools. VPC, EKS, RDS, SQS and live plan/apply/destroy follow the cost review.

Project guide: [DOC.md](https://github.com/Narx-Space-Prod/platform-infrastructure/blob/main/DOC.md).
The guide distinguishes implemented code from activated infrastructure and live verification.

## Current state

AWS publishing is disabled. No cloud resources or new Argo applications have been provisioned.
All changes after repository initialization go through feature branches and pull requests.
These repositories are public on GitHub Free. Protected `main` requires a CODEOWNER
approval, passing CI checks and resolved conversations; administrators follow the same rules.
