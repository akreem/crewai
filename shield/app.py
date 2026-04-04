"""
Shield Agent — autonomous security scanner and pentester.

Receives a high-level security goal, plans its own scan strategy,
executes scans, interprets results, runs follow-ups, and returns
a complete vulnerability analysis with remediations.
"""

import subprocess
import json
import os
import re
from fastapi import FastAPI
from pydantic import BaseModel
from shared.agent_loop import AgentLoop

app = FastAPI(title="Shield Agent")

WORKSPACE = os.getenv("WORKSPACE_DIR", "/app/workspace")

_SAFE_TARGET = re.compile(r"^[a-zA-Z0-9.\-:/_ ]+$")


def _validate(value: str, label: str) -> str | None:
    if not value:
        return f"{label} is required"
    if not _SAFE_TARGET.match(value):
        return f"Invalid characters in {label}"
    return None


# ---------------------------------------------------------------------------
# LOCAL TOOLS
# ---------------------------------------------------------------------------
async def nmap_scan(target: str = "", scan_type: str = "quick", ports: str = "", **kwargs) -> dict:
    if err := _validate(target, "target"):
        return {"error": err}

    profiles = {
        "quick": ["-sV", "--top-ports", "100", "-T4"],
        "stealth": ["-sS", "-sV", "-T2", "--top-ports", "1000"],
        "full": ["-sV", "-sC", "-p-", "-T3"],
        "vuln": ["-sV", "--script", "vuln", "--top-ports", "1000"],
        "udp": ["-sU", "--top-ports", "50", "-T4"],
    }
    args = profiles.get(scan_type, profiles["quick"])
    if ports:
        args = [a for a in args if not a.startswith("--top-ports")]
        args += ["-p", ports]

    cmd = ["nmap", "-oX", "-"] + args + [target]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        return {
            "target": target,
            "scan_type": scan_type,
            "command": " ".join(cmd),
            "output": result.stdout[-8000:],
            "stderr": result.stderr[-1000:] if result.stderr else None,
        }
    except subprocess.TimeoutExpired:
        return {"error": "Scan timed out (10 min)"}
    except Exception as e:
        return {"error": str(e)}


async def trivy_scan(image: str = "", **kwargs) -> dict:
    if err := _validate(image, "image"):
        return {"error": err}

    cmd = ["trivy", "image", "--format", "json", "--severity", "CRITICAL,HIGH,MEDIUM", image]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        try:
            parsed = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            parsed = {"raw": result.stdout[-8000:]}
        return {"image": image, "results": parsed}
    except subprocess.TimeoutExpired:
        return {"error": "Trivy scan timed out"}
    except Exception as e:
        return {"error": str(e)}


async def checkov_scan(path: str = "", **kwargs) -> dict:
    target = path or WORKSPACE
    resolved = os.path.realpath(target)
    if not resolved.startswith("/app"):
        return {"error": "Path must be within /app"}

    cmd = ["checkov", "-d", resolved, "--output", "json", "--quiet"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        try:
            parsed = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            parsed = {"raw": result.stdout[-8000:]}
        return {"path": target, "results": parsed}
    except Exception as e:
        return {"error": str(e)}


async def dns_lookup(target: str = "", **kwargs) -> dict:
    if err := _validate(target, "target"):
        return {"error": err}
    cmd = ["nslookup", target]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return {"target": target, "output": result.stdout}
    except Exception as e:
        return {"error": str(e)}


async def check_ssl(host: str = "", port: int = 443, **kwargs) -> dict:
    if err := _validate(host, "host"):
        return {"error": err}
    cmd = ["nmap", "--script", "ssl-cert,ssl-enum-ciphers", "-p", str(port), host]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return {"host": host, "port": port, "output": result.stdout[-4000:]}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Tool schemas for the LLM
# ---------------------------------------------------------------------------
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "nmap_scan",
            "description": "Run an nmap network scan. Use 'quick' for fast recon, 'stealth' for evasive, 'full' for all ports, 'vuln' for vulnerability scripts, 'udp' for UDP.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "IP, hostname, or CIDR range"},
                    "scan_type": {"type": "string", "enum": ["quick", "stealth", "full", "vuln", "udp"], "default": "quick"},
                    "ports": {"type": "string", "description": "Specific ports to scan, e.g. '22,80,443' or '1-1000'. Leave empty for profile defaults."},
                },
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trivy_scan",
            "description": "Scan a Docker image for known CVEs and vulnerabilities using Trivy",
            "parameters": {
                "type": "object",
                "properties": {
                    "image": {"type": "string", "description": "Docker image name:tag"},
                },
                "required": ["image"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "checkov_scan",
            "description": "Scan IaC files (Dockerfile, docker-compose, Terraform, K8s manifests) for security misconfigurations",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to scan. Defaults to /app/workspace"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dns_lookup",
            "description": "Perform DNS lookup on a target",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "Hostname to look up"},
                },
                "required": ["target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_ssl",
            "description": "Check SSL/TLS certificate and cipher suites on a host",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "Hostname to check"},
                    "port": {"type": "integer", "default": 443},
                },
                "required": ["host"],
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "nmap_scan": nmap_scan,
    "trivy_scan": trivy_scan,
    "checkov_scan": checkov_scan,
    "dns_lookup": dns_lookup,
    "check_ssl": check_ssl,
}

SYSTEM_PROMPT = """\
You are the Shield — a senior security engineer and penetration tester running inside an isolated Docker container.

You'll receive a mission and a strategic brief from the Tech Lead (Orchestrator). \
The brief provides targets, context, and suggested approaches — but YOU own the security methodology. \
You decide scan strategy, depth, tools, and follow-up actions.

Your engineering principles:
- The brief is intel, not orders. If the Tech Lead says "quick scan" but you spot \
  something suspicious, go deeper. Security doesn't cut corners.
- Think like an attacker: recon → enumerate → probe → exploit path analysis.
- Don't just list open ports — assess what an attacker could DO with them.
- Correlate findings: open port 22 + default SSH config + outdated OpenSSH = a kill chain, not 3 separate issues.
- If you find something critical that wasn't asked about, REPORT IT. Don't stay in scope when security is at risk.
- Challenge assumptions: if Watchman says a container is healthy but you see it's running as root \
  with all capabilities, that's a finding.
- Provide remediations that are specific and implementable, not generic "keep software updated."

Your output should read like a pentest report:
- **Risk Level**: overall assessment (critical / high / medium / low)
- **Attack Surface**: what's exposed and what an attacker sees
- **Findings**: each with severity, exploit scenario, and specific remediation
- **Kill Chains**: if findings combine into a realistic attack path, describe it
- **Flags for Team**: anything that needs urgent attention or falls outside your scope
"""

agent = AgentLoop(
    name="shield",
    system_prompt=SYSTEM_PROMPT,
    tools_schema=TOOLS_SCHEMA,
    tool_functions=TOOL_FUNCTIONS,
)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
class GoalRequest(BaseModel):
    goal: str
    brief: dict | None = None
    depends_on: list[str] | None = None


@app.post("/agent/run")
async def run_agent(req: GoalRequest):
    return await agent.run(req.goal, brief=req.brief, depends_on=req.depends_on)


@app.get("/health")
async def health():
    tools = {}
    for tool in ["nmap", "trivy", "checkov"]:
        try:
            subprocess.run([tool, "--version"], capture_output=True, timeout=10)
            tools[tool] = "available"
        except Exception:
            tools[tool] = "not found"
    return {"status": "ok", "service": "shield", "tools": tools}
