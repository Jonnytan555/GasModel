resource "aws_scheduler_schedule" "scraper_hourly" {
  name       = "${local.name_prefix}-scraper-hourly"
  group_name = "default"

  flexible_time_window { mode = "OFF" }

  schedule_expression = "cron(0 * * * ? *)"   # every hour on the hour

  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = aws_iam_role.scheduler.arn

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.scraper.arn
      launch_type         = "FARGATE"

      network_configuration {
        assign_public_ip = false
        subnets          = aws_subnet.private[*].id
        security_groups  = [aws_security_group.ecs.id]
      }
    }
  }
}
