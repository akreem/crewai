"""
Watchman Agent — autonomous system reliability monitor.

Receives a high-level monitoring goal, reasons about what to check,
calls local tools, interprets results, and returns a complete analysis.
"""

import os
import psutil
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from shared.agent_loop import AgentLoop

app = FastAPI(title="Watchman Agent")

# Docker client — only works when socket is mounted
docker_client = None
try:
    import docker
    docker_client = docker.from_env()
except Exception:
    pass


# ---------------------------------------------------------------------------
# LOCAL TOOLS — these are what the agent's LLM can decide to call
# ---------------------------------------------------------------------------
async def check_cpu(**kwargs) -> dict:
    cpu_per_core = psutil.cpu_percent(interval=1, percpu=True)
    avg = sum(cpu_per_core) / len(cpu_per_core) if cpu_per_core else 0
    return {
        "cpu_average_percent": round(avg, 1),
        "per_core": cpu_per_core,
        "core_count": len(cpu_per_core),
        "load_avg": [round(x, 2) for x in psutil.getloadavg()],
    }


async def check_memory(**kwargs) -> dict:
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return {
        "ram_used_gb": round(mem.used / (1024**3), 2),
        "ram_total_gb": round(mem.total / (1024**3), 2),
        "ram_percent": mem.percent,
        "swap_used_gb": round(swap.used / (1024**3), 2),
        "swap_percent": swap.percent,
    }


async def check_disk(**kwargs) -> dict:
    partitions = []
    for p in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(p.mountpoint)
            partitions.append({
                "mount": p.mountpoint,
                "total_gb": round(usage.total / (1024**3), 2),
                "used_gb": round(usage.used / (1024**3), 2),
                "percent": usage.percent,
            })
        except PermissionError:
            pass
    return {"partitions": partitions}


async def check_network_io(**kwargs) -> dict:
    io = psutil.net_io_counters()
    return {
        "bytes_sent_mb": round(io.bytes_sent / (1024**2), 2),
        "bytes_recv_mb": round(io.bytes_recv / (1024**2), 2),
        "packets_sent": io.packets_sent,
        "packets_recv": io.packets_recv,
        "errors_in": io.errin,
        "errors_out": io.errout,
        "drops_in": io.dropin,
        "drops_out": io.dropout,
    }


async def list_containers(**kwargs) -> dict:
    if not docker_client:
        return {"error": "Docker socket not available"}
    containers = []
    for c in docker_client.containers.list(all=True):
        info = {
            "name": c.name,
            "image": c.image.tags[0] if c.image.tags else c.image.id[:12],
            "status": c.status,
        }
        if c.status == "running":
            try:
                raw = c.stats(stream=False)
                cpu_d = (
                    raw["cpu_stats"]["cpu_usage"]["total_usage"]
                    - raw["precpu_stats"]["cpu_usage"]["total_usage"]
                )
                sys_d = (
                    raw["cpu_stats"]["system_cpu_usage"]
                    - raw["precpu_stats"]["system_cpu_usage"]
                )
                n_cpus = len(raw["cpu_stats"]["cpu_usage"].get("percpu_usage", [1]))
                info["cpu_percent"] = round((cpu_d / sys_d) * n_cpus * 100, 2) if sys_d > 0 else 0.0
                info["memory_mb"] = round(raw["memory_stats"].get("usage", 0) / (1024**2), 2)
            except Exception:
                pass
        containers.append(info)
    return {"containers": containers}


async def get_container_logs(container_name: str = "", lines: int = 100, **kwargs) -> dict:
    if not docker_client:
        return {"error": "Docker socket not available"}
    try:
        container = docker_client.containers.get(container_name)
        logs = container.logs(tail=lines, timestamps=True).decode("utf-8", errors="replace")
        log_lines = logs.strip().split("\n") if logs.strip() else []
        error_keywords = ("error", "fatal", "panic", "critical", "exception", "traceback")
        errors = [l for l in log_lines if any(kw in l.lower() for kw in error_keywords)]
        warnings = [l for l in log_lines if "warn" in l.lower()]
        return {
            "container": container_name,
            "total_lines": len(log_lines),
            "error_count": len(errors),
            "warning_count": len(warnings),
            "errors": errors[-20:],
            "warnings": warnings[-10:],
            "recent_logs": log_lines[-20:],
        }
    except Exception as e:
        return {"error": str(e)}


async def get_top_processes(count: int = 10, **kwargs) -> dict:
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            procs.append(p.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    procs.sort(key=lambda x: x.get("cpu_percent", 0) or 0, reverse=True)
    return {"top_by_cpu": procs[:count]}


# ---------------------------------------------------------------------------
# Tool schemas for the LLM
# ---------------------------------------------------------------------------
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "check_cpu",
            "description": "Get CPU usage per core, average, and load average",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_memory",
            "description": "Get RAM and swap usage",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_disk",
            "description": "Get disk usage for all mounted partitions",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_network_io",
            "description": "Get network I/O counters — bytes, packets, errors, drops",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_containers",
            "description": "List all Docker containers with status, CPU, and memory usage",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_container_logs",
            "description": "Fetch and analyze logs from a specific Docker container. Identifies errors and warnings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "container_name": {"type": "string", "description": "Name of the Docker container"},
                    "lines": {"type": "integer", "description": "Number of recent log lines to fetch", "default": 100},
                },
                "required": ["container_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_top_processes",
            "description": "Get top processes by CPU usage",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": "How many processes to return", "default": 10},
                },
                "required": [],
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "check_cpu": check_cpu,
    "check_memory": check_memory,
    "check_disk": check_disk,
    "check_network_io": check_network_io,
    "list_containers": list_containers,
    "get_container_logs": get_container_logs,
    "get_top_processes": get_top_processes,
}

SYSTEM_PROMPT = """\
You are the Watchman — a senior SRE engineer running inside an isolated Docker container.

You'll receive a mission and a strategic brief from the Tech Lead (Orchestrator).

CRITICAL RULES:
1. **Do ONLY what the mission asks.** If the mission says "list containers and images", \
   do exactly that — call list_containers and return the result. Do NOT also check CPU, \
   memory, disk, network, or logs unless explicitly asked.
2. **Minimum tool calls.** Call only the tools needed to answer the mission. If one tool \
   call gives you the answer, STOP. Do not call additional tools "for completeness".
3. **No unsolicited analysis.** If not asked for recommendations, security notes, or \
   health assessments, don't include them. Answer what was asked.
4. **Adapt the brief.** The brief is guidance, not a script. If the brief suggests \
   more work than the mission requires, follow the mission.
5. **If something looks off**, briefly flag it (one line), but don't investigate unless \
   that's part of the mission.

Output format — match the scope of the mission:
- Simple query (e.g. "list containers") → concise table or list, no essays
- Health check → Status + Diagnosis + Key Findings + Recommendations
- Deep investigation → full incident report style
"""

agent = AgentLoop(
    name="watchman",
    system_prompt=SYSTEM_PROMPT,
    tools_schema=TOOLS_SCHEMA,
    tool_functions=TOOL_FUNCTIONS,
    base_url=os.getenv("LLM_BASE_URL"),
    api_key=os.getenv("LLM_API_KEY"),
)


# ---------------------------------------------------------------------------
# API — single endpoint: receive goal, run agent loop, return analysis
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
    return {"status": "ok", "service": "watchman", "docker": docker_client is not None}


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
    return {"service": "watchman", "llm": result}
