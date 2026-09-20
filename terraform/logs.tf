resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${var.project_name}"
  retention_in_days = 7

  tags = {
    Project = var.project_name
  }
}

resource "aws_cloudwatch_log_group" "metrics" {
  name              = "/ecs/${var.project_name}-metrics"
  retention_in_days = 7

  tags = {
    Project = var.project_name
  }
}