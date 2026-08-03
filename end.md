# Shutdown Guide

Use this every time you finish. Do not end the Canvas lab until Terraform cleanup is done.

## 1. Stop Local Processes

```bash
cd "/Users/shrey-mac/Downloads/Codes/Cloud&devops/aws-autoscaling-dashboard"
./load_test.sh stop
docker compose down --remove-orphans
```

## 2. Refresh Credentials

If Canvas credentials expired, paste fresh values into `lab.env`.

```bash
. ./scripts/load_lab_env.sh
aws sts get-caller-identity
```

Do not continue until this works.

## 3. Destroy AWS Resources

```bash
cd terraform
terraform init
terraform destroy
cd ..
```

When prompted, type `yes`.

## 4. Verify AWS Is Empty

Check AWS Console in the same region:

- `EC2 > Instances`: no project instances running/stopped
- `EC2 > Auto Scaling Groups`: no project ASG
- `EC2 > Load Balancers`: no project ALB
- `EC2 > Target Groups`: no project target group
- `EC2 > Launch Templates`: no project launch template
- `EC2 > Security Groups`: no project security groups

Then stop/end the Canvas lab.

## If Terraform Destroy Fails

Use AWS Console cleanup in this order:

1. Delete Auto Scaling Group.
2. Wait for instances to terminate.
3. Delete Load Balancer.
4. Delete Target Group.
5. Delete Launch Template.
6. Delete project Security Groups.

Do not terminate instances before deleting the ASG, or it may recreate them.
