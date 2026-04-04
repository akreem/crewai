"""
Sentinel Orchestrator — the Tech Lead.

The smartest LLM in the system. It does NOT touch tools. Instead it:
1. Receives a user command
2. Thinks strategically about what needs to happen
3. Crafts detailed briefs for each engineer agent — not step-by-step orders,
   but strategic context, objectives, suggested approaches, and priorities
4. Delegates to agents who have the domain expertise to execute
5. Reviews what comes back, passes intel between agents
6. Synthesizes a final executive summary
"""

import json
import os
import httpx
from fastapi import FastAPI
from pydantic import BaseModel
from openai import OpenAI

# -- Config --
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
ORCHESTRATOR_MODEL = os.getenv("ORCHESTRATOR_MODEL", os.getenv("LLM_MODEL", "qwen/qwen-2.5-72b-instruct"))
WATCHMAN_URL = os.getenv("WATCHMAN_URL", "http://watchman:6001")
SHIELD_URL = os.getenv("SHIELD_URL", "http://shield:6002")
SCRIBE_URL = os.getenv("SCRIBE_URL", "http://scribe:6003")

app = FastAPI(title="Sentinel Orchestrator")

llm = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

AGENTS = {
    "watchman": {"url": WATCHMAN_URL},
    "shield": {"url": SHIELD_URL},
    "scribe": {"url": SCRIBE_URL},
}

# ---------------------------------------------------------------------------
# Tool definitions — the Tech Lead delegates with BRIEFS
# ---------------------------------------------------------------------------
BRIEF_SCHEMA = {
    "type": "object",
    "description": "Strategic brief for the agent. NOT orders — context and guidance so the engineer can make good decisions.",
    "properties": {
        "objective": {
            "type": "string",
            "description": "What we're trying to achieve and WHY it matters. Give the engineer the full picture.",
        },
        "strategic_context": {
            "type": "string",
            "description": "Background: what prompted this, what other agents found, what the user cares about.",
        },
        "suggested_approach": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Your recommended approach — but the engineer can deviate if they find a better way.",
        },
        "targets": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Specific targets: IPs, container names, image names, paths.",
        },
        "priorities": {
            "type": "array",
            "items": {"type": "string"},
            "description": "What matters most and why. Helps the engineer triage.",
        },
        "constraints": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Scope limits, time limits, things to avoid.",
        },
        "output_format": {
            "type": "string",
            "description": "What you need back from them so you can coordinate the next step.",
        },
    },
    "required": ["objective"],
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "delegate_to_watchman",
            "description": "Brief the Watchman (SRE engineer). They save their work to the shared workspace. You get back a receipt with the file path and a short summary.",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "One-line mission statement"},
                    "brief": BRIEF_SCHEMA,
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "File paths in workspace of other agents' work that Watchman should read before starting.",
                    },
                },
                "required": ["goal", "brief"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delegate_to_shield",
            "description": "Brief the Shield (security engineer). They save their work to the shared workspace. You get back a receipt with the file path and a short summary.",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "One-line mission statement"},
                    "brief": BRIEF_SCHEMA,
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "File paths in workspace of other agents' work that Shield should read. E.g. Watchman's output file so Shield knows what containers/services to target.",
                    },
                },
                "required": ["goal", "brief"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delegate_to_scribe",
            "description": "Brief the Scribe (technical writer). They read other agents' work files from workspace and produce reports. You get back a receipt.",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "One-line mission statement"},
                    "brief": BRIEF_SCHEMA,
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "File paths of ALL agent work files the Scribe should read and document.",
                    },
                },
                "required": ["goal", "brief", "depends_on"],
            },
        },
    },
]

TOOL_ROUTING = {
    "delegate_to_watchman": "watchman",
    "delegate_to_shield": "shield",
    "delegate_to_scribe": "scribe",
}

SYSTEM_PROMPT = """\
You are the Sentinel Orchestrator — a Tech Lead managing a distributed team of \
specialist engineer agents for SRE, security, and documentation.

YOUR ROLE:
You are the strategic thinker. You have the best LLM. Your engineers have domain \
tools you don't. Your job is to give them the CONTEXT and OBJECTIVES they need to \
do great work — not to micromanage how they do it.

YOUR TEAM:
• Watchman (SRE Engineer) — tools: psutil, docker-py, container logs, process inspection.
• Shield (Security Engineer) — tools: nmap, trivy, checkov, SSL/DNS checks.
• Scribe (Technical Writer) — tools: file writing, JSON export, PDF conversion.

HOW COMMUNICATION WORKS:
Agents save their full work to the shared workspace as JSON files. When you delegate, \
you get back a RECEIPT: the file path + a short summary. You do NOT get the full data.

To have one agent build on another's work:
1. Delegate to Agent A → get receipt with output_file path
2. Delegate to Agent B with depends_on=[Agent A's output_file]
   → Agent B reads Agent A's work directly from the workspace

This keeps YOUR context window lean. You only see summaries. Agents see full data.

BRIEF WRITING:
1. Start with WHY — objective and why it matters.
2. Give strategic context — what prompted this, what the user cares about.
3. Suggest an approach — but trust them to adapt.
4. Specify targets — concrete IPs, container names, image names.
5. Set priorities — what matters most so they can triage.
6. Note constraints — scope limits, time, things to avoid.
7. Tell them what you need back.

COORDINATION:
• Watchman first → pass output_file to Shield via depends_on.
• Shield reads Watchman's work to know what to scan.
• Scribe gets depends_on=[watchman_file, shield_file] to produce reports.
• If a summary mentions something concerning, you can send a follow-up mission.

Scribe ALWAYS runs last to document everything — the system guarantees this.
After all agents report, provide YOUR executive summary as the Tech Lead.
"""


# ---------------------------------------------------------------------------
# Agent communication — lightweight: send brief, get receipt
# ---------------------------------------------------------------------------
async def delegate_to_agent(
    agent_name: str,
    goal: str,
    brief: dict | None = None,
    depends_on: list[str] | None = None,
) -> dict:
    base_url = AGENTS[agent_name]["url"]
    payload: dict = {"goal": goal}
    if brief:
        payload["brief"] = brief
    if depends_on:
        payload["depends_on"] = depends_on

    async with httpx.AsyncClient(timeout=600.0) as http:
        r = await http.post(f"{base_url}/agent/run", json=payload)
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
class CommandRequest(BaseModel):
    command: str


class CommandResponse(BaseModel):
    plan: str
    agent_reports: list
    summary: str


@app.post("/command", response_model=CommandResponse)
async def run_command(req: CommandRequest):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": req.command},
    ]

    agent_reports: list[dict] = []
    agent_files: list[str] = []   # track output file paths for depends_on
    plan_text = ""

    # ── Phase 1: Investigation (Watchman + Shield) ────────────────────
    investigation_tools = [t for t in TOOLS if "scribe" not in t["function"]["name"]]

    for _ in range(10):
        resp = llm.chat.completions.create(
            model=ORCHESTRATOR_MODEL,
            messages=messages,
            tools=investigation_tools,
            tool_choice="auto",
        )
        msg = resp.choices[0].message

        if msg.content and not plan_text:
            plan_text = msg.content

        messages.append(msg)

        if not msg.tool_calls:
            break

        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments)
            agent_name = TOOL_ROUTING[tc.function.name]

            try:
                receipt = await delegate_to_agent(
                    agent_name,
                    goal=args["goal"],
                    brief=args.get("brief"),
                    depends_on=args.get("depends_on"),
                )
                agent_reports.append({"agent": agent_name, **receipt})
                if receipt.get("output_file"):
                    agent_files.append(receipt["output_file"])
                # Only the lightweight receipt goes into the message history
                result_str = json.dumps(receipt, default=str)
            except Exception as e:
                error_report = {"agent": agent_name, "error": str(e)}
                agent_reports.append(error_report)
                result_str = json.dumps(error_report)

            messages.append(
                {"role": "tool", "tool_call_id": tc.id, "content": result_str}
            )

    # ── Phase 2: Documentation (Scribe — ALWAYS fires) ───────────────
    if agent_files:
        files_list = ", ".join(agent_files)
        scribe_planning_prompt = (
            f"All investigation agents have reported. Their work is saved at: {files_list}\n\n"
            "Write a brief for the Scribe to document everything. "
            "Use depends_on to point Scribe at those files. "
            "The Scribe will read the full data directly — you only need to "
            "tell them what to focus on, who the audience is, and what matters most."
        )
        messages.append({"role": "user", "content": scribe_planning_prompt})

        scribe_tools = [t for t in TOOLS if "scribe" in t["function"]["name"]]

        resp = llm.chat.completions.create(
            model=ORCHESTRATOR_MODEL,
            messages=messages,
            tools=scribe_tools,
            tool_choice="required",
        )
        msg = resp.choices[0].message
        messages.append(msg)

        if msg.tool_calls:
            tc = msg.tool_calls[0]
            args = json.loads(tc.function.arguments)

            # Guarantee all agent files are passed even if LLM forgets some
            depends_on = list(set((args.get("depends_on") or []) + agent_files))

            try:
                scribe_receipt = await delegate_to_agent(
                    "scribe",
                    goal=args["goal"],
                    brief=args.get("brief"),
                    depends_on=depends_on,
                )
                agent_reports.append({"agent": "scribe", **scribe_receipt})
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id,
                     "content": json.dumps(scribe_receipt, default=str)}
                )
            except Exception as e:
                agent_reports.append({"agent": "scribe", "error": str(e)})

    # ── Phase 3: Executive Summary (Tech Lead wraps up) ───────────────
    messages.append({
        "role": "user",
        "content": (
            "All agents have reported and documentation is written. "
            "Provide your executive summary as Tech Lead. Be concise. "
            "Highlight the most critical findings and recommended next steps."
        ),
    })

    resp = llm.chat.completions.create(
        model=ORCHESTRATOR_MODEL,
        messages=messages,
    )
    summary = resp.choices[0].message.content or ""

    return CommandResponse(plan=plan_text, agent_reports=agent_reports, summary=summary)


@app.get("/status")
async def agent_status():
    statuses = {}
    for name, info in AGENTS.items():
        try:
            async with httpx.AsyncClient(timeout=5.0) as http:
                r = await http.get(f"{info['url']}/health")
                statuses[name] = r.json()
        except Exception as e:
            statuses[name] = {"status": "unreachable", "error": str(e)}
    return statuses


@app.get("/health")
async def health():
    return {"status": "ok", "service": "orchestrator"}
