output "rds_endpoint" {
  description = "RDS SQL Server endpoint — set as DB_HOST env var"
  value       = aws_db_instance.sqlserver.address
}

output "mq_endpoint" {
  description = "Amazon MQ STOMP+TLS endpoint — set as MQ_HOST env var (port 61614)"
  value       = tolist(aws_mq_broker.main.instances)[0].endpoints[0]
}

output "dashboard_url" {
  description = "Gas demand dashboard"
  value       = "http://${aws_lb.dashboard.dns_name}:8050"
}

output "models_bucket" {
  description = "S3 bucket for model .pkl files — set as MODELS_DIR=s3://bucket/models"
  value       = "s3://${aws_s3_bucket.models.bucket}/models"
}

output "ecr_gas_model" {
  description = "ECR URI for gas-model image"
  value       = aws_ecr_repository.gas_model.repository_url
}

output "ecr_gas_scraper" {
  description = "ECR URI for gas-scraper image"
  value       = aws_ecr_repository.gas_scraper.repository_url
}
