terraform {
  required_version = "~> 1.16.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.69.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "narx-commerce"
      Environment = "bootstrap"
      Owner       = "platform-engineering"
      ManagedBy   = "terraform"
    }
  }
}
