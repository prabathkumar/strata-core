# ==============================================================================
# STRATA INFRASTRUCTURE SPECIFICATION: deploy/cluster.tf
# Declarative Cloud Architecture Infrastructure Configuration
# Provisoning Secure, High-Performance Production Tiers Automatically
# ==============================================================================

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

# 1. Network Perimeter Layer: Isolate Strata Concurrency Clusters
resource "aws_security_group" "strata_security_perimeter" {
  name        = "strata-cluster-sg"
  description = "Enforce type-safe network boundary security gates for Strata event fibers"

  # High-Volume Asynchronous Stream Ingestion Socket Port
  ingress {
    description = "Native Stream Ingestion Endpoint Socket"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# 2. Server Compute Layer: Bare-Metal Execution Target optimized for Wasm/AOT
resource "aws_instance" "strata_node_prime" {
  ami           = "ami-0c7217cdde317cfec" # Hardened Ubuntu Server LTS
  instance_type = "c6i.xlarge"            # Compute-Optimized architecture matching high-scale matrix multipliers

  security_groups = [aws_security_group.strata_security_perimeter.name]

  # Automated Instance Configuration Pipeline script
  user_data = <<-EOF
              #!/bin/bash
              echo "[Cloud Setup]: Spinning up target environment container..."
              apt-get update && apt-get install -y docker.io
              
              # Clone the official core tech stack repository directly
              git clone https://github.com /app
              cd /app
              
              # Automatically orchestrate the multi-stage compiler execution image
              docker build -t strata-service .
              docker run -d -p 8080:8080 --name running-node strata-service
              EOF

  tags = {
    Name        = "Strata-Enterprise-Production-Prime"
    Environment = "Production"
    Engine      = "v1.0.0"
  }
}

output "production_cluster_endpoint" {
  value       = aws_instance.strata_node_prime.public_ip
  description = "The public ip gateway hosting your high-scale Strata Virtual Fibers."
}
