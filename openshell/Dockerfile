# StormDesk agent + console image for the OpenShell sandbox.
# Build from the repo root AFTER running the sync scripts, so the cached
# closures, alerts and road graph are baked in and nothing needs the network:
#   docker build -f openshell/Dockerfile -t stormdesk:local .
FROM python:3.12-slim

# OpenShell policy runs the workload as the "sandbox" user (process.run_as_user).
RUN useradd --create-home --shell /bin/bash sandbox

WORKDIR /app
COPY requirements.txt .
# GPU and training packages stay on the host; the sandbox only runs the app.
RUN pip install --no-cache-dir -r requirements.txt

COPY stormdesk/ stormdesk/
COPY ui/ ui/
COPY scripts/ scripts/
COPY eval/ eval/
COPY data/ data/
COPY openshell/ openshell/

# Ship the policy in the image too. A --policy flag at create time takes precedence.
COPY openshell/policy.yaml /etc/openshell/policy.yaml

# OpenShell 0.1.4 refuses a working directory the sandbox user does not own
# ("OCI WorkingDir is not usable by the sandbox identity"). Only the directory changes
# owner; the files stay root-owned, and the policy keeps /app read-only regardless.
RUN chown sandbox:sandbox /app

# /app is read-only inside the sandbox; the live DB goes to /tmp.
ENV STORMDESK_DB=/tmp/stormdesk/stormdesk.db \
    STORMDESK_SANDBOX=1 \
    AGENT_BASE_URL=http://host.openshell.internal:8000/v1 \
    TRIAGE_BASE_URL=http://host.openshell.internal:8001/v1 \
    PYTHONUNBUFFERED=1

# MOCK=1 (scripts/openshell_up.sh on a laptop) runs the scripted agent, so no GPU is needed.
ARG MOCK=0
ENV STORMDESK_MOCK_LLM=$MOCK

USER sandbox
EXPOSE 8080
CMD ["python3.12", "scripts/sandbox_start.py"]
