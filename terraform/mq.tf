resource "aws_mq_broker" "main" {
  broker_name        = "${local.name_prefix}-activemq"
  engine_type        = "ActiveMQ"
  engine_version     = "5.18"
  host_instance_type = "mq.t3.micro"
  deployment_mode    = "SINGLE_INSTANCE"   # use ACTIVE_STANDBY_MULTI_AZ for prod
  publicly_accessible = false

  subnet_ids         = [aws_subnet.private[0].id]
  security_groups    = [aws_security_group.mq.id]

  user {
    username = "admin"
    password = var.mq_password
  }

  # Note: Amazon MQ uses port 61614 (STOMP+TLS), not 61613.
  # Update MQ_PORT env var to 61614 and enable TLS in stomp.py.
}
