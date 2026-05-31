variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "eu-west-2"   # London — closest to UK gas data sources
}

variable "environment" {
  description = "Environment name (dev / prod)"
  type        = string
  default     = "dev"
}

variable "db_password" {
  description = "RDS SQL Server SA password — store in Secrets Manager, never commit"
  type        = string
  sensitive   = true
}

variable "mq_password" {
  description = "Amazon MQ admin password"
  type        = string
  sensitive   = true
}

variable "gas_model_image_tag" {
  description = "Docker image tag for gas-model (pushed to ECR)"
  type        = string
  default     = "latest"
}

variable "gas_scraper_image_tag" {
  description = "Docker image tag for gas-scraper (pushed to ECR)"
  type        = string
  default     = "latest"
}
