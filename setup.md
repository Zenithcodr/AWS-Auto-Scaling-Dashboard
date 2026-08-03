# Setup And Run Guide

Use this for a Canvas AWS Lab. The dashboard runs on your Mac. AWS only runs Terraform-created resources and the Ansible-configured workload.

## 1. Install Once

Open Docker Desktop, then install/check tools:

```bash
brew install terraform ansible awscli python
cd "/Users/shrey-mac/Downloads/Codes/Cloud&devops/aws-autoscaling-dashboard"
./scripts/check_devops_prereqs.sh
```

## 2. Start Canvas Lab

1. Start the Canvas AWS Lab.
2. Open AWS Console from Canvas.
3. Copy the temporary AWS credentials.
4. Use one region everywhere, for example `us-east-1`.

Do not create IAM users, roles, or policies.

## 3. Fill `lab.env`

Create the local lab file:

```bash
cd "/Users/shrey-mac/Downloads/Codes/Cloud&devops/aws-autoscaling-dashboard"
test -f lab.env || cp lab.env.example lab.env
chmod 600 lab.env
```

Edit `lab.env` and fill these values:

```bash
AWS_REGION="us-east-1"
AWS_DEFAULT_REGION="us-east-1"
AWS_ACCESS_KEY_ID="PASTE_CANVAS_ACCESS_KEY"
AWS_SECRET_ACCESS_KEY="PASTE_CANVAS_SECRET_KEY"
AWS_SESSION_TOKEN="PASTE_CANVAS_SESSION_TOKEN"
USE_IAM_ROLE="false"

LAB_REGION="us-east-1"
LAB_VPC_ID="vpc-xxxxxxxxxxxxxxxxx"
LAB_PUBLIC_SUBNET_IDS='["subnet-aaaaaaaaaaaaaaaaa","subnet-bbbbbbbbbbbbbbbbb"]'
LAB_AMI_ID="ami-xxxxxxxxxxxxxxxxx"
LAB_KEY_NAME="cloud-devops-lab-key"
LAB_PRIVATE_KEY_FILE="/path/to/cloud-devops-lab-key.pem"
LAB_SSH_CIDR="YOUR_PUBLIC_IP/32"
```

Where to get them:

- Canvas credentials: Canvas AWS details panel
- VPC/subnets: AWS Console `VPC`
- AMI ID: Amazon Linux 2023 AMI in EC2 launch screen, then cancel
- key pair: AWS Console `EC2 > Key Pairs`
- public IP: `curl -s https://checkip.amazonaws.com`

Then load and verify:

```bash
. ./scripts/load_lab_env.sh
aws sts get-caller-identity
```

## 4. Create AWS Resources With Terraform

```bash
cd "/Users/shrey-mac/Downloads/Codes/Cloud&devops/aws-autoscaling-dashboard"
. ./scripts/load_lab_env.sh
cd terraform
terraform init
terraform apply
terraform output
cd ..
```

When prompted, type `yes`.

Copy these Terraform outputs into `lab.env`:

```bash
AUTO_SCALING_GROUP_NAME="..."
LOAD_BALANCER_ARN="..."
TARGET_GROUP_ARN="..."
ALB_DNS_NAME="..."
```

Then sync dashboard config:

```bash
. ./scripts/load_lab_env.sh
./scripts/sync_dashboard_env.sh
```

Default scaling is custom app logic:

```bash
SCALING_MODE="custom"
SCALE_OUT_CPU_THRESHOLD="70"
SCALE_IN_CPU_THRESHOLD="30"
SCALER_COOLDOWN_SECONDS="60"
```

## 5. Configure EC2 Workload With Ansible

```bash
chmod 400 "${LAB_PRIVATE_KEY_FILE}"
./scripts/render_ansible_inventory.sh "${LAB_REGION}" cloud-devops-autoscaling ansible/inventory.generated.ini
ansible-playbook -i ansible/inventory.generated.ini ansible/playbook.yml
```

Wait until AWS Console `EC2 > Target Groups > Targets` shows healthy targets.

## 6. Run Dashboard Locally

```bash
./scripts/run_local_dashboard.sh
```

Open:

```text
http://127.0.0.1:5000
```

## 7. Generate Load Against AWS ALB

Do not load test localhost.

```bash
. ./scripts/load_lab_env.sh
./load_test.sh probe scaleout70
./load_test.sh start scaleout70
```

`scaleout70` is designed to push the workload above the custom controller's 70% CPU scale-out threshold.

Stop load:

```bash
./load_test.sh stop
```

## Later Runs

1. Start Canvas lab.
2. Paste fresh Canvas credentials into `lab.env`.
3. Run:

```bash
cd "/Users/shrey-mac/Downloads/Codes/Cloud&devops/aws-autoscaling-dashboard"
. ./scripts/load_lab_env.sh
aws sts get-caller-identity
./scripts/sync_dashboard_env.sh
./scripts/render_ansible_inventory.sh "${LAB_REGION}" cloud-devops-autoscaling ansible/inventory.generated.ini
ansible-playbook -i ansible/inventory.generated.ini ansible/playbook.yml
./scripts/run_local_dashboard.sh
```

If the lab was reset and resources are gone, rerun Terraform from step 4 and copy the new outputs into `lab.env`.

## Common Fixes

- `ExpiredToken`: paste fresh Canvas credentials into `lab.env`, then rerun `. ./scripts/load_lab_env.sh`.
- Ansible SSH fails: check `.pem` path, `chmod 400`, and `LAB_SSH_CIDR`.
- No metrics: check Terraform outputs in `lab.env`, then run `./scripts/sync_dashboard_env.sh`.
- Cleanup: use [end.md](/Users/shrey-mac/Downloads/Codes/Cloud&devops/aws-autoscaling-dashboard/end.md).
