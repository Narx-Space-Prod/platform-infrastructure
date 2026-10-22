mock_provider "aws" {}

variables {
  aws_region        = "ap-south-1"
  state_bucket_name = "narx-commerce-state-test"
}

run "state_storage_security" {
  command = apply

  assert {
    condition     = aws_s3_bucket.state.force_destroy == false
    error_message = "State storage must not delete objects during teardown."
  }

  assert {
    condition     = aws_s3_bucket_versioning.state.versioning_configuration[0].status == "Enabled"
    error_message = "State storage requires versioning for recovery."
  }

  assert {
    condition = (
      aws_s3_bucket_public_access_block.state.block_public_acls &&
      aws_s3_bucket_public_access_block.state.block_public_policy &&
      aws_s3_bucket_public_access_block.state.ignore_public_acls &&
      aws_s3_bucket_public_access_block.state.restrict_public_buckets
    )
    error_message = "All four public access protections must be enabled."
  }

  assert {
    condition     = aws_s3_bucket_ownership_controls.state.rule[0].object_ownership == "BucketOwnerEnforced"
    error_message = "Object ACLs must be disabled."
  }

  assert {
    condition     = one(aws_s3_bucket_server_side_encryption_configuration.state.rule).apply_server_side_encryption_by_default[0].sse_algorithm == "AES256"
    error_message = "State objects must be encrypted at rest."
  }

  assert {
    condition = (
      jsondecode(aws_s3_bucket_policy.state.policy).Statement[0].Effect == "Deny" &&
      jsondecode(aws_s3_bucket_policy.state.policy).Statement[0].Condition.Bool["aws:SecureTransport"] == "false"
    )
    error_message = "State storage must reject unencrypted HTTP requests."
  }
}

run "reject_unsafe_bucket_names" {
  command = plan

  variables {
    state_bucket_name = "Not_A_Valid_Bucket"
  }

  expect_failures = [var.state_bucket_name]
}
