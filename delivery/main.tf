terraform {
  required_version = "~> 1.16.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.69.0"
    }
  }
}

# Preparation only. No backend, plan or apply is activated until the AWS review.
provider "aws" {
  region              = var.region
  allowed_account_ids = [var.account_id]
  default_tags {
    tags = { Project = "narx-commerce", ManagedBy = "terraform" }
  }
}

variable "account_id" {
  type        = string
  description = "Reviewed AWS account. Never infer this from a developer's default credentials."
  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "Provide a 12-digit AWS account ID."
  }
}
variable "region" {
  type        = string
  description = "Reviewed AWS region."
}
variable "existing_github_oidc_provider_arn" {
  type        = string
  default     = null
  description = "Reuse the account's existing GitHub OIDC provider when one exists."
}

locals {
  registry_repositories = toset(["frontend", "catalogue", "orders", "cart"])
  callers = {
    commerce-frontend  = ["frontend"]
    commerce-catalogue = ["catalogue"]
    commerce-orders    = ["orders", "cart"]
  }
  provider_arn = coalesce(var.existing_github_oidc_provider_arn, try(aws_iam_openid_connect_provider.github[0].arn, null))
  read_actions = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability", "ecr:DescribeImages"]
}

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.existing_github_oidc_provider_arn == null ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

resource "aws_ecr_repository" "service" {
  for_each             = local.registry_repositories
  name                 = "narx/commerce-${each.key}"
  force_delete         = false
  image_tag_mutability = "IMMUTABLE"
  # Cosign v3 uses OCI 1.1 referrers; no mutable signature tags are required.
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "AES256"
  }
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "untagged" {
  for_each   = aws_ecr_repository.service
  repository = each.value.name
  # Do not delete tagged releases automatically: a promoted/rollback digest may be old.
  policy = jsonencode({ rules = [{
    rulePriority = 1
    description  = "Expire only untagged images after 14 days"
    selection    = { tagStatus = "untagged", countType = "sinceImagePushed", countUnit = "days", countNumber = 14 }
    action       = { type = "expire" }
  }] })
}

resource "aws_iam_role" "publisher" {
  for_each             = local.callers
  name                 = "narx-${each.key}-publisher"
  max_session_duration = 3600
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Action = "sts:AssumeRoleWithWebIdentity"
    Principal = { Federated = local.provider_arn }
    Condition = { StringEquals = {
      "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
      "token.actions.githubusercontent.com:sub" = "repo:Narx-Space-Prod/${each.key}:environment:registry-release"
    } }
  }] })
}

resource "aws_iam_role_policy" "publisher" {
  for_each = local.callers
  role     = aws_iam_role.publisher[each.key].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
    { Effect = "Allow", Resource = [for name in each.value : aws_ecr_repository.service[name].arn], Action = concat(local.read_actions,
    ["ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage"]) }
  ] })
}

resource "aws_iam_role" "verification" {
  name = "narx-gitops-registry-verification"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Action = "sts:AssumeRoleWithWebIdentity"
    Principal = { Federated = local.provider_arn }
    Condition = { StringEquals = {
      "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
      "token.actions.githubusercontent.com:sub" = "repo:Narx-Space-Prod/platform-gitops:environment:registry-verification"
    } }
  }] })
}
resource "aws_iam_role_policy" "verification" {
  role = aws_iam_role.verification.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
    { Effect = "Allow", Action = local.read_actions, Resource = [for repository in aws_ecr_repository.service : repository.arn] }
  ] })
}

output "repositories" {
  value = { for name, repository in aws_ecr_repository.service : name => repository.repository_url }
}
output "publisher_roles" {
  value = { for name, role in aws_iam_role.publisher : name => role.arn }
}
output "verification_role" {
  value = aws_iam_role.verification.arn
}
