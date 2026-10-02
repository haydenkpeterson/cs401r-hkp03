# ── modules/storage ──────────────────────────────────────────────────────────
# ONE data bucket, organised by stage with four top-level prefixes. The prefix
# split is what lets Lab 2 give DataEngineer raw/processed/features while the
# MLEngineer role stays confined to artifacts/ and features/.
#
# S3 bucket names are globally unique, so the account ID is appended. Against
# LocalStack this resolves to 000000000000, which is the name the Makefile's
# local-validate target looks for.

data "aws_caller_identity" "current" {}

locals {
  name_prefix = "${var.project}-${var.environment}"
  bucket_name = "${local.name_prefix}-data-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket" "data" {
  bucket = local.bucket_name

  # Lets terraform destroy delete a versioned bucket that still holds objects
  # and old versions. Right for synthetic, regenerable lab data; wrong for a
  # bucket of real customer records, because it deletes every version with no
  # confirmation. Off unless the environment turns it on.
  force_destroy = var.force_destroy

  tags = {
    Name = local.bucket_name
  }
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket = aws_s3_bucket.data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Versioning is how a bad transform is recovered from: overwriting a processed
# object keeps the previous version rather than destroying it.
resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# S3 has no real directories. An empty object with a trailing slash is how a
# prefix is made to exist before anything is written to it, so the four data
# stages are visible in the console from day one.
resource "aws_s3_object" "prefixes" {
  for_each = toset(var.prefixes)

  bucket = aws_s3_bucket.data.id
  key    = each.value

  # Applied before the public access block lands, an ACL-bearing object can be
  # rejected; depending on the block keeps the ordering deterministic.
  depends_on = [aws_s3_bucket_public_access_block.data]
}

# Retention per prefix. raw/ is a landing zone: once processed/ holds the
# cleaned copy, a raw file has no reason to outlive 90 days. The noncurrent
# rules cap how long versioning keeps overwritten objects around, with
# features/ held longer because a model may need to be traced back to the
# exact feature set it trained on.
#
# datacapture/ has no writer until Lab 5's endpoint data capture, which emits
# one object per interval for as long as an endpoint is up. Retention is set
# now so it exists before the writer does.
resource "aws_s3_bucket_lifecycle_configuration" "data" {
  count  = var.enable_lifecycle_rules ? 1 : 0
  bucket = aws_s3_bucket.data.id

  rule {
    id     = "expire-raw-data"
    status = "Enabled"
    filter {
      prefix = "raw/"
    }
    expiration {
      days = 90
    }
  }

  rule {
    id     = "expire-raw-versions"
    status = "Enabled"
    filter {
      prefix = "raw/"
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  rule {
    id     = "expire-processed-versions"
    status = "Enabled"
    filter {
      prefix = "processed/"
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  rule {
    id     = "expire-feature-versions"
    status = "Enabled"
    filter {
      prefix = "features/"
    }
    noncurrent_version_expiration {
      noncurrent_days = 60
    }
  }

  rule {
    id     = "expire-datacapture"
    status = "Enabled"
    filter {
      prefix = "datacapture/"
    }
    expiration {
      days = 7
    }
  }

  # Noncurrent-version rules mean nothing until versioning is on.
  depends_on = [aws_s3_bucket_versioning.data]
}
