# Terraform Infrastructure Provisioning

This directory codifies the AWS resources described in the presentation deck:

- Application Load Balancer
- Target Group
- Launch Template for workload target instances
- Auto Scaling Group
- detailed EC2 monitoring for 1-minute custom-controller CPU signals
- Security groups for ALB-to-workload traffic and Ansible SSH access

Terraform is mandatory for the full project workflow. It provisions AWS infrastructure only. It does not run or deploy the monitoring dashboard, and it does not create an AWS-managed scaling policy. The local dashboard's custom controller submits scaling decisions to the ASG.

The stack is intentionally parameterized so it can be used with a lab VPC and subnet IDs instead of creating an entire network by default. It also requires an EC2 key pair and SSH CIDR so Ansible can connect to workload instances. The dashboard remains on your Mac and talks to these resources through AWS APIs.

## Example

```bash
cd terraform
terraform init
terraform plan
```

Run `. ./scripts/load_lab_env.sh` from the project root first so Terraform receives `TF_VAR_*` values from `lab.env`. Use `terraform apply` when the plan looks correct.

After apply, copy these outputs into `lab.env`:

- `auto_scaling_group_name`
- `load_balancer_arn`
- `target_group_arn`
- `alb_dns_name`

Use `alb_dns_name` for browser checks and `load_test.sh`.

Then generate the mandatory Ansible inventory:

```bash
../scripts/render_ansible_inventory.sh us-east-1 cloud-devops-autoscaling ../ansible/inventory.generated.ini
```
