# ── modules/vpc ──────────────────────────────────────────────────────────────
# The network boundary for the NorthStar platform. Lab 1 is a single public
# subnet in one AZ; Lab 2 adds private subnets and a NAT Gateway alongside
# these resources.
#
# Every name is derived from var.project and var.environment so the same module
# builds the dev stack on AWS and the local stack on LocalStack.

locals {
  name_prefix = "${var.project}-${var.environment}"
}

resource "aws_vpc" "this" {
  cidr_block = var.vpc_cidr

  # Studio resolves S3 and ECR endpoints by name, so both must be on.
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${local.name_prefix}-vpc"
  }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = var.public_subnet_cidr
  availability_zone       = var.availability_zone
  map_public_ip_on_launch = true

  tags = {
    Name = "${local.name_prefix}-public-1"
    Tier = "public"
  }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name = "${local.name_prefix}-igw"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = {
    Name = "${local.name_prefix}-public-rt"
  }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# Inbound is restricted to the VPC CIDR — nothing from the internet may open a
# connection to Studio. Outbound is open so Studio can pull container images
# and reach S3 through the Internet Gateway.
resource "aws_security_group" "sagemaker" {
  name        = "${local.name_prefix}-sagemaker-sg"
  description = "SageMaker Studio: intra-VPC inbound only, unrestricted egress"
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "All traffic from within the VPC"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    description = "All outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${local.name_prefix}-sagemaker-sg"
  }
}
