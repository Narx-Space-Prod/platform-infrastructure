mock_provider "aws" {}
variables {
  account_id                        = "123456789012"
  region                            = "us-east-1"
  existing_github_oidc_provider_arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
}
override_resource {
  target          = aws_ecr_repository.service["frontend"]
  values          = { arn = "arn:aws:ecr:us-east-1:123456789012:repository/narx/commerce-frontend" }
  override_during = plan
}
override_resource {
  target          = aws_ecr_repository.service["catalogue"]
  values          = { arn = "arn:aws:ecr:us-east-1:123456789012:repository/narx/commerce-catalogue" }
  override_during = plan
}
override_resource {
  target          = aws_ecr_repository.service["orders"]
  values          = { arn = "arn:aws:ecr:us-east-1:123456789012:repository/narx/commerce-orders" }
  override_during = plan
}
override_resource {
  target          = aws_ecr_repository.service["cart"]
  values          = { arn = "arn:aws:ecr:us-east-1:123456789012:repository/narx/commerce-cart" }
  override_during = plan
}
run "registry_and_identity_controls" {
  command = plan
  assert {
    condition     = length(aws_ecr_repository.service) == 4 && alltrue([for r in aws_ecr_repository.service : r.image_tag_mutability == "IMMUTABLE" && !r.force_delete])
    error_message = "Four protected repositories with immutable commit tags are required."
  }
  assert {
    condition     = alltrue([for r in aws_iam_role.publisher : strcontains(r.assume_role_policy, "environment:registry-release") && strcontains(r.assume_role_policy, "sts.amazonaws.com")])
    error_message = "Publishing roles must require the protected registry environment and correct audience."
  }
  assert {
    condition     = !strcontains(aws_iam_role_policy.verification.policy, "ecr:PutImage") && !strcontains(aws_iam_role_policy.verification.policy, "ecr:Delete") && !strcontains(aws_iam_role_policy.verification.policy, "iam:")
    error_message = "Verification must not mutate images or IAM."
  }
  assert {
    condition     = alltrue([for policy in aws_ecr_lifecycle_policy.untagged : jsondecode(policy.policy).rules[0].selection.tagStatus == "untagged"])
    error_message = "Lifecycle cleanup must not delete tagged deployment or rollback releases."
  }
}
