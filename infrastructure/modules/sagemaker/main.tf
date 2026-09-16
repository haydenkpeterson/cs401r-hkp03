# ── modules/sagemaker ────────────────────────────────────────────────────────
# Studio is the IDE for every ML task in this platform. In Lab 1 the Domain
# sits in the public subnet for simplicity; Lab 2 moves it behind a NAT
# Gateway in a private subnet.
#
# A brand-new AWS account has no AWSServiceRoleForAmazonSageMakerNotebooks
# service-linked role and the Domain create fails with a service-linked role
# error. Create it once in the console and re-apply — a one-time account
# bootstrap, not a code error.

locals {
  name_prefix = "${var.project}-${var.environment}"
}

resource "aws_sagemaker_domain" "this" {
  domain_name = "${local.name_prefix}-domain"
  auth_mode   = "IAM"
  vpc_id      = var.vpc_id
  subnet_ids  = var.subnet_ids

  # Stated explicitly rather than left to the provider default. In Lab 1
  # Studio sits in a public subnet with no NAT, so egress goes out over the
  # SageMaker-managed network path. Lab 2 flips this to VpcOnly once a NAT
  # Gateway exists to carry the traffic.
  app_network_access_type = var.app_network_access_type

  # Studio creates an EFS filesystem for home directories that Terraform never
  # sees. Left at the default (Retain) it survives DeleteDomain, its mount
  # target pins the subnet, and terraform destroy hangs on the subnet and
  # security group. Nothing of value lives in a Studio home directory here.
  retention_policy {
    home_efs_file_system = "Delete"
  }

  default_user_settings {
    execution_role  = var.execution_role_arn
    security_groups = var.security_group_ids

    sharing_settings {
      notebook_output_option = "Disabled"
    }

    kernel_gateway_app_settings {
      default_resource_spec {
        instance_type = var.instance_type
      }
    }
  }

  tags = {
    Name = "${local.name_prefix}-domain"
  }
}

resource "aws_sagemaker_user_profile" "this" {
  domain_id         = aws_sagemaker_domain.this.id
  user_profile_name = var.user_profile_name

  user_settings {
    execution_role  = var.execution_role_arn
    security_groups = var.security_group_ids
  }

  tags = {
    Name = var.user_profile_name
  }
}
