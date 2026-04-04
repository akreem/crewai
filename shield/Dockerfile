FROM python:3.12-slim

WORKDIR /app
ENV PYTHONPATH=/app

# System-level security tools
RUN apt-get update && apt-get install -y --no-install-recommends \
        nmap \
        wget \
        apt-transport-https \
        gnupg \
        lsb-release \
    && rm -rf /var/lib/apt/lists/*

# Trivy
RUN wget -qO - https://aquasecurity.github.io/trivy-repo/deb/public.key \
        | gpg --dearmor -o /usr/share/keyrings/trivy.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/trivy.gpg] https://aquasecurity.github.io/trivy-repo/deb generic main" \
        > /etc/apt/sources.list.d/trivy.list \
    && apt-get update && apt-get install -y --no-install-recommends trivy \
    && rm -rf /var/lib/apt/lists/*

# Checkov (Python-based IaC scanner)
RUN pip install --no-cache-dir checkov

COPY shared/ /app/shared/
COPY shield/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shield/app.py .

EXPOSE 6002
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "6002"]
