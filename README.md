# AWS Auto-Scaling Dashboard

A local **Flask** dashboard that monitors and controls an **AWS Auto Scaling Group (ASG)**
in real time. You run the dashboard on your own machine; the actual EC2 instances,
load balancer, and scaling group live in AWS and are created by **Terraform**.

The dashboard reads live CPU / traffic metrics from AWS and, when CPU crosses your
thresholds, tells the Auto Scaling Group to **add or remove EC2 instances automatically**.

---

## 1. What is actually happening (read this first)

This project is **not** the "click Launch Instance in the console and SSH in" workflow.
You never create instances by hand here. Instead:

```
YOUR COMPUTER (local)                         AWS ACCOUNT (remote)
──────────────────────                        ─────────────────────────────────────
 Flask Dashboard  ── boto3 (AWS SDK) ─────►   Auto Scaling Group (ASG)
 (this repo)          reads metrics             │  desired = N
   │                  sends scale commands       ├── EC2 instance 1  ┐
   │                                             ├── EC2 instance 2  ├─ created & destroyed
   ▼                                             └── EC2 instance N  ┘   AUTOMATICALLY
 http://127.0.0.1:5000                          │
 (charts, instance list,                   Application Load Balancer (ALB)
  scale up / down buttons)                  one public URL, spreads traffic
```

The three moving parts:

| Layer | Tool | Role |
|-------|------|------|
| **Infrastructure** | Terraform (`terraform/`) | Creates the ALB, Launch Template, Auto Scaling Group and security groups in your AWS account. This is what replaces "manually launching instances". |
| **Configuration** | Ansible (`ansible/`) | SSHes into the instances and installs the CPU-heavy demo workload that sits behind the load balancer. |
| **Monitoring & Control** | Flask + boto3 (this app) | Runs locally. Reads CloudWatch CPU metrics and instance health, then calls the ASG's `SetDesiredCapacity` API to scale out (add instances) or scale in (remove them). |

### How scaling actually works
- The **Auto Scaling Group** is told a `desired_capacity` (e.g. 2). AWS then guarantees
  exactly that many healthy instances exist, launching or terminating them from the
  **Launch Template** blueprint as needed.
- The dashboard's controller watches average CPU:
  - CPU above **70%** → it raises desired capacity (scale **out**).
  - CPU below **30%** → it lowers desired capacity (scale **in**).
- The **Application Load Balancer** gives you a single URL and distributes requests
  across however many instances currently exist.

So: **Terraform builds the group, the group builds the instances, the dashboard decides how many.**

---

## 2. Repository layout

```
app.py                  Flask entrypoint (routes + API)
aws_client.py           All boto3 calls to EC2 / CloudWatch / AutoScaling / ELB
config.py               Loads settings from .env
monitor.py              Collects a "snapshot" of AWS metrics
scaler.py               The scaling decision logic (the custom controller)
metrics_logger.py       Writes metrics/events to ./data (CSV + SQLite)
templates/ , static/    Dashboard web UI
terraform/              Infrastructure as Code: ALB + ASG + Launch Template + SGs
ansible/                Configures the workload on the instances
scripts/                Helper shell scripts (Mac/Linux)
tests/                  pytest tests
.env.example            Template for local configuration (copy to .env)
```

---

## 3. Prerequisites

**To just run the dashboard UI locally:**
- [Python 3.10+](https://www.python.org/downloads/) (on Windows, the `py` launcher is installed with it)

**To run the full project against real AWS, also install:**

| Tool | Why you need it | Install |
|------|-----------------|---------|
| AWS account + credentials | boto3/Terraform authenticate as you | [Create account](https://aws.amazon.com/) |
| [Terraform](https://developer.hashicorp.com/terraform/install) | Builds the ALB, ASG, launch template | `winget install Hashicorp.Terraform` (Windows) / `brew install terraform` (Mac) |
| [Ansible](https://docs.ansible.com/ansible/latest/installation_guide/intro_installation.html) | Configures the workload on the instances | `pip install ansible` (needs WSL/Linux/Mac; not native Windows) |
| [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) | Optional — verify credentials with `aws sts get-caller-identity` | `winget install Amazon.AWSCLI` / `brew install awscli` |

> **Windows tip:** the dashboard itself runs natively on Windows. Terraform and the
> AWS CLI have native Windows builds, but **Ansible does not run natively on Windows** —
> use **WSL2** (Ubuntu), Git Bash, or a Mac/Linux machine for the Ansible step.

> **Security note:** `.env`, `lab.env`, `*.pem` keys and Terraform state are git-ignored
> and are **never** committed. Only the `.env.example` / `lab.env.example` templates
> (placeholders only) are in the repo.

---

## 4. Quick start — run the dashboard locally

You can start the dashboard on its own to see the UI. Without valid AWS
credentials it will load, but the AWS data panels will show errors until you
configure a real account (Section 5).

### Windows (PowerShell)

```powershell
# from the project folder
py -3.10 -m venv .venv-win
.\.venv-win\Scripts\python.exe -m pip install -r requirements.txt

# create your local config from the template
Copy-Item .env.example .env

# start it
.\.venv-win\Scripts\python.exe app.py
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
python app.py
```

Then open: **http://127.0.0.1:5000**

Health check: **http://127.0.0.1:5000/healthz** should return `{"status":"ok",...}`.

### What you'll see on the dashboard

| Page / URL | What it does |
|------------|--------------|
| `/` | Main dashboard: live CPU chart, instance list, ASG desired/min/max, recent scaling events |
| `/control` | Manual control panel: buttons to force scale-out / scale-in and set desired capacity |
| `/healthz` | JSON health check (used by the AWS load balancer too) |

### HTTP API (used by the UI, also callable directly)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/metrics` | GET | Full snapshot: CPU, instances, ASG state, controller decision, history, events. `?refresh=true` forces a fresh AWS read |
| `/api/instances` | GET | Current EC2 instances + ASG summary |
| `/api/history` | GET | Recent metric history (`?limit=` up to 500) |
| `/api/events` | GET | Recent scaling events (`?limit=` up to 200) |
| `/api/control` | GET/POST | Read controller state, or POST an action (scale out/in, set capacity). Requires `X-Control-Token` header if `CONTROL_API_TOKEN` is set |
| `/api/download-metrics` | GET | Download the collected `metrics.csv` |

---

## 5. Connecting it to a real AWS account (full setup)

This is what makes the dashboard show live instances and actually scale them.

### Step 1 — Put your AWS credentials in `.env`
Open `.env` and fill in real values:

```env
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=<your access key>
AWS_SECRET_ACCESS_KEY=<your secret key>
AWS_SESSION_TOKEN=<only if using temporary/lab credentials>
USE_IAM_ROLE=false
```

`boto3` uses these to authenticate as you against your AWS account.

### Step 2 — Create the AWS infrastructure with Terraform
Terraform needs a few inputs about your account. Provide them in a
`terraform/terraform.tfvars` file (or you'll be prompted). The required ones:

| Variable | Required | Example | What it is |
|----------|----------|---------|------------|
| `vpc_id` | yes | `vpc-0abc123` | The VPC to launch into |
| `public_subnet_ids` | yes | `["subnet-aaa","subnet-bbb"]` | Two public subnets for the ALB + ASG |
| `ami_id` | yes | `ami-0abc123` | Amazon Linux 2023 AMI in your region |
| `key_name` | yes | `my-lab-key` | Existing EC2 key pair (Ansible SSHes with it) |
| `ssh_allowed_cidr_blocks` | yes | `["1.2.3.4/32"]` | Your public IP, so only you can SSH |
| `aws_region` | no (default `us-east-1`) | `us-east-1` | Region |
| `instance_type` | no (default `t3.micro`) | `t3.micro` | Instance size |
| `min_size` / `max_size` / `desired_capacity` | no (`1`/`4`/`1`) | – | ASG bounds |

See `terraform/variables.tf` for the full list and `terraform/README.md`.

```bash
cd terraform
terraform init
terraform apply     # review the plan, then type "yes"
terraform output    # note the ASG name, ALB ARN, target group ARN
```

This creates, in your account:
- an Application Load Balancer,
- a Launch Template,
- an Auto Scaling Group (min 1 / max 4 by default),
- the required security groups.

### Step 3 — Feed Terraform's outputs back into `.env`
Copy the values from `terraform output` into `.env`:

```env
AUTO_SCALING_GROUP_NAME=<from terraform output>
LOAD_BALANCER_ARN=<from terraform output>
TARGET_GROUP_ARN=<from terraform output>
```

The dashboard needs the ASG name so it knows which group to monitor and scale.

### Step 4 — Configure the workload with Ansible
Ansible SSHes into the new instances and installs the demo CPU workload:

```bash
ansible-playbook -i ansible/inventory.generated.ini ansible/playbook.yml
```

(The `scripts/render_ansible_inventory.sh` helper can generate the inventory from
the running ASG. See `ansible/README.md`.)

### Step 5 — Restart the dashboard
Restart `app.py`. It will now show real instances, live CPU charts, ALB target
health, and the scale-out / scale-in controls will act on your real ASG.

---

## 6. Seeing it scale (load test)

Generate traffic against the **AWS load balancer** (never against localhost) to push
CPU past the 70% threshold and watch the ASG add instances:

```bash
./load_test.sh probe scaleout70
./load_test.sh start scaleout70
# ...watch the dashboard add instances...
./load_test.sh stop
```

`scaleout70` is a demo profile tuned to cross the scale-out threshold.

---

## 7. Configuration reference

All behavior is controlled through environment variables in `.env`
(defaults live in `config.py`). Key ones:

| Variable | Default | Meaning |
|----------|---------|---------|
| `APP_HOST` / `APP_PORT` | `127.0.0.1` / `5000` | Where the dashboard listens |
| `AWS_REGION` | `us-east-1` | AWS region to query |
| `AUTO_SCALING_GROUP_NAME` | – | Which ASG to monitor/scale (from Terraform) |
| `SCALING_MODE` | `custom` | `custom` = this app decides; `aws_managed` = AWS policies decide |
| `SCALE_OUT_CPU_THRESHOLD` | `70` | CPU % that triggers adding instances |
| `SCALE_IN_CPU_THRESHOLD` | `30` | CPU % that triggers removing instances |
| `SCALER_MIN_INSTANCES` / `SCALER_MAX_INSTANCES` | `1` / `4` | Controller soft limits |
| `SCALER_COOLDOWN_SECONDS` | `60` | Wait between scaling actions |
| `CONTROL_API_TOKEN` | – | If set, control actions require this token |

---

## 8. Running the tests

```bash
# Windows
.\.venv-win\Scripts\python.exe -m pytest

# macOS / Linux
python -m pytest
```

---

## 9. Shutting everything down

Stop the local dashboard with `Ctrl+C`. To tear down the AWS resources (so you
stop paying for them):

```bash
cd terraform
terraform destroy
```

---

## 10. Troubleshooting

| Symptom | Cause & fix |
|---------|-------------|
| Dashboard loads but panels show "AWS credentials were not found" | `.env` still has placeholder keys. Paste real credentials and restart. |
| "AWS API call failed" / `AccessDenied` | Credentials are valid but lack permissions, or the ASG name in `.env` is wrong. Check `AUTO_SCALING_GROUP_NAME`. |
| Auth errors appear after a while (lab credentials) | Temporary/session credentials expired. Refresh `AWS_SESSION_TOKEN` in `.env` and restart. |
| `py -3.10` not found (Windows) | Python 3.10 isn't installed; install it, or use `py -3` / `python`. |
| `RuntimeError: Dashboard runtime policy is local_only` | You're running it inside AWS. This app is meant to run locally; run it on your own machine. |
| Port 5000 already in use | Change `APP_PORT` in `.env`, or stop the other process. |
| Ansible step fails on Windows | Ansible has no native Windows build — run that step from WSL2, Git Bash, or Mac/Linux. |

---

## 11. Notes & safety

- The dashboard is meant to run **locally**, not on an AWS instance. A runtime
  guard (`runtime_guard.py`) blocks it from starting if it detects it is running
  inside AWS.
- Never commit real credentials. `.env`, `lab.env`, `*.pem`, and Terraform state
  are already in `.gitignore`.
- If you use temporary "lab" credentials, they expire — refresh them in `.env`
  and restart the dashboard when AWS calls start failing with auth errors.
