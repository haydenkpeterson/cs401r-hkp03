# Downstream modules and environments/dev/main.tf consume these.

output "vpc_id" {
  description = "ID of the VPC"
  value       = aws_vpc.this.id
}

output "vpc_cidr" {
  description = "CIDR block of the VPC"
  value       = aws_vpc.this.cidr_block
}

output "public_subnet_id" {
  description = "ID of the public subnet"
  value       = aws_subnet.public.id
}

output "private_subnet_id" {
  description = "ID of the private subnet"
  value       = aws_subnet.private.id
}

output "nat_gateway_id" {
  description = "ID of the NAT Gateway, or null when enable_nat_gateway is false"
  value       = var.enable_nat_gateway ? aws_nat_gateway.this[0].id : null
}

output "internet_gateway_id" {
  description = "ID of the Internet Gateway attached to the VPC"
  value       = aws_internet_gateway.this.id
}

output "route_table_id" {
  description = "ID of the public route table"
  value       = aws_route_table.public.id
}

output "private_route_table_id" {
  description = "ID of the private route table"
  value       = aws_route_table.private.id
}

output "security_group_id" {
  description = "ID of the SageMaker security group"
  value       = aws_security_group.sagemaker.id
}
