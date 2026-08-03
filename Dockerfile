FROM python:3.11-slim

LABEL org.opencontainers.image.title="Local AWS Auto-Scaling Dashboard"
LABEL org.opencontainers.image.description="Operator Mac dashboard only; AWS hosts Terraform resources and the Ansible workload target."

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DASHBOARD_RUNTIME_POLICY=local_only
ENV ALLOW_DASHBOARD_ON_AWS=false
ENV LOCAL_DEMO_WORK_ENABLED=false

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "app:app"]
