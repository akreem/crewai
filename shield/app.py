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
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from shared.agent_loop import AgentLoop

app = FastAPI(title="Shield Agent")

WORKSPACE = os.getenv("WORKSPACE_DIR", "/app/workspace")
HOST_GATEWAY = os.getenv("HOST_GATEWAY", "host.docker.internal")

_SAFE_TARGET = re.compile(r"^[a-zA-Z0-9.\-:/_ ]+$")


def _validate(value: str, label: str) -> str | None:
    if not value:
        return f"{label} is required"
    if not _SAFE_TARGET.match(value):
        return f"Invalid characters in {label}"
    return None


def _summarize_trivy(parsed: dict) -> dict:
    """Extract a compact summary from trivy JSON — counts + top CVEs per target."""
    results = parsed.get("Results", [])
    summary = {"targets": [], "total_vulns": 0}
    for target in results:
        vulns = target.get("Vulnerabilities", [])
        if not vulns:
            continue
        counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0}
        top_cves = []
        for v in vulns:
            sev = v.get("Severity", "UNKNOWN")
            if sev in counts:
                counts[sev] += 1
            if len(top_cves) < 10:
                top_cves.append({
                    "id": v.get("VulnerabilityID", ""),
                    "pkg": v.get("PkgName", ""),
                    "severity": sev,
                    "title": (v.get("Title") or "")[:100],
                    "installed": v.get("InstalledVersion", ""),
                    "fixed": v.get("FixedVersion", ""),
                })
        entry = {
            "target": target.get("Target", ""),
            "type": target.get("Type", ""),
            "counts": counts,
            "total": len(vulns),
            "top_cves": top_cves,
        }
        summary["targets"].append(entry)
        summary["total_vulns"] += len(vulns)
    return summary


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

    cmd = ["nmap", "-oN", "-"] + args + [target]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        return {
            "target": target,
            "scan_type": scan_type,
            "command": " ".join(cmd),
            "output": result.stdout[-6000:],
            "stderr": result.stderr[-500:] if result.stderr else None,
        }
    except subprocess.TimeoutExpired:
        return {"error": "Scan timed out (10 min)"}
    except Exception as e:
        return {"error": str(e)}


async def list_docker_images(**kwargs) -> dict:
    """List Docker images available on the host via docker.sock."""
    cmd = ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        images = [line.strip() for line in result.stdout.strip().split("\n") if line.strip() and "<none>" not in line]
        return {"images": images}
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
            # Summarize: only keep vulnerability counts + top findings per target
            summary = _summarize_trivy(parsed)
            return {"image": image, "summary": summary, "total_raw_chars": len(result.stdout)}
        except (json.JSONDecodeError, ValueError):
            return {"image": image, "raw": result.stdout[-4000:]}
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
            # Summarize: only counts + failed checks
            if isinstance(parsed, list):
                summary = []
                for section in parsed:
                    s = section.get("summary", {})
                    failed = [
                        {"id": c.get("check_id", ""), "name": (c.get("check_result", {}).get("evaluated_keys") or [c.get("check_id", "")])[0] if isinstance(c, dict) else str(c)}
                        for c in (section.get("results", {}).get("failed_checks", []))[:15]
                    ]
                    summary.append({"check_type": section.get("check_type", ""), "passed": s.get("passed", 0), "failed": s.get("failed", 0), "skipped": s.get("skipped", 0), "top_failures": failed})
                return {"path": target, "summary": summary}
            else:
                return {"path": target, "results": str(parsed)[:4000]}
        except (json.JSONDecodeError, ValueError):
            return {"path": target, "raw": result.stdout[-4000:]}
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
            "description": f"Run an nmap network scan against a target. For host-machine scans, use '{HOST_GATEWAY}' as the target. Use 'quick' for fast recon, 'stealth' for evasive, 'full' for all ports, 'vuln' for vulnerability scripts, 'udp' for UDP.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": f"IP, hostname, or CIDR range. Use '{HOST_GATEWAY}' to scan the Docker host machine."},
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
            "name": "list_docker_images",
            "description": "List all Docker images available on the host machine's Docker daemon. Call this BEFORE trivy_scan to discover which images can be scanned.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trivy_scan",
            "description": "Scan a Docker image for known CVEs and vulnerabilities using Trivy. Only works on images available on the host Docker daemon. Call list_docker_images first to see available images.",
            "parameters": {
                "type": "object",
                "properties": {
                    "image": {"type": "string", "description": "Docker image name:tag — must be an image present on the host. Use list_docker_images to discover available images."},
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
    "list_docker_images": list_docker_images,
    "checkov_scan": checkov_scan,
    "dns_lookup": dns_lookup,
    "check_ssl": check_ssl,
}

SYSTEM_PROMPT = f"""\
You are the Shield — a senior security engineer running inside an isolated Docker container.
You are scanning the HOST MACHINE that runs the Docker containers, NOT the container you run in.

You'll receive a mission and a strategic brief from the Tech Lead (Orchestrator).

TARGET RULES (MOST IMPORTANT):
- For ALL network/port scans (nmap), ALWAYS use "{HOST_GATEWAY}" as the target. \
  This resolves to the Docker host machine. NEVER scan container names or container IPs.
- For SSL/TLS checks on services exposed by the host, use "{HOST_GATEWAY}" as the host.
- For Trivy image scans, first call list_docker_images to see which images exist on the \
  host's Docker daemon, then scan those real image names. Do NOT guess image names.
- For DNS lookups, use the actual public domain/hostname if provided in the mission.
- If the mission provides a specific external IP or hostname, use that instead of {HOST_GATEWAY}.

CRITICAL RULES:
1. **Do ONLY what the mission asks.** If the mission says "scan port 80", scan port 80. \
   Do NOT also scan all ports, run trivy, or check containers unless explicitly asked.
2. **Minimum tool calls.** Call only the tools needed to answer the mission. If one scan \
   gives you the answer, STOP. Do not run additional scans "for completeness".
3. **No unsolicited analysis.** If not asked for kill chains, attack paths, or \
   remediations, don't include them. Answer what was asked.
4. **Adapt the brief.** The brief is guidance, not a script. If the brief suggests \
   more work than the mission requires, follow the mission.
5. **If something critical appears**, briefly flag it (one line), but don't investigate \
   unless that's part of the mission.

Output format — match the scope of the mission:
- Simple scan (e.g. "scan this host") → concise findings table, no essays
- Vulnerability assessment → Risk Level + Findings + Remediations
- Deep investigation → full pentest report style
"""

agent = AgentLoop(
    name="shield",
    system_prompt=SYSTEM_PROMPT,
    tools_schema=TOOLS_SCHEMA,
    tool_functions=TOOL_FUNCTIONS,
    base_url=os.getenv("LLM_BASE_URL"),
    api_key=os.getenv("LLM_API_KEY"),
)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
class GoalRequest(BaseModel):
    goal: str
    brief: dict | None = None
    depends_on: list[str] | None = None
    workspace_dir: str | None = None


@app.post("/agent/run")
async def run_agent(req: GoalRequest):
    try:
        return await agent.run(req.goal, brief=req.brief, depends_on=req.depends_on, workspace_dir=req.workspace_dir)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


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


@app.get("/config")
async def get_config():
    return {"name": agent.name, "system_prompt": agent.system_prompt}


class PromptUpdate(BaseModel):
    system_prompt: str | None = None


@app.post("/config/prompt")
async def update_prompt(req: PromptUpdate):
    agent.update_system_prompt(req.system_prompt)
    return {"updated": True, "using_default": req.system_prompt is None}


@app.get("/health/llm")
async def health_llm():
    from shared.agent_loop import ping_llm
    result = ping_llm(agent.llm, os.getenv("WORKER_LLM_MODEL", "unknown"))
    return {"service": "shield", "llm": result}
