resource "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"

  client_id_list = [
    "sts.amazonaws.com"
  ]

  tags = {
    Project = var.project_name
  }
}

data "aws_iam_policy_document" "github_deploy_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type = "Federated"

      identifiers = [
        aws_iam_openid_connect_provider.github.arn
      ]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"

      values = [
        "sts.amazonaws.com"
      ]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"

      values = [
        "repo:RudraMoharana-99/rca-copilot:environment:production"
      ]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name = "${var.project_name}-github-deploy-role"

  assume_role_policy = data.aws_iam_policy_document.github_deploy_trust.json

  tags = {
    Project = var.project_name
  }
}

data "aws_iam_policy_document" "github_deploy_ecr" {
  statement {
    sid = "ECRLogin"

    actions = [
      "ecr:GetAuthorizationToken"
    ]

    resources = ["*"]
  }

  statement {
    sid = "ECRPush"

    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
      "ecr:BatchGetImage"
    ]

    resources = [
      aws_ecr_repository.app.arn
    ]
  }
}

resource "aws_iam_role_policy" "github_deploy_ecr" {
  name   = "${var.project_name}-github-deploy-ecr"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy_ecr.json
}

data "aws_iam_policy_document" "github_deploy_ecs" {
  statement {
    sid = "RegisterTaskDefinition"

    actions = [
      "ecs:RegisterTaskDefinition",
      "ecs:DescribeTaskDefinition"
    ]

    resources = ["*"]
  }

  statement {
    sid = "DeployService"

    actions = [
      "ecs:UpdateService",
      "ecs:DescribeServices"
    ]

    resources = [
      aws_ecs_service.app.id
    ]
  }
}

resource "aws_iam_role_policy" "github_deploy_ecs" {
  name   = "${var.project_name}-github-deploy-ecs"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy_ecs.json
}

data "aws_iam_policy_document" "github_deploy_passrole" {
  statement {
    sid = "PassECSTaskRoles"

    actions = [
      "iam:PassRole"
    ]

    resources = [
      aws_iam_role.task.arn,
      aws_iam_role.execution.arn
    ]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"

      values = [
        "ecs-tasks.amazonaws.com"
      ]
    }
  }
}

resource "aws_iam_role_policy" "github_deploy_passrole" {
  name   = "${var.project_name}-github-deploy-passrole"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy_passrole.json
}