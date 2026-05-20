# Faryo VM Guard

Cloud Run guard for the GCP Faryo VM. It is invoked by Cloud Scheduler, checks the Gateway guard health endpoint, and resets the Compute Engine instance only after consecutive failures.

Required environment variables:

```text
PROJECT_ID=<gcp-project-id>
ZONE=<compute-zone>
INSTANCE_NAME=<compute-instance-name>
HEALTH_URL=<gateway-/api/guard-health-url>
HEALTH_TOKEN=<private-guard-token>
FAILURE_THRESHOLD=3
COOLDOWN_SECONDS=600
REQUEST_TIMEOUT_SECONDS=8
```

The runtime service account needs only `compute.instances.get`, `compute.instances.setLabels`, `compute.instances.reset`, and `compute.zoneOperations.get` on the target project.
