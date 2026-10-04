data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${var.project_name}-execution-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json

  tags = {
    Project = var.project_name
  }
}

resource "aws_iam_role" "task" {
  name               = "${var.project_name}-task-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json

  tags = {
    Project = var.project_name
  }
}

data "aws_iam_policy_document" "ssm_read" {
  statement {
    actions = [
      "ssm:GetParameters"
    ]

    resources = [
      "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project_name}/*"
    ]
  }
}

resource "aws_iam_role_policy" "execution_ssm" {
  name   = "${var.project_name}-execution-ssm"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.ssm_read.json
}

resource "aws_iam_role_policy" "task_ssm" {
  name   = "${var.project_name}-task-ssm"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.ssm_read.json
}

data "aws_iam_policy_document" "dynamodb" {
  statement {
    actions = [
      "dynamodb:PutItem",
      "dynamodb:GetItem"
    ]

    resources = [
      aws_dynamodb_table.incidents.arn
    ]
  }
}

resource "aws_iam_role_policy" "task_dynamodb" {
  name   = "${var.project_name}-dynamodb"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.dynamodb.json
}

resource "aws_iam_role_policy_attachment" "execution_ecs" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy_attachment" "task_xray" {
  role       = aws_iam_role.task.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

resource "aws_iam_role_policy_attachment" "task_cloudwatch" {
  role       = aws_iam_role.task.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

data "aws_iam_policy_document" "github_deploy_smoke_test" {
  statement {
    sid = "DiscoverRunningTask"

    actions = [
      "ecs:ListTasks",
      "ecs:DescribeTasks",
      "ec2:DescribeNetworkInterfaces",
    ]

    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "github_deploy_smoke_test" {
  name   = "${var.project_name}-github-deploy-smoke-test"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy_smoke_test.json
}

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.project_name}-scheduler-role"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json

  tags = {
    Project = var.project_name
  }
}

data "aws_iam_policy_document" "scheduler_run_task" {
  statement {
    sid = "RunRegressionTask"

    actions = [
      "ecs:RunTask"
    ]

    resources = [
      "arn:aws:ecs:${var.region}:${data.aws_caller_identity.current.account_id}:task-definition/${var.project_name}:*"
    ]

    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.main.arn]
    }
  }

  statement {
    sid = "PassECSTaskRoles"

    actions = [
      "iam:PassRole"
    ]

    resources = [
      aws_iam_role.execution.arn,
      aws_iam_role.task.arn,
    ]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "scheduler_run_task" {
  name   = "${var.project_name}-scheduler-run-task"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler_run_task.json
}