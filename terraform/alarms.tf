resource "aws_sns_topic" "alerts" {
  name = "${var.project_name}-alerts"

  tags = {
    Project = var.project_name
  }
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "provider_unavailable" {
  alarm_name        = "${var.project_name}-provider-unavailable"
  alarm_description = "RCA request exhausted provider retries and ended with provider_unavailable."

  namespace   = "RCACopilot"
  metric_name = "api_requests_total"

  dimensions = {
    OTelLib = "rca_copilot"
    outcome = "provider_unavailable"
  }

  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  datapoints_to_alarm = 1

  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"

  treat_missing_data = "notBreaching"

  alarm_actions = [
    aws_sns_topic.alerts.arn
  ]

  tags = {
    Project = var.project_name
  }
}

resource "aws_cloudwatch_metric_alarm" "cost_ceiling" {
  alarm_name        = "${var.project_name}-cost-ceiling"
  alarm_description = "RCA request reached the configured token/cost ceiling."

  namespace   = "RCACopilot"
  metric_name = "api_requests_total"

  dimensions = {
    OTelLib = "rca_copilot"
    outcome = "cost_ceiling"
  }

  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  datapoints_to_alarm = 1

  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"

  treat_missing_data = "notBreaching"

  alarm_actions = [
    aws_sns_topic.alerts.arn
  ]

  tags = {
    Project = var.project_name
  }
}

resource "aws_cloudwatch_metric_alarm" "tool_failures" {
  alarm_name        = "${var.project_name}-tool-failures"
  alarm_description = "One or more RCA telemetry tools failed during incident investigation."

  namespace   = "RCACopilot"
  metric_name = "tool_failures_total"

  dimensions = {
    OTelLib = "rca_copilot"
  }

  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  datapoints_to_alarm = 1

  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"

  treat_missing_data = "notBreaching"

  alarm_actions = [
    aws_sns_topic.alerts.arn
  ]

  tags = {
    Project = var.project_name
  }
}

resource "aws_cloudwatch_metric_alarm" "regression_failed" {
  alarm_name        = "${var.project_name}-regression-failed"
  alarm_description = "Scheduled RCA baseline regression gate failed."

  namespace   = "RCACopilot"
  metric_name = "regression_runs_total"

  dimensions = {
    OTelLib = "rca_copilot"
    outcome = "fail"
  }

  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  datapoints_to_alarm = 1

  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"

  treat_missing_data = "notBreaching"

  alarm_actions = [
    aws_sns_topic.alerts.arn
  ]

  tags = {
    Project = var.project_name
  }
}