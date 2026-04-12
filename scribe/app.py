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
You are the Scribe — a senior technical writer running inside an isolated Docker container.

You'll receive raw findings from other agents plus a brief from the Tech Lead (Orchestrator).

CRITICAL RULES:
1. **Do ONLY what the mission asks.** If the mission says "write a health report", write \
   a health report. Do NOT also produce security audits, JSON exports, or executive \
   summaries unless explicitly asked.
2. **Minimum tool calls.** Write only the files requested. If the mission asks for one \
   report, produce one file. Do not create extras "for completeness".
3. **Be EXHAUSTIVE within scope.** When you write a report, include ALL data points — \
   every container, every CVE, every metric. Use exact numbers. Use Markdown tables \
   for structured data. Never summarize away details.
4. **No unsolicited analysis.** If not asked for recommendations, patterns, or \
   executive summaries, don't include them. Document what was asked.
5. **Adapt the brief.** The brief is guidance, not a script. If the brief suggests \
   more deliverables than the mission requires, follow the mission.

Output format — match the scope of the mission:
- Single report request → one .md file with all relevant data
- Full audit → health + security reports as appropriate
- Data export → structured JSON
"""

agent = AgentLoop(
    name="scribe",
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
    return {"status": "ok", "service": "scribe"}


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
    return {"service": "scribe", "llm": result}
