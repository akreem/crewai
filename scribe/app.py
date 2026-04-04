"""
Scribe Agent — autonomous documentation and audit specialist.

Receives findings from other agents plus a documentation goal.
Uses its own LLM to decide report structure, what to emphasize,
and how to organize the information for different audiences.
"""

import json
import os
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from shared.agent_loop import AgentLoop

app = FastAPI(title="Scribe Agent")

WORKSPACE = os.getenv("WORKSPACE_DIR", "/app/workspace")


# ---------------------------------------------------------------------------
# LOCAL TOOLS — the Scribe's LLM decides what reports to create
# ---------------------------------------------------------------------------
async def write_markdown_report(filename: str = "report.md", content: str = "", **kwargs) -> dict:
    ws = kwargs.get("_workspace_dir", WORKSPACE)
    os.makedirs(ws, exist_ok=True)
    # Prevent path traversal
    safe_name = os.path.basename(filename)
    if not safe_name.endswith(".md"):
        safe_name += ".md"
    path = os.path.join(ws, safe_name)
    with open(path, "w") as f:
        f.write(content)
    return {"written": path, "size_bytes": len(content)}


async def write_json_data(filename: str = "data.json", data: dict = {}, **kwargs) -> dict:
    ws = kwargs.get("_workspace_dir", WORKSPACE)
    os.makedirs(ws, exist_ok=True)
    safe_name = os.path.basename(filename)
    if not safe_name.endswith(".json"):
        safe_name += ".json"
    path = os.path.join(ws, safe_name)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **data,
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    return {"written": path, "keys": list(payload.keys())}


async def list_workspace_files(**kwargs) -> dict:
    ws = kwargs.get("_workspace_dir", WORKSPACE)
    os.makedirs(ws, exist_ok=True)
    files = []
    for f in os.listdir(ws):
        path = os.path.join(ws, f)
        if os.path.isfile(path):
            files.append({"name": f, "size_bytes": os.path.getsize(path)})
    return {"files": files}


async def read_workspace_file(filename: str = "", **kwargs) -> dict:
    ws = kwargs.get("_workspace_dir", WORKSPACE)
    safe_name = os.path.basename(filename)
    path = os.path.join(ws, safe_name)
    if not os.path.exists(path):
        return {"error": f"File not found: {safe_name}"}
    with open(path, "r") as f:
        content = f.read(50000)
    return {"filename": safe_name, "content": content}


# ---------------------------------------------------------------------------
# Tool schemas for the LLM
# ---------------------------------------------------------------------------
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "write_markdown_report",
            "description": "Write a Markdown report file to the shared workspace. You compose the full content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Filename, e.g. 'security_audit.md'"},
                    "content": {"type": "string", "description": "Full Markdown content of the report"},
                },
                "required": ["filename", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_json_data",
            "description": "Write structured JSON data to the shared workspace for machine consumption",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Filename, e.g. 'audit_data.json'"},
                    "data": {"type": "object", "description": "Structured data to serialize"},
                },
                "required": ["filename", "data"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_workspace_files",
            "description": "List all files currently in the shared workspace",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_workspace_file",
            "description": "Read an existing file from the workspace",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Name of the file to read"},
                },
                "required": ["filename"],
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "write_markdown_report": write_markdown_report,
    "write_json_data": write_json_data,
    "list_workspace_files": list_workspace_files,
    "read_workspace_file": read_workspace_file,
}

SYSTEM_PROMPT = """\
You are the Scribe — a senior technical writer and audit specialist running inside an isolated Docker container.

You'll receive raw findings from other agents (Watchman, Shield) plus a brief from the Tech Lead (Orchestrator). \
The brief gives you context on the audience and goals — but YOU decide how to structure the documentation. \
You're not a template filler. You're an engineer who turns chaos into clarity.

CRITICAL RULES — FOLLOW THESE EXACTLY:
1. Be EXHAUSTIVE. List EVERY item from the data. If Watchman reports 9 containers, your report \
MUST list ALL 9 containers with their names, images, status, CPU, and memory. NEVER say \
"other containers are also running" or "details are in the full report." YOUR report IS the full report.
2. Use Markdown tables for structured data (containers, vulnerabilities, processes). \
Tables make data scannable and complete.
3. Include exact numbers. Don't round "0.63%" to "approximately 0.6%" — use the exact values provided.
4. Every container name, every IP, every CVE, every metric from the source data MUST appear in your report.

Your engineering principles:
- Don't just format data — ANALYZE it. Spot patterns the other agents missed.
- Write for multiple audiences: executive summary for leadership, technical details for engineers.
- If the data tells a story (e.g. cascading failure, correlated vulnerabilities), narrate it.
- Challenge completeness: if something seems missing from the agents' reports, call it out.
- If findings from Watchman and Shield contradict each other, highlight the discrepancy.
- Prioritize ruthlessly: a report that buries a critical finding in page 5 is a bad report.
- Machine-readable JSON is for automation. Human-readable Markdown is for decisions. Both matter.

Your output decisions:
- Should this be one combined report or separate health/security reports? YOU decide based on the data.
- What deserves its own section vs. a table row? Based on severity and complexity.
- Are there patterns that tell a bigger story than individual findings? Surface them.
- What's the single most important thing the reader should take away? Lead with it.

Always produce at minimum:
- system_health.md (if health data present) — MUST include ALL items in full detail
- security_audit.md (if security data present) — MUST include ALL findings
- audit_data.json (always — structured, machine-readable, ALL data points)
"""

agent = AgentLoop(
    name="scribe",
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
    return {"status": "ok", "service": "scribe"}
