resource "aws_ssm_parameter" "anthropic_key" {
  name  = "/${var.project_name}/anthropic-api-key"
  type  = "SecureString"
  value = "placeholder"

  lifecycle {
    ignore_changes = [value]
  }

  tags = {
    Project = var.project_name
  }
}

resource "aws_ssm_parameter" "otel_config" {
  name  = "/${var.project_name}/otel-collector-config"
  type  = "String"
  value = file("${path.module}/../otel-collector-config.yaml")

  tags = {
    Project = var.project_name
  }
}