resource "aws_ecs_cluster" "main" {
  name = "${local.name_prefix}-cluster"
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "listener"  { name = "/ecs/${local.name_prefix}/listener";  retention_in_days = 30 }
resource "aws_cloudwatch_log_group" "dashboard" { name = "/ecs/${local.name_prefix}/dashboard"; retention_in_days = 30 }
resource "aws_cloudwatch_log_group" "train"     { name = "/ecs/${local.name_prefix}/train";     retention_in_days = 30 }
resource "aws_cloudwatch_log_group" "scraper"   { name = "/ecs/${local.name_prefix}/scraper";   retention_in_days = 30 }

locals {
  common_env = [
    { name = "DB_HOST",    value = aws_db_instance.sqlserver.address },
    { name = "DB_NAME",    value = "GAS_MODEL" },
    { name = "MQ_HOST",    value = tolist(aws_mq_broker.main.instances)[0].endpoints[0] },
    { name = "MQ_PORT",    value = "61614" },
    { name = "MQ_USER",    value = "admin" },
    { name = "MODELS_DIR", value = "s3://${aws_s3_bucket.models.bucket}/models" },
    { name = "LOG_DIR",    value = "/tmp/logs" },
  ]
  common_secrets = [
    { name = "DB_PASS", valueFrom = aws_secretsmanager_secret.db_password.arn },
    { name = "MQ_PASS", valueFrom = aws_secretsmanager_secret.mq_password.arn },
  ]
  image_model   = "${aws_ecr_repository.gas_model.repository_url}:${var.gas_model_image_tag}"
  image_scraper = "${aws_ecr_repository.gas_scraper.repository_url}:${var.gas_scraper_image_tag}"
}

resource "aws_ecs_task_definition" "listener" {
  family                   = "${local.name_prefix}-listener"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name        = "listener"
    image       = local.image_model
    command     = ["python", "listener.py"]
    essential   = true
    environment = local.common_env
    secrets     = local.common_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.listener.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "ecs"
      }
    }
  }])
}

resource "aws_ecs_task_definition" "dashboard" {
  family                   = "${local.name_prefix}-dashboard"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name         = "dashboard"
    image        = local.image_model
    command      = ["python", "dashboard/app.py"]
    essential    = true
    portMappings = [{ containerPort = 8050, protocol = "tcp" }]
    environment  = local.common_env
    secrets      = local.common_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.dashboard.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "ecs"
      }
    }
  }])
}

resource "aws_ecs_task_definition" "train" {
  family                   = "${local.name_prefix}-train"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "1024"
  memory                   = "2048"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name        = "train"
    image       = local.image_model
    command     = ["python", "train.py"]
    essential   = true
    environment = local.common_env
    secrets     = local.common_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.train.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "ecs"
      }
    }
  }])
}

resource "aws_ecs_task_definition" "scraper" {
  family                   = "${local.name_prefix}-scraper"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "scraper"
    image     = local.image_scraper
    command   = ["python", "main.py"]
    essential = true
    environment = concat(local.common_env, [
      { name = "MQ_QUEUE_NATIONAL", value = "/queue/gas.national" },
      { name = "MQ_QUEUE_ENTSOG",   value = "/queue/gas.entsog"   },
      { name = "MQ_QUEUE_WEATHER",  value = "/queue/gas.weather"  },
    ])
    secrets = local.common_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.scraper.name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "ecs"
      }
    }
  }])
}

resource "aws_ecs_service" "listener" {
  name            = "${local.name_prefix}-listener"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.listener.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false
  }
}

resource "aws_lb" "dashboard" {
  name               = "${local.name_prefix}-alb"
  internal           = false
  load_balancer_type = "application"
  subnets            = aws_subnet.public[*].id
  security_groups    = [aws_security_group.alb.id]
}

resource "aws_lb_target_group" "dashboard" {
  name        = "${local.name_prefix}-dashboard"
  port        = 8050
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    path                = "/"
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "dashboard" {
  load_balancer_arn = aws_lb.dashboard.arn
  port              = 8050
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.dashboard.arn
  }
}

resource "aws_ecs_service" "dashboard" {
  name            = "${local.name_prefix}-dashboard"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.dashboard.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.dashboard.arn
    container_name   = "dashboard"
    container_port   = 8050
  }

  depends_on = [aws_lb_listener.dashboard]
}
