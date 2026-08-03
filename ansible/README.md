# Ansible Workload Configuration

This playbook configures only the EC2 demo workload target used behind the Application Load Balancer:

- installs Python, Flask, and Gunicorn
- deploys the `/healthz` and CPU-heavy `/demo/work` Flask workload target service
- runs the service through systemd on port `5000`

Ansible is mandatory for the full project workflow. Terraform creates the infrastructure and SSH access; Ansible configures the workload target that makes the ALB target group healthy.

It must not deploy or run the monitoring dashboard. The dashboard runs locally on your Mac through Docker Compose and reads these AWS resources through boto3.

Run Ansible from the project root so the local `ansible.cfg` is applied. That config disables SSH host key blocking for Canvas lab instances, which are temporary and frequently recreated.

```bash
. ./scripts/load_lab_env.sh
./scripts/render_ansible_inventory.sh us-east-1 cloud-devops-autoscaling ansible/inventory.generated.ini
ansible-playbook -i ansible/inventory.generated.ini ansible/playbook.yml
```

If you are running from inside the `ansible/` directory, adjust the paths accordingly.
