output "auto_scaling_group_name" {
  description = "Name to place in AUTO_SCALING_GROUP_NAME."
  value       = aws_autoscaling_group.app.name
}

output "load_balancer_arn" {
  description = "ARN to place in LOAD_BALANCER_ARN."
  value       = aws_lb.app.arn
}

output "target_group_arn" {
  description = "ARN to place in TARGET_GROUP_ARN."
  value       = aws_lb_target_group.app.arn
}

output "alb_dns_name" {
  description = "Public DNS name for browser and load-test traffic."
  value       = aws_lb.app.dns_name
}

output "app_security_group_id" {
  description = "Security group used by ASG instances and Ansible SSH access."
  value       = aws_security_group.app.id
}

output "ansible_discovery_command" {
  description = "Command to generate an Ansible inventory from running Terraform-created instances."
  value       = "../scripts/render_ansible_inventory.sh ${var.aws_region} ${var.project_name} ../ansible/inventory.generated.ini"
}
