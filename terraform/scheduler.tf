resource "aws_scheduler_schedule" "regression" {
  name = "${var.project_name}-regression"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression = "rate(7 days)"

  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = aws_iam_role.scheduler.arn

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.app.arn_without_revision
      launch_type         = "FARGATE"
      task_count          = 1

      network_configuration {
        subnets          = data.aws_subnets.default.ids
        security_groups  = [aws_security_group.app.id]
        assign_public_ip = true
      }
    }

    input = jsonencode({
      containerOverrides = [
        {
          name = var.project_name
          command = [
            "python",
            "-m",
            "eval.regression"
          ]
        }
      ]
    })
  }
}