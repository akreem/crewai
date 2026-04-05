"""
Reusable autonomous agent loop.

Every worker container uses this same loop:
1. Receive a goal + structured brief from the orchestrator
2. The brief gives strategic context (crafted by the smarter orchestrator LLM)
3. If other agents' work is referenced, read it from the shared workspace (not from context)
4. Worker LLM reasons about what tools to call
5. Execute local tools, interpret results, iterate
6. Save full work output to workspace as JSON
7. Return a lightweight receipt to the orchestrator (file path + short summary)
"""

import json
import os
import time
from datetime import datetime, timezone
from typing import Callable
from openai import OpenAI

DEFAULT_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
DEFAULT_BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
WORKER_LLM_MODEL = os.getenv("WORKER_LLM_MODEL", os.getenv("LLM_MODEL", "qwen/qwen-2.5-72b-instruct"))
WORKSPACE = os.getenv("WORKSPACE_DIR", "/app/workspace")


def create_llm(base_url: str | None = None, api_key: str | None = None):
    return OpenAI(
        base_url=base_url or DEFAULT_BASE_URL,
        api_key=api_key or DEFAULT_API_KEY,
        timeout=120.0,
        max_retries=2,
    )


def read_agent_work(file_path: str, workspace: str | None = None) -> dict | None:
    """Read another agent's saved work from the shared workspace."""
    ws = workspace or WORKSPACE
    full_path = file_path if file_path.startswith("/") else os.path.join(ws, file_path)
    if not os.path.exists(full_path):
        return None
    with open(full_path, "r") as f:
        return json.load(f)


class AgentLoop:
    """
    An autonomous agent that receives a goal + strategic brief,
    reasons with an LLM, calls local tools, and iterates until done.

    Saves full work to the shared workspace. Returns only a receipt
    to the orchestrator — keeps the orchestrator's context window lean.
    """

    def __init__(
        self,
        name: str,
        system_prompt: str,
        tools_schema: list[dict],
        tool_functions: dict[str, Callable],
        max_iterations: int = 15,
        base_url: str | None = None,
        api_key: str | None = None,
    ):
        self.name = name
        self.system_prompt = system_prompt
        self.tools_schema = tools_schema
        self.tool_functions = tool_functions
        self.max_iterations = max_iterations
        self.llm = create_llm(base_url=base_url, api_key=api_key)

    async def run(
        self,
        goal: str,
        brief: dict | None = None,
        depends_on: list[str] | None = None,
        workspace_dir: str | None = None,
    ) -> dict:
        """
        Execute the full agent loop.

        Args:
            goal: High-level objective.
            brief: Strategic context from the orchestrator's LLM.
            depends_on: File paths in the workspace of other agents' work
                        to read before starting. Replaces passing raw data.

        Returns:
            Lightweight receipt:
            {
                "agent": str,
                "output_file": str,       # where full work is saved
                "summary": str,           # short summary for orchestrator
                "tool_calls_made": int,
            }
        """
        # Effective workspace for this run
        effective_workspace = workspace_dir or WORKSPACE

        # Build the user message
        parts = [f"# Mission\n{goal}"]

        if brief:
            parts.append("\n# Strategic Brief (from Tech Lead)")
            if brief.get("objective"):
                parts.append(f"\n## Objective & Why\n{brief['objective']}")
            if brief.get("strategic_context"):
                parts.append(f"\n## Situational Context\n{brief['strategic_context']}")
            if brief.get("suggested_approach"):
                parts.append("\n## Suggested Approach (adapt as you see fit)")
                for i, step in enumerate(brief["suggested_approach"], 1):
                    parts.append(f"{i}. {step}")
            if brief.get("targets"):
                parts.append(f"\n## Known Targets\n{', '.join(str(t) for t in brief['targets'])}")
            if brief.get("priorities"):
                parts.append("\n## Priorities")
                for p in brief["priorities"]:
                    parts.append(f"- {p}")
            if brief.get("constraints"):
                parts.append("\n## Constraints")
                for c in brief["constraints"]:
                    parts.append(f"- {c}")
            if brief.get("output_format"):
                parts.append(f"\n## What The Team Needs Back\n{brief['output_format']}")

        # Load referenced agent work from workspace files (not from context payload)
        if depends_on:
            for dep_path in depends_on:
                dep_data = read_agent_work(dep_path, workspace=effective_workspace)
                if dep_data:
                    agent_name = dep_data.get("agent", "unknown")
                    parts.append(f"\n# Prior Work: {agent_name} ({dep_path})")
                    # Only inject the analysis + key data, not raw tool dumps
                    if dep_data.get("analysis"):
                        parts.append(f"\n## Their Analysis\n{dep_data['analysis']}")
                    if dep_data.get("key_data"):
                        parts.append(f"\n## Key Data\n```json\n{json.dumps(dep_data['key_data'], default=str, indent=2)}\n```")
                else:
                    parts.append(f"\n# Prior Work: {dep_path} — FILE NOT FOUND (proceed without it)")

        user_msg = "\n".join(parts)

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_msg},
        ]

        all_tool_results: list[dict] = []

        for i in range(self.max_iterations):
            kwargs = {
                "model": WORKER_LLM_MODEL,
                "messages": messages,
            }
            if self.tools_schema:
                kwargs["tools"] = self.tools_schema
                kwargs["tool_choice"] = "auto"

            # LLM call with retry on transient errors
            resp = None
            for llm_attempt in range(3):
                try:
                    resp = self.llm.chat.completions.create(**kwargs)
                    break
                except Exception as e:
                    print(f"[{self.name}] LLM call attempt {llm_attempt+1} failed: {e}")
                    if llm_attempt < 2:
                        time.sleep(3 * (llm_attempt + 1))
                    else:
                        raise RuntimeError(f"LLM call failed after 3 attempts: {e}") from e

            msg = resp.choices[0].message
            messages.append(msg)

            if not msg.tool_calls:
                break

            for tc in msg.tool_calls:
                fn_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                if fn_name in self.tool_functions:
                    try:
                        result = await self.tool_functions[fn_name](**args, _workspace_dir=effective_workspace)
                    except Exception as e:
                        result = {"error": str(e)}
                else:
                    result = {"error": f"Unknown tool: {fn_name}"}

                result_str = json.dumps(result, default=str)
                all_tool_results.append(
                    {"tool": fn_name, "args": args, "result": result}
                )

                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": result_str}
                )

        # Extract final analysis from last assistant message
        analysis = ""
        for m in reversed(messages):
            content = m.content if hasattr(m, "content") else m.get("content")
            role = m.role if hasattr(m, "role") else m.get("role")
            if role == "assistant" and content:
                analysis = content
                break

        # ── Save full work to workspace ──────────────────────────────
        os.makedirs(effective_workspace, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_filename = f"{self.name}_{ts}.json"
        output_path = os.path.join(effective_workspace, output_filename)

        # key_data = the important structured bits other agents might need
        # (e.g. container list, vulnerability findings) — NOT the full raw dumps
        key_data = {}
        for tr in all_tool_results:
            if "error" not in tr.get("result", {}):
                key_data[tr["tool"]] = tr["result"]

        full_output = {
            "agent": self.name,
            "goal": goal,
            "timestamp": ts,
            "analysis": analysis,
            "key_data": key_data,
            "tool_calls_made": len(all_tool_results),
            "raw_tool_results": all_tool_results,
        }

        with open(output_path, "w") as f:
            json.dump(full_output, f, indent=2, default=str)

        # ── Return receipt with full analysis ────────────────────────
        return {
            "agent": self.name,
            "output_file": output_filename,
            "summary": analysis,
            "tool_calls_made": len(all_tool_results),
        }
