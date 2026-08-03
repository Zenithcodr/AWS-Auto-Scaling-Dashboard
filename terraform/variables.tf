variable "aws_region" {
  description = "AWS region for the Auto Scaling demo resources."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Name prefix for all resources created by this stack."
  type        = string
  default     = "cloud-devops-autoscaling"
}

variable "vpc_id" {
  description = "VPC ID where the ALB and Auto Scaling Group will run."
  type        = string
}

variable "public_subnet_ids" {
  description = "At least two public subnet IDs for the internet-facing ALB and ASG."
  type        = list(string)
}

variable "ami_id" {
  description = "Amazon Linux 2023 AMI ID for the demo workload instances."
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type for the demo workload."
  type        = string
  default     = "t3.micro"
}

variable "key_name" {
  description = "EC2 key pair name required for the mandatory Ansible workload configuration step."
  type        = string

  validation {
    condition     = length(trimspace(var.key_name)) > 0
    error_message = "key_name is required because Ansible must SSH into the workload instances."
  }
}

variable "ssh_allowed_cidr_blocks" {
  description = "CIDR blocks allowed to SSH to workload instances for the required Ansible step. Prefer your current public IP as x.x.x.x/32."
  type        = list(string)
}

variable "app_port" {
  description = "Port exposed by the Flask demo workload on each EC2 instance."
  type        = number
  default     = 5000
}

variable "desired_capacity" {
  description = "Initial desired capacity for the Auto Scaling Group."
  type        = number
  default     = 1
}

variable "min_size" {
  description = "Minimum Auto Scaling Group size."
  type        = number
  default     = 1
}

variable "max_size" {
  description = "Maximum Auto Scaling Group size."
  type        = number
  default     = 4
}

variable "asg_default_cooldown" {
  description = "ASG cooldown used by the custom dashboard controller."
  type        = number
  default     = 60
}

variable "health_check_grace_period" {
  description = "Seconds to wait before ELB health checks affect new ASG instances."
  type        = number
  default     = 120
}

variable "enable_detailed_monitoring" {
  description = "Enable 1-minute EC2 metrics so the custom controller can react faster."
  type        = bool
  default     = true
}
