resource "aws_db_subnet_group" "main" {
  name       = "${local.name_prefix}-db-subnet"
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_instance" "sqlserver" {
  identifier             = "${local.name_prefix}-sqlserver"
  engine                 = "sqlserver-ex"   # Express edition — included licence, 10 GB
  engine_version         = "15.00"
  instance_class         = "db.t3.small"
  allocated_storage      = 20
  storage_encrypted      = true
  username               = "sa"
  password               = var.db_password
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  skip_final_snapshot    = var.environment != "prod"
  multi_az               = var.environment == "prod"
  backup_retention_period = 7
  deletion_protection    = var.environment == "prod"

  # SQL Server Express does not use a parameter group or option group
  license_model = "license-included"

  tags = { Name = "${local.name_prefix}-sqlserver" }
}
