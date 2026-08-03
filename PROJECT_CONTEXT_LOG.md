# Project Context Log

Created: 2026-04-26

Purpose: persistent project memory for Codex and future maintenance. Before making changes or running project actions, read this file first, then verify anything that may have changed from the live files.

Suggested first command in future prompts:

```bash
sed -n '1,260p' PROJECT_CONTEXT_LOG.md
```

After meaningful project changes, append an entry under "Update Log" and adjust any stale sections.

## Project Summary

This is an AWS Auto-Scaling Infrastructure Monitoring and Control Dashboard.

It is a local-Mac Flask dashboard that:

- Reads real AWS EC2, CloudWatch, Auto Scaling Group, and Application Load Balancer data through boto3 from the user's Mac.
- Shows a custom HTML/CSS/JS dashboard with Chart.js charts.
- Logs metric snapshots to CSV and SQLite.
- Logs controller and AWS scaling events.
- Provides a control page to update controller settings and optionally submit scaling actions.
- Requires Terraform, Ansible, Docker, Docker Compose, pytest, and GitHub Actions CI as the Cloud + DevOps toolchain.
- Must not be deployed as the monitoring dashboard on AWS resources. AWS hosts only Terraform-created infrastructure plus the Ansible-configured workload target service.

## Repository State

- Root path: `/Users/shrey-mac/Downloads/Codes/Cloud&devops/aws-autoscaling-dashboard`
- This directory is currently not a git repository. `git status --short` returns: `fatal: not a git repository`.
- Hidden/runtime files exist: `.env`, `.env.example`, `.github/workflows/ci.yml`, and `.venv/`. Generated caches, load-test logs, generated Ansible inventory, and runtime data files were cleaned on 2026-04-27.
- Secret-bearing files are present. Do not copy secrets into responses or logs.

## Important Safety Notes

- `lab.env` is the preferred single source for Canvas credentials, Terraform input values, Terraform output ARNs/names, Ansible SSH settings, and load-test target values. It is ignored and must not be committed.
- `.env` contains active temporary AWS configuration and secret values generated from `lab.env` by `scripts/sync_dashboard_env.sh`. Only inspect it through redaction.
- `aws_lab_env.sh` was removed as a legacy secret-bearing helper. `.gitignore` still ignores it in case it is accidentally recreated.
- `.gitignore` currently ignores `.env`, `lab.env`, `aws_lab_env.sh`, `*.pem`, `.load-test/`, caches, `.venv/`, Terraform state, generated Ansible inventory, data runtime files, pyc files, and `.DS_Store`.
- Temporary AWS credentials may expire. If AWS calls fail with auth errors, first suspect expired lab credentials.

## Main Files

- `app.py`: Flask application, routes, snapshot cache, API wiring.
- `config.py`: loads `.env`, defines `AppConfig`, creates runtime directories.
- `runtime_guard.py`: refuses to start the dashboard on detected AWS runtimes when `DASHBOARD_RUNTIME_POLICY=local_only`.
- `aws_client.py`: boto3 EC2, CloudWatch, Auto Scaling, ELBv2, and S3 wrapper.
- `monitor.py`: builds infrastructure snapshots and warnings.
- `scaler.py`: custom scaling controller, persisted controller state, control actions.
- `metrics_logger.py`: writes metrics/events to CSV and SQLite, optional S3 sync.
- `diagnose_aws.py`: CLI diagnostic for ALB -> target group -> EC2 path.
- `setup.md`: from-scratch and repeat-run Canvas AWS Lab setup guide using `lab.env` as the single editable lab control file.
- `end.md`: shutdown guide for stopping local runs, loading `lab.env`, destroying Terraform AWS resources, verifying no AWS resources remain, and ending Canvas lab.
- `templates/index.html`: dashboard page.
- `templates/control.html`: scaling control page.
- `static/app.js`: dashboard/control frontend behavior.
- `static/styles.css`: full UI styling.
- `load_test.sh` and `load_test_worker.sh`: sustained/burst load generator against `/demo/work`.
- `lab.env.example`: safe template for the ignored `lab.env` control file containing Canvas credentials placeholders, Terraform inputs/outputs, Ansible key settings, load-test target, and local dashboard defaults.
- `run_app.sh`: optional local Gunicorn debug helper using `lab.env`/`.env` and `.venv`; Docker remains the required full-project run path.
- `ansible.cfg`: project-local Ansible config for Canvas lab runs; disables host-key blocking for temporary EC2 hosts and sets inventory/temp defaults.
- `terraform/`: mandatory IaC for ALB, target group, launch template, Auto Scaling Group, security groups, SSH access, detailed EC2 monitoring, and custom-controller ASG posture.
- `ansible/`: mandatory workload configuration playbook and generated/static inventory support for EC2 instances.
- `scripts/check_devops_prereqs.sh`: mandatory toolchain checker for Docker, Docker Compose, Terraform, Ansible, AWS CLI, curl, and Python.
- `scripts/load_lab_env.sh`: sourceable helper that loads `lab.env`, exports Canvas AWS values, derives `LOAD_TEST_TARGET_BASE`, and maps lab values to Terraform `TF_VAR_*` variables.
- `scripts/render_ansible_inventory.sh`: generates Ansible inventory from Terraform-created AWS instance tags.
- `scripts/sync_dashboard_env.sh`: writes `.env` from `lab.env` for Docker/dashboard use without printing secret values.
- `scripts/run_local_dashboard.sh`: Mac-local dashboard runner that requires `lab.env`, syncs `.env` from it, sets local-only runtime policy, and calls Docker Compose.
- `.dockerignore`: excludes `.env`, `lab.env`, private keys, legacy lab credentials, runtime data, caches, Terraform state, and generated inventory from Docker images.
- `tests/test_basic.py`: 20 unit tests using fake AWS clients, runtime-guard checks, and config/scaler behavior checks.

## Runtime Config Snapshot

This is a redacted snapshot from `.env` as of 2026-04-26:

- `FLASK_ENV=production`
- `APP_HOST=127.0.0.1`
- `APP_PORT=5000`
- `DASHBOARD_RUNTIME_POLICY=local_only` should be used for the local dashboard.
- `ALLOW_DASHBOARD_ON_AWS=false` should remain false for the required project flow.
- `LOCAL_DEMO_WORK_ENABLED=false` disables local dashboard CPU-load endpoint by default.
- `AWS_REGION=us-east-1`
- `MONITORING_LABEL=AWS Auto-Scaling Monitoring & Control Dashboard`
- `USE_IAM_ROLE=false`
- `AUTO_SCALING_GROUP_NAME=cppe-demo-asg`
- `LOAD_BALANCER_ARN` and `TARGET_GROUP_ARN` are configured for `us-east-1` and account `471112581819`.
- `AWS_METRIC_WINDOW_MINUTES=60`
- `AWS_METRIC_PERIOD_SECONDS=60`
- `POLL_INTERVAL_SECONDS=10`
- `.env` has `SCALING_MODE=custom`, `SCALE_OUT_CPU_THRESHOLD=70`, `SCALE_IN_CPU_THRESHOLD=30`.
- `CONTROL_ENABLED=true`
- `CONTROL_API_TOKEN` is set, so control POST actions require a token.
- `CONTROL_ALLOW_FORCE=false`
- `LOG_TO_S3=false`
- Runtime paths:
  - `METRICS_CSV_PATH=data/metrics.csv`
  - `EVENTS_CSV_PATH=data/events.csv`
  - `SQLITE_PATH=data/metrics.db`
  - `CONTROLLER_STATE_PATH=data/controller_state.json`
- `DEMO_WORK_MAX_ITERATIONS=8000000`

Important: `ScalingController` loads `data/controller_state.json` and stored values override default env-derived state fields. The current persisted controller state is more important than the threshold values in `.env`.

## Current Controller State

From `data/controller_state.json` as of 2026-04-26:

- mode: `custom`
- scale-out CPU threshold: `70.0`
- scale-in CPU threshold: `30.0`
- min instances: `2`
- max instances: `6`
- cooldown: `30` seconds
- active control: `true`
- last action: `scale_out`
- last action timestamp: `2026-04-20T07:01:04.743536+00:00`
- last reason: capacity was still converging, actual active instances `2` vs desired capacity `5`
- latest desired capacity: `5`
- last processed CPU timestamp: `2026-04-20T07:01:00+00:00`

## API Surface

Implemented routes in `app.py`:

- `GET /`: dashboard UI.
- `GET /control`: control page UI.
- `GET /healthz`: service health JSON.
- `GET /demo/work`: local CPU-heavy debug endpoint, disabled by default with `LOCAL_DEMO_WORK_ENABLED=false`; real load should target the AWS ALB `/demo/work` endpoint configured by Ansible.
- `GET /api/metrics`: collects/caches snapshot, evaluates controller, logs snapshot, returns history/events.
- `GET /api/instances`: returns EC2 instances and ASG metadata.
- `GET /api/events`: returns local controller events plus recent AWS scaling activities.
- `GET /api/history`: returns recent logged metric rows.
- `GET /api/control`: returns controller state, hard limits, and control flags.
- `POST /api/control`: validates optional token, applies settings/manual action, logs result.
- `GET /api/download-metrics`: downloads `data/metrics.csv`.

## Backend Behavior

`/api/metrics`:

- Uses a 10 second in-memory snapshot cache unless `?refresh=true`.
- Calls `MonitoringService.collect_snapshot()`.
- Calls `ScalingController.evaluate(snapshot, source="automatic")`.
- Logs snapshot metrics through `MonitoringService.log_snapshot()`.
- Returns current snapshot, controller state/result, metric history, and events.

`MonitoringService.collect_snapshot()`:

- Reads EC2 instances, ASG details, CPU series, ALB request series, ALB healthy host metric series, and direct target group health.
- Merges ASG metadata into EC2 instances.
- Counts active instances in `running` or `pending`.
- Prefers direct target group health counts for healthy hosts when available.
- Builds warnings for target health lookup errors, zero targets with desired capacity, low healthy target count, and unhealthy targets.

`ScalingController.evaluate()`:

- Noops in `aws_managed` mode.
- Noops when active control is disabled.
- Requires `AUTO_SCALING_GROUP_NAME` for active custom scaling.
- Avoids reprocessing the same latest CPU sample during automatic evaluation.
- Waits if actual active instance count differs from desired capacity.
- Applies cooldown for automatic actions.
- Uses CPU thresholds, request signals, confirmation samples, fast demo scale-out/scale-in steps, and bounds.
- Writes controller state to `data/controller_state.json`.
- Writes scaling decision events to `data/events.csv` and SQLite.

`MetricsLogger`:

- Ensures `data/metrics.csv`, `data/events.csv`, and `data/metrics.db` exist.
- Writes metric rows with timestamp, CPU, counts, desired capacity, mode, thresholds, bounds, action, ALB ARN, ASG name.
- Writes event rows with timestamp, source, type, action, message, mode, desired capacity, result, details.
- Optionally syncs metrics/events/db to S3 when enabled.

## Frontend Behavior

Dashboard page:

- Uses Chart.js from CDN.
- Shows infrastructure pulse, CPU chart, capacity card, recommendations, fleet snapshot, controller summary, traffic chart, Cloud + DevOps toolchain map, active EC2 table, event list.
- Polls `/api/metrics` every `min(POLL_INTERVAL_SECONDS, 10)` seconds.
- "Refresh Now" calls `/api/metrics?refresh=true`.
- Frontend falls back from raw series to history rows when live series are empty.

Control page:

- Loads `/api/control` and `/api/events?limit=20`.
- Saves settings with `POST /api/control`.
- Sends `X-Control-Token` when token input is present.
- Manual buttons include `evaluate_now` and `refresh`.
- Force scale buttons are hidden when `CONTROL_ALLOW_FORCE=false`.

## Metric Logging Workflow

- The dashboard logs real AWS metric snapshots to `data/metrics.csv`.
- The same metric rows are stored in `data/metrics.db` for `/api/history` and dashboard history.
- Controller and AWS scaling events are written to `data/events.csv` and SQLite.
- When `LOG_TO_S3=true`, local metric archives can be uploaded to S3.
- No separate training or recommendation pipeline is part of the project after the 2026-04-26 cleanup.

## Local Commands

Mandatory full run order:

```bash
./scripts/check_devops_prereqs.sh
test -f lab.env || cp lab.env.example lab.env
. ./scripts/load_lab_env.sh
cd terraform
terraform init
terraform apply
cd ..
# Copy Terraform outputs into lab.env, then:
. ./scripts/load_lab_env.sh
./scripts/sync_dashboard_env.sh
./scripts/render_ansible_inventory.sh "${LAB_REGION}" cloud-devops-autoscaling ansible/inventory.generated.ini
ansible-playbook -i ansible/inventory.generated.ini ansible/playbook.yml
./scripts/run_local_dashboard.sh
```

Python/Gunicorn debug helpers, not the primary project run:

```bash
.venv/bin/python app.py
./run_app.sh
```

Tests:

```bash
.venv/bin/python -m pytest -q
```

Docker:

```bash
./scripts/run_local_dashboard.sh
```

Terraform:

```bash
test -f lab.env || cp lab.env.example lab.env
. ./scripts/load_lab_env.sh
cd terraform
terraform init
terraform plan
```

Ansible syntax check:

```bash
ANSIBLE_LOCAL_TEMP=/tmp/ansible-local ANSIBLE_REMOTE_TEMP=/tmp/ansible-remote ansible-playbook --syntax-check -i demo_workload, ansible/playbook.yml
```

Diagnostic:

```bash
.venv/bin/python diagnose_aws.py
```

Load testing:

```bash
./load_test.sh probe scaleout70
./load_test.sh start scaleout70
./load_test.sh stop
./load_test.sh burst 40 2500000
```

`load_test.sh` now requires an AWS ALB `/demo/work` target URL via `LOAD_TEST_TARGET_BASE` or an explicit argument, and refuses localhost targets so load is generated against AWS resources rather than the local dashboard. The recommended scale-out demo profile is `scaleout70`; sustained profiles are `light`, `medium`, `heavy`, `scaleout70`, `spike`, and `flood`.

## Data State

As of the 2026-04-27 cleanup, generated runtime data files were removed:

- `data/metrics.csv`
- `data/events.csv`
- `data/metrics.db`
- `data/controller_state.json`
- `.load-test/`

The app recreates metrics/events CSV files, SQLite tables, and controller state when it starts and receives telemetry/control activity.

## Docs And Setup Notes

- `README.md` is now a concise project overview plus quick run/shutdown commands.
- `setup.md` is now a concise Canvas AWS Lab runbook for the mandatory Terraform -> Ansible -> Docker workflow.
- `end.md` is now a concise shutdown runbook focused on stopping local processes, running `terraform destroy`, and verifying AWS cleanup.
- `/Users/shrey-mac/Downloads/AWS_AutoScaling_Tools_Deck (1).pptx` was used on 2026-04-26 as a design/content source. Extracted deck themes: AWS Auto-Scaling Monitoring & Control Dashboard, Flask application, boto3 AWS observability, CSV/SQLite analytics history, Docker, GitHub Actions, Terraform, and Ansible.
- Setup docs now use a single-region rule with examples in `us-east-1`, matching the active `.env`, data, and load-test default target.
- Docs recommend custom app scaling with `SCALING_MODE=custom`, `SCALE_OUT_CPU_THRESHOLD=70`, `SCALE_IN_CPU_THRESHOLD=30`, `USE_IAM_ROLE=false`, `CONTROL_ALLOW_FORCE=false`, and `LOG_TO_S3=false`.

## AWS Infrastructure

The old `iam/` policy examples were removed on 2026-04-27 because the Canvas lab flow assumes no IAM management access. Use Canvas temporary credentials and keep `USE_IAM_ROLE=false`.

Expected AWS resources:

- ALB: `cppe-demo-alb`
- Target group: `cppe-demo-tg`
- Auto Scaling Group: `cppe-demo-asg`
- Demo workload target service on EC2: Flask/Gunicorn on port `5000`, health path `/healthz`, work path `/demo/work`

Required IaC and configuration workflow:

- `terraform/` creates an ALB, target group, launch template, ASG, security groups, SSH access, detailed EC2 monitoring, and custom-controller tags from supplied VPC/subnet/AMI/key variables. Terraform does not create an AWS target-tracking policy now; the local dashboard controller submits scaling decisions.
- `terraform/variables.tf` requires `key_name` and `ssh_allowed_cidr_blocks` so Ansible SSH access is part of the infrastructure path.
- `ansible/` configures the demo workload on Terraform-created EC2 instances and is required before the ALB target group should be considered ready.
- `scripts/render_ansible_inventory.sh` discovers running instances tagged with `Project=<project_name>` and writes `ansible/inventory.generated.ini`.

## Tests

Last local test run:

- Date: 2026-04-27
- Command: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider`
- Result: `20 passed in 0.14s`

Covered behavior includes:

- Metrics/event logging.
- Scale-out and scale-in decisions.
- Request signal behavior.
- Fast demo scaling steps.
- Target health warning generation.
- Capacity convergence no-op.
- Duplicate CPU sample prevention.
- ASG bounds sync.
- AWS rejection error response.
- Local dashboard runtime guard allow/block behavior.

## Future Maintenance Checklist

Before modifying behavior:

1. Read this file.
2. Inspect relevant source files directly because this log can become stale.
3. If AWS credentials or `.env` are relevant, inspect only with redaction.
4. Run focused tests after code changes.
5. Update this file with what changed, commands run, and any new caveats.

Recommended hygiene TODOs:

- Keep docs consistent about region and default scaling mode.
- Keep runtime files out of the project source: `data/*.csv`, `data/*.db`, `data/controller_state.json`, `.load-test/`, `.venv/`, caches, generated inventory, and private key files.

## Update Log

### 2026-04-26 - Initial Codex context pass

- Read repository structure, docs, configs, backend files, frontend files, scripts, tests, IAM policies, and runtime data summaries.
- Created this persistent context log.
- Verified local tests pass with `.venv/bin/python -m pytest -q`.
- Recorded active runtime context without copying secret values.

### 2026-04-26 - Removed training/recommendation components

- Removed the `ml/` source directory and empty `models/` runtime directory.
- Removed training/recommendation dependency pins from `requirements.txt`.
- Removed model/training/MLflow config fields from `config.py`, `.env`, `.env.example`, `setup.md`, and `demo-checklist.md`.
- Removed the `./models:/app/models` Docker Compose volume.
- Updated `README.md` to describe metric logging instead of a training workflow and removed the stale `/api/predict` endpoint reference.
- Updated `tests/test_basic.py` for the smaller `AppConfig` shape.
- Verified with `.venv/bin/python -m pytest -q`: `17 passed in 0.15s`.

### 2026-04-26 - Matched project to AWS AutoScaling Tools deck

- Read `/Users/shrey-mac/Downloads/AWS_AutoScaling_Tools_Deck (1).pptx` and extracted 3 slides of content.
- Rebranded visible UI from the old course console label to `Cloud & DevOps Console`.
- Updated dashboard hero text to `Monitoring & Control Dashboard` with the deck's AWS Monitoring / Flask Application / DevOps Project framing.
- Added a dashboard `Cloud + DevOps Toolchain` section with the deck's App Layer, AWS + APIs, Data + Analytics, and DevOps + IaC categories.
- Added `terraform/` infrastructure for ALB, target group, launch template, Auto Scaling Group, security groups, and CPU target tracking.
- Added `ansible/` playbook for repeatable demo workload configuration when SSH access is available.
- Updated `README.md`, `setup.md`, and `demo-checklist.md` to mention Terraform and Ansible and the deck-aligned toolchain.
- Updated default `MONITORING_LABEL` to `AWS Auto-Scaling Monitoring & Control Dashboard`.
- Added `.env` and Terraform state patterns to `.gitignore`.
- Verified `.venv/bin/python -m pytest -q`: `17 passed in 0.13s`.
- Verified shell scripts with `bash -n`, Python files with `py_compile`, Terraform files with `terraform fmt -check -recursive terraform`, and Ansible syntax with temp paths under `/tmp`.
- Started the local Gunicorn app at `http://127.0.0.1:5000` and verified `/healthz` plus rendered dashboard HTML containing the new Cloud & DevOps branding and toolchain section.

### 2026-04-26 - Provided AWS lab setup and full run steps

- User asked for AWS lab setup and full app run instructions.
- Recommended AWS lab setup path: same region throughout, default/project VPC, ALB security group, app security group, target group on port 5000 with `/healthz`, launch template, internet-facing ALB, ASG attached to target group, and CPU target tracking policy.
- Recommended copying ASG name, ALB ARN, target group ARN, and temporary lab credentials into `.env`, then running the dashboard locally with Docker Compose.
- Later update made Terraform and Ansible mandatory, so manual Console creation is only a fallback for restricted lab accounts.

### 2026-04-26 - Made Terraform and Ansible mandatory

- User clarified Terraform and Ansible are not optional and must be mandatory like Docker.
- Updated Terraform so SSH access is required through `key_name` and `ssh_allowed_cidr_blocks`.
- Updated Terraform launch template to attach the key pair, associate public IPs, allow SSH from the supplied CIDR, and only bootstrap base Python packages.
- Moved workload configuration responsibility to Ansible; Terraform now provisions infrastructure and Ansible configures the Flask/Gunicorn demo workload.
- Added `scripts/check_devops_prereqs.sh` to require Docker, Docker Compose, Terraform, Ansible, AWS CLI, curl, and Python before running the project.
- Added `scripts/render_ansible_inventory.sh` to generate the mandatory Ansible inventory from running AWS instances tagged with the project name.
- Updated `README.md`, `setup.md`, `demo-checklist.md`, `terraform/README.md`, `ansible/README.md`, and CI to use Terraform -> Ansible -> Docker as the required run order.
- Verified `terraform fmt -check -recursive terraform`, Ansible syntax check, shell script syntax, prerequisite checker, and `.venv/bin/python -m pytest -q` with `17 passed in 0.38s`.

### 2026-04-26 - User asked for setup/run guide

- User asked for the steps to run the project with Terraform, Ansible, Docker, plus a normal app starting guide.
- Answer should present Terraform -> Ansible -> Docker as the required full-project flow.
- Normal Python app startup should be described as local debugging only, not a replacement for the mandatory Cloud + DevOps workflow.

### 2026-04-26 - Clarified Console vs Terraform/Ansible purpose

- User asked what the point of Terraform and Ansible is if resources are created in the AWS Console.
- Clarified project stance: in the mandatory workflow, users should not manually create ALB, target group, launch template, ASG, or security groups in the Console.
- AWS Console should only be used to collect lab prerequisites such as VPC/subnet/AMI/key information and to verify Terraform-created resources, target health, and scaling activity.
- Updated `README.md`, `setup.md`, and `demo-checklist.md` to state Terraform creates infrastructure, Ansible configures workload instances, and Docker runs the local dashboard.

### 2026-04-26 - Enforced local dashboard and AWS-only resources split

- User clarified the monitoring dashboard must run on the Mac, while AWS should host only resources, not the dashboard.
- Added `runtime_guard.py` and wired it into `app.py`; with `DASHBOARD_RUNTIME_POLICY=local_only`, detected AWS runtimes are blocked unless `ALLOW_DASHBOARD_ON_AWS=true` is deliberately set.
- Added `.dockerignore` so `.env`, `aws_lab_env.sh`, runtime data, caches, generated inventory, and Terraform state are excluded from Docker build context.
- Extended `.gitignore` for generated data runtime files.
- Updated `Dockerfile`, `docker-compose.yml`, `.env`, `.env.example`, and `run_app.sh` so the local dashboard is bound to `127.0.0.1` and marked local-only.
- Added `scripts/run_local_dashboard.sh` as the preferred Mac runner for Docker Compose.
- Set `LOCAL_DEMO_WORK_ENABLED=false` by default so dashboard-local `/demo/work` is disabled; load generation should target the AWS ALB `/demo/work` endpoint.
- Tightened `load_test.sh` so it requires `LOAD_TEST_TARGET_BASE` or an explicit ALB URL and refuses localhost/127.0.0.1 targets.
- Added an Ansible pre-task assertion to refuse local dashboard targets; Ansible remains only for Terraform-created AWS workload instances.
- Tagged Terraform resources with `DashboardRuntime=local-mac-only` and `AWSRole=remote-workload-resources`.
- Updated `README.md`, `setup.md`, `demo-checklist.md`, `terraform/README.md`, `ansible/README.md`, and the dashboard toolchain copy to describe the split clearly.
- Verified shell syntax, Terraform fmt, Ansible syntax, Python compile, Docker Compose config, load-test localhost refusal, and `.venv/bin/python -m pytest -q` with `19 passed in 0.16s`.
- Docker image build check could not run because the Docker daemon was not running on the Mac.

### 2026-04-26 - User asked how to use the project

- User asked how to use the tightened Terraform + Ansible + Docker project.
- Answer should explain the required order: collect AWS lab values, Terraform creates AWS resources, Ansible configures EC2 workload target, `.env` points the Mac dashboard at Terraform outputs, Docker runs the dashboard locally, load testing targets the AWS ALB.

### 2026-04-26 - Rebuilt setup.md for Canvas AWS Lab from scratch

- User asked for a new setup guide for starting from scratch in a Canvas AWS Lab.
- Replaced `setup.md` with a Canvas-focused guide covering lab start, temporary access key/secret/session token collection at the beginning, no IAM management access, one-region setup, VPC/subnet/AMI/key pair collection, Terraform apply, Ansible workload configuration, local Mac dashboard run, AWS ALB load testing, demo checklist, troubleshooting, and cleanup.
- Documented that the only allowed Console creation prerequisite is an EC2 key pair if the lab does not already provide one; ALB, target group, launch template, ASG, security groups, and scaling policy are Terraform-owned.
- Updated `.env.example` to Canvas-safe defaults: `SCALING_MODE=aws_managed`, `SCALE_OUT_CPU_THRESHOLD=70`, `SCALE_IN_CPU_THRESHOLD=30`, and `CONTROL_ALLOW_FORCE=false`.

### 2026-04-26 - Expanded setup.md with first-run and later-run flows

- User asked for every step needed for first run, second run, and following runs, including what to install and what to open on AWS and Mac.
- Reorganized `setup.md` with explicit `What To Install On Your Mac`, `What To Open`, `First Run From Scratch`, and `Second Run And Later Runs` sections.
- Added later-run cases for same Canvas lab still running, expired credentials with existing resources, and stopped/reset Canvas lab.
- Added guidance for re-exporting Canvas credentials, updating `.env`, rerunning Terraform plan/apply, rerunning Ansible idempotently, starting the local dashboard, and safely handling stale Terraform state after lab resets.
- Added `.terraform-state-backups/` to `.gitignore` because the setup guide now backs up local Terraform state before resetting stale lab state.

### 2026-04-27 - Added end-of-lab shutdown guide

- User asked for `end.md` explaining how to close runs and make sure nothing is left running in AWS because it might cost money.
- Created `end.md` with ordered shutdown steps: stop local load workers, stop local dashboard/Docker Compose, refresh Canvas credentials if needed, set Terraform variables, run `terraform destroy`, verify AWS cleanup with AWS CLI and Console, manual Console cleanup fallback, end Canvas lab, and final local checks.
- The guide emphasizes deleting the ASG before manual EC2 termination if Terraform destroy fails, because an active ASG can relaunch instances.
- Added `end.md` to the main file list in this context log.

### 2026-04-27 - Fixed macOS Bash inventory script issue

- User hit `mapfile: command not found` while running `scripts/render_ansible_inventory.sh` on macOS.
- Replaced Bash 4 `mapfile` usage with a Bash 3-compatible `while read` parser so the script works with macOS default Bash.
- Verified `bash -n scripts/render_ansible_inventory.sh`, confirmed no remaining `mapfile/readarray` usage, and ran a mocked AWS CLI inventory generation test successfully.

### 2026-04-27 - Fixed Ansible host key verification block

- User hit `Host key verification failed` when running `ansible-playbook` against Terraform-created Canvas lab EC2 instances.
- Added project-root `ansible.cfg` with `host_key_checking = False` and SSH args `StrictHostKeyChecking=no` plus `UserKnownHostsFile=/dev/null`, appropriate for temporary Canvas lab hosts.
- Updated `ansible/README.md` and `setup.md` to instruct running Ansible from the project root so the local config applies.

### 2026-04-27 - Added single `lab.env` control file workflow

- User asked for one file to enter AWS credentials, ARNs, and other lab values so other files can reuse them without repeated manual entry.
- Added `lab.env.example` as the safe template for ignored `lab.env`; it covers Canvas temporary credentials, Terraform inputs, Terraform outputs/ARNs, Ansible SSH key values, load-test target derivation, and dashboard defaults.
- Added `scripts/load_lab_env.sh` to source `lab.env`, export AWS variables, map lab values to Terraform `TF_VAR_*`, set Ansible key variables, and derive `LOAD_TEST_TARGET_BASE` from `ALB_DNS_NAME`.
- Added `scripts/sync_dashboard_env.sh` to generate `.env` from `lab.env` for Docker/dashboard use without printing secret values.
- Updated `scripts/run_local_dashboard.sh` to require `lab.env` and auto-sync `.env` from it before starting Docker Compose.
- Added `lab.env` to `.gitignore` and `.dockerignore`.
- Created an ignored local `lab.env` from `lab.env.example` with placeholder values only; user should edit this file with current Canvas lab credentials and outputs.
- Rewrote `setup.md` around the single-file flow: first run starts by copying `lab.env.example` to `lab.env`, Canvas credentials go into that file, Terraform uses sourced `TF_VAR_*`, Terraform outputs are copied back into `lab.env`, Ansible uses the same loaded values, Docker runs locally, and load testing derives the ALB target.
- Rewrote `end.md` so shutdown uses `. ./scripts/load_lab_env.sh` and plain `terraform destroy` instead of repeated `-var` flags.
- Updated `README.md` credential model, Terraform/Ansible/Docker quick flow, and project structure to mention `lab.env` and the new scripts.
- Verified shell syntax, Terraform formatting, Docker Compose config, sourceability of `load_lab_env.sh` from both Bash and zsh with a temporary placeholder lab file, stale credential/manual-var scans, and `.venv/bin/python -m pytest -q` with `19 passed in 0.14s`.

### 2026-04-27 - Set dashboard auto-refresh to 10 seconds

- User asked for the app to auto-refresh after a few seconds, around 10 seconds.
- Changed the frontend refresh cap in `static/app.js` from 15 seconds to 10 seconds for both dashboard and control page polling.
- Changed the initial dashboard refresh-cycle display in `templates/index.html` to `10 sec`.
- Changed the backend snapshot cache TTL in `app.py` from 15 seconds to 10 seconds so automatic dashboard refreshes can collect fresh snapshots at the 10-second cadence.
- Updated `config.py`, `.env.example`, `lab.env.example`, local placeholder `lab.env`, and `scripts/sync_dashboard_env.sh` defaults to `POLL_INTERVAL_SECONDS=10`.
- Verified shell syntax and `.venv/bin/python -m pytest -q` with `19 passed in 0.09s`.

### 2026-04-27 - Cleaned project directory and refined app

- User asked to remove unused files, clean the project directory, avoid breakage, and refine UI/backend.
- Removed generated clutter: Python bytecode caches, pytest cache, `.DS_Store`, `.load-test/`, generated Ansible inventory, Terraform provider cache directory, and runtime data files under `data/`.
- Removed sensitive/obsolete local artifacts: root `cloud-devops-lab-key.pem`, legacy `aws_lab_env.sh`, and `with_project_env.sh`.
- Removed no-IAM policy examples under `iam/` and the stale duplicate `demo-checklist.md`; `setup.md` is now the single run guide.
- Kept Terraform state files intentionally so `terraform destroy` remains possible for existing AWS resources.
- Kept `.venv` intentionally because it is the active local test/debug environment.
- Updated `run_app.sh` to use the current `lab.env`/`.env` sync flow and fail clearly when Gunicorn is missing.
- Tightened backend config parsing in `config.py` so invalid boolean/int/float env values fall back to defaults instead of crashing startup.
- Updated the missing AWS credentials API error to point users to the Canvas `lab.env` workflow.
- Refined UI CSS by removing decorative glow blobs/radial orb backgrounds, reducing panel/card radii, removing negative letter spacing, and reducing hover movement for a calmer dashboard.
- Updated `.gitignore` and `.dockerignore` to ignore `*.pem`.
- Updated README security/troubleshooting/project structure content to match the no-IAM Canvas lab flow.
- Verified shell syntax, Terraform formatting, Ansible syntax check, Docker Compose config, and tests with `20 passed in 0.20s`.

### 2026-04-27 - Simplified setup and shutdown steps

- User asked to make the steps clear and concise and remove unnecessary instructions.
- Replaced long `setup.md` with a short runbook: install/check tools, start Canvas lab, fill `lab.env`, run Terraform, copy outputs, run Ansible, start Docker dashboard, generate ALB load, and handle later runs/common fixes.
- Replaced long `end.md` with a short shutdown guide: stop load/dashboard, refresh credentials, run `terraform destroy`, verify AWS resources are gone, and use a minimal manual cleanup order only if Terraform fails.
- Replaced long `README.md` with a concise project overview, required tools, `lab.env` values, full run commands, load-test commands, and shutdown commands.
- Verified no stale long-guide terms in active docs, shell syntax passed, and tests passed with `20 passed in 0.12s`.

### 2026-04-27 - Made custom scaling the required scaling path

- User asked to use custom scaling logic for faster and more accurate scaling and to update Terraform, Ansible, docs, and load generation for 70% CPU scale-out.
- Removed Terraform AWS-managed target-tracking policy so the local dashboard custom controller is the scaling authority.
- Updated Terraform to tag resources with `ScalingMode=custom-dashboard-controller`, enable detailed EC2 monitoring, set ASG cooldown to 60 seconds, reduce health check grace to 120 seconds, and speed target group health checks to 10 seconds.
- Updated config defaults, `.env.example`, `lab.env.example`, local `lab.env`, generated `.env`, and `scripts/sync_dashboard_env.sh` to use `SCALING_MODE=custom`, scale out at 70%, scale in at 30%, 1-minute metrics, and a 60-second cooldown.
- Adjusted custom scale-out step logic so request-backed 70% CPU overload can use the fast scale-out step.
- Updated Ansible workload `/demo/work` to support timed CPU-burn requests through a `seconds` parameter and increased Gunicorn timeout for sustained load.
- Added `scaleout70` load-test profile that starts sustained 20-second CPU-burn requests intended to push t3.micro workload CPU above 70%.
- Updated `README.md`, `setup.md`, `terraform/README.md`, and `ansible/README.md` around the custom scaling workflow and the `scaleout70` load profile.
- Verified shell syntax, Terraform formatting, Terraform validation, Ansible syntax, Docker Compose config, load-test help/localhost refusal, and tests with `20 passed in 0.14s`. Removed the generated Terraform provider cache after validation to keep the directory clean.
