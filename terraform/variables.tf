variable "region" {
  description = "AWS region used for RCA Copilot infrastructure"
  type        = string
  default     = "ap-south-1"
}

variable "project_name" {
  description = "Base name used for RCA Copilot AWS resources"
  type        = string
  default     = "rca-copilot"
}

variable "image_tag" {
  description = "Docker image tag deployed to ECS"
  type        = string
}