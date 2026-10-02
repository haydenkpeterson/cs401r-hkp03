# ── modules/vpc ──────────────────────────────────────────────────────────────
# The network boundary for the NorthStar platform. Lab 1 built a single public
# subnet in one AZ. Lab 2 adds a private subnet for SageMaker and the Glue
# workers, with a NAT Gateway in the public subnet carrying their outbound
# traffic. Nothing on the internet can open a connection into the private
# subnet.
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

# ── Private tier (Lab 2) ─────────────────────────────────────────────────────

resource "aws_subnet" "private" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = var.private_subnet_cidr
  availability_zone       = var.availability_zone
  map_public_ip_on_launch = false

  tags = {
    Name = "${local.name_prefix}-private-1"
    Tier = "private"
  }
}

# The NAT Gateway bills by the hour whether or not traffic flows through it,
# so it is optional. LocalStack sets enable_nat_gateway = false; there it
# would only be an emulated resource with nothing behind it.
resource "aws_eip" "nat" {
  count  = var.enable_nat_gateway ? 1 : 0
  domain = "vpc"

  tags = {
    Name = "${local.name_prefix}-eip"
  }
}

resource "aws_nat_gateway" "this" {
  count         = var.enable_nat_gateway ? 1 : 0
  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public.id

  tags = {
    Name = "${local.name_prefix}-nat"
  }

  # A NAT Gateway in a subnet whose VPC has no Internet Gateway yet comes up
  # with no path out.
  depends_on = [aws_internet_gateway.this]
}

# Default route goes to the NAT Gateway, not the Internet Gateway: outbound
# only. With NAT disabled the table has local routes only.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id

  dynamic "route" {
    for_each = var.enable_nat_gateway ? [1] : []
    content {
      cidr_block     = "0.0.0.0/0"
      nat_gateway_id = aws_nat_gateway.this[0].id
    }
  }

  tags = {
    Name = "${local.name_prefix}-private-rt"
  }
}

resource "aws_route_table_association" "private" {
  subnet_id      = aws_subnet.private.id
  route_table_id = aws_route_table.private.id
}

# Inbound is restricted to the VPC CIDR — nothing from the internet may open a
# connection to Studio. Outbound is open so Studio can pull container images
# and reach S3; from the private subnet that egress leaves via the NAT Gateway.
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
