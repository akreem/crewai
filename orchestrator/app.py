"""
Sentinel Orchestrator — the Tech Lead.

The smartest LLM in the system. It does NOT touch tools. Instead it:
1. Receives a user command
2. Chats with the user to clarify objectives, scope, targets
3. Presents a plan and waits for user confirmation
4. Only THEN delegates to agents
5. Reviews what comes back, passes intel between agents
6. Synthesizes a final executive summary
"""

import json
import os
import uuid
import asyncio
import hashlib
import hmac
import time
import httpx
import jwt
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, Depends, Cookie
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel
from openai import OpenAI

# -- Config --
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
ORCHESTRATOR_API_KEY = os.getenv("ORCHESTRATOR_API_KEY", OPENROUTER_API_KEY)
ORCHESTRATOR_BASE_URL = os.getenv("ORCHESTRATOR_BASE_URL", os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1"))
ORCHESTRATOR_MODEL = os.getenv("ORCHESTRATOR_MODEL", os.getenv("LLM_MODEL", "qwen/qwen-2.5-72b-instruct"))
WATCHMAN_URL = os.getenv("WATCHMAN_URL", "http://watchman:6001")
SHIELD_URL = os.getenv("SHIELD_URL", "http://shield:6002")
SCRIBE_URL = os.getenv("SCRIBE_URL", "http://scribe:6003")

import re
_CONFIRM_RE = re.compile(
    r'^\s*(go+|yes|y|do\s*it|execute|start|proceed|run\s*it|let\'?s\s*go|'
    r'approved|confirmed?|yep|yeah|ok|okay|sure|absolutely|affirmative|roger)'
    r'[\s!. ]*$',
    re.IGNORECASE,
)

def _is_confirmation(text: str) -> bool:
    """Check if a user message is a confirmation to execute."""
    return bool(_CONFIRM_RE.match(text.strip()))

app = FastAPI(title="Sentinel Orchestrator")

DASHBOARD_PATH = os.getenv("DASHBOARD_PATH", "/app/dashboard/index.html")
LOGIN_PATH = os.getenv("LOGIN_PATH", "/app/dashboard/login.html")

# -- Auth config --
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "sentinel")
AUTH_SECRET = os.getenv("AUTH_SECRET", hashlib.sha256(AUTH_PASSWORD.encode()).hexdigest())
AUTH_TOKEN_HOURS = int(os.getenv("AUTH_TOKEN_HOURS", "72"))

# Paths that don't require auth
_PUBLIC_PATHS = {"/auth/login", "/auth/check", "/health", "/login"}


def _create_token() -> str:
    return jwt.encode(
        {"exp": int(time.time()) + AUTH_TOKEN_HOURS * 3600, "sub": "user"},
        AUTH_SECRET,
        algorithm="HS256",
    )


def _verify_token(token: str) -> bool:
    try:
        jwt.decode(token, AUTH_SECRET, algorithms=["HS256"])
        return True
    except Exception:
        return False


class LoginRequest(BaseModel):
    password: str


@app.post("/auth/login")
async def auth_login(req: LoginRequest):
    if not hmac.compare_digest(req.password, AUTH_PASSWORD):
        raise HTTPException(status_code=401, detail="Wrong password")
    token = _create_token()
    resp = JSONResponse({"ok": True})
    resp.set_cookie(
        key="sentinel_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=AUTH_TOKEN_HOURS * 3600,
        path="/",
    )
    return resp


@app.post("/auth/logout")
async def auth_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("sentinel_token", path="/")
    return resp


@app.get("/auth/check")
async def auth_check(sentinel_token: str = Cookie(None)):
    if sentinel_token and _verify_token(sentinel_token):
        return {"authenticated": True}
    return {"authenticated": False}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # Public paths bypass auth
    if path in _PUBLIC_PATHS or path.startswith("/auth/"):
        return await call_next(request)
    # Check cookie
    token = request.cookies.get("sentinel_token")
    if token and _verify_token(token):
        return await call_next(request)
    # For API calls return 401, for pages redirect to login
    if path.startswith("/api/") or path.startswith("/chat/sessions") or path.startswith("/ws/") or path.startswith("/status") or path.startswith("/workspace"):
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    # Serve login page for unauthenticated page requests
    if os.path.exists(LOGIN_PATH):
        return FileResponse(LOGIN_PATH, media_type="text/html")
    return JSONResponse({"detail": "Not authenticated"}, status_code=401)


@app.get("/login")
async def login_page():
    return FileResponse(LOGIN_PATH, media_type="text/html")


@app.get("/")
async def dashboard():
    return FileResponse(DASHBOARD_PATH, media_type="text/html")


@app.get("/chat/{session_id:path}")
async def dashboard_chat(session_id: str):
    return FileResponse(DASHBOARD_PATH, media_type="text/html")

llm = OpenAI(
    base_url=ORCHESTRATOR_BASE_URL,
    api_key=ORCHESTRATOR_API_KEY,
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
• Scribe (Technical Writer) — tools: Markdown report writing, JSON export. Scribe ALWAYS runs after investigation agents.

CONVERSATION FLOW — THIS IS CRITICAL:

1. UNDERSTAND — Read the user's message. If their intent is clear (e.g. "health check \
all containers", "scan my network", "full audit"), DO NOT ask clarifying questions. \
Go straight to presenting a plan. Only ask questions if the request is genuinely \
ambiguous or missing critical info you can't reasonably assume (e.g. no target IP for \
a network scan). When in doubt, assume broad scope and proceed. \
NEVER ask more than ONE round of questions. NEVER ask about "depth" or "scope" \
if the user already said "all" or gave a clear directive.
2. PLAN — Present a SHORT execution plan (3-5 lines max):
   - Which agents and what they'll do
   - Expected output
   NOTE: Scribe is NEVER optional. Always include Scribe in your plan.
3. CONFIRM — End with: "Say **go** to proceed."
4. EXECUTE — When the user confirms, IMMEDIATELY call the delegation tools. \
Do NOT present the plan again. Do NOT ask for confirmation a second time. \
Any message like "go", "yes", "do it", "execute", "start", "proceed", "run it", \
"let's go", "approved", "confirmed", "yep", "y", "ok", "go!!", "goooo", or similar \
means the user has confirmed. CALL THE TOOLS IMMEDIATELY. Even if the message \
contains extra words alongside a confirmation, EXECUTE.

NEVER call delegation tools before the user confirms. Always present a plan first.
NEVER re-present the plan after the user says go. Execute it.
NEVER ask multiple rounds of clarifying questions. One round max, and only if truly needed.
If the user just says "hey" or something casual, respond conversationally and ask \
what they need help with.

HOW COMMUNICATION WORKS:
Agents save their full work to the shared workspace as JSON files. When you delegate, \
you get back a RECEIPT: the file path + a short summary. You do NOT get the full data.

To have one agent build on another's work:
1. Delegate to Agent A → get receipt with output_file path
2. Delegate to Agent B with depends_on=[Agent A's output_file]
   → Agent B reads Agent A's work directly from the workspace

BRIEF WRITING (when you execute):
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
• Scribe ALWAYS runs last with depends_on=[watchman_file, shield_file] to produce reports.
• Scribe is MANDATORY — never skip it. The investigation agents return raw data; the Scribe explains and documents it for humans.
• If a summary mentions something concerning, you can send a follow-up mission.

CRITICAL RULES:
• NEVER fabricate, invent, or hallucinate data. If an agent returns an error, report the error honestly.
• If you don't have real data from an agent, say so. Do NOT make up container names, IPs, CVEs, or metrics.
• Your executive summary must ONLY reference data that actually came back from agents.
• If all agents failed, your summary should say they failed and suggest retrying.

After all agents report, provide YOUR executive summary as the Tech Lead.
"""


# ---------------------------------------------------------------------------
# Session store — persisted to workspace volume as JSON
# ---------------------------------------------------------------------------
WORKSPACE_DIR = os.getenv("WORKSPACE_DIR", "/app/workspace")
SESSIONS_DIR = os.path.join(WORKSPACE_DIR, ".sessions")
sessions: dict[str, dict] = {}


def _session_path(sid: str) -> str:
    return os.path.join(SESSIONS_DIR, f"{sid}.json")


def _save_session(sid: str):
    """Persist session to disk."""
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    session = sessions[sid]
    # Filter out system messages and non-serializable content for storage
    saveable_messages = []
    for m in session["messages"]:
        if hasattr(m, "model_dump"):
            d = m.model_dump(exclude_none=True)
        elif isinstance(m, dict):
            d = dict(m)
        else:
            continue
        if d.get("role") == "system":
            continue
        # Strip tool_calls objects that aren't JSON-friendly
        if "tool_calls" in d and d["tool_calls"]:
            d["tool_calls"] = [
                {"id": tc.get("id", ""), "function": {"name": tc.get("function", {}).get("name", ""), "arguments": tc.get("function", {}).get("arguments", "")}}
                if isinstance(tc, dict) else
                {"id": tc.id, "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in d["tool_calls"]
            ]
        saveable_messages.append(d)

    data = {
        "session_id": sid,
        "title": session.get("title", ""),
        "created": session.get("created", ""),
        "updated": session.get("updated", ""),
        "phase": session.get("phase", "chat"),
        "agent_reports": session.get("agent_reports", []),
        "messages": saveable_messages,
    }
    with open(_session_path(sid), "w") as f:
        json.dump(data, f, indent=2, default=str)


def _load_session(sid: str) -> dict | None:
    """Load session from disk."""
    path = _session_path(sid)
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        data = json.load(f)
    return data


def _load_all_sessions():
    """Load session metadata from disk on startup."""
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    for fname in os.listdir(SESSIONS_DIR):
        if not fname.endswith(".json"):
            continue
        sid = fname[:-5]
        if sid in sessions:
            continue
        data = _load_session(sid)
        if data:
            messages = [{"role": "system", "content": SYSTEM_PROMPT}] + data.get("messages", [])
            sessions[sid] = {
                "messages": messages,
                "agent_reports": data.get("agent_reports", []),
                "agent_files": [],
                "phase": data.get("phase", "chat"),
                "title": data.get("title", ""),
                "created": data.get("created", ""),
                "updated": data.get("updated", ""),
            }


# Load existing sessions on startup
_load_all_sessions()


def get_or_create_session(session_id: str | None) -> tuple[str, list]:
    from datetime import datetime, timezone
    if session_id and session_id in sessions:
        sessions[session_id]["updated"] = datetime.now(timezone.utc).isoformat()
        return session_id, sessions[session_id]["messages"]
    sid = session_id or str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    sessions[sid] = {
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}],
        "agent_reports": [],
        "agent_files": [],
        "phase": "chat",
        "title": "",
        "created": now,
        "updated": now,
    }
    return sid, sessions[sid]["messages"]


# ---------------------------------------------------------------------------
# Agent communication — lightweight: send brief, get receipt
# ---------------------------------------------------------------------------
async def delegate_to_agent(
    agent_name: str,
    goal: str,
    brief: dict | None = None,
    depends_on: list[str] | None = None,
    workspace_dir: str | None = None,
    retries: int = 3,
) -> dict:
    base_url = AGENTS[agent_name]["url"]
    payload: dict = {"goal": goal}
    if brief:
        payload["brief"] = brief
    if depends_on:
        payload["depends_on"] = depends_on
    if workspace_dir:
        payload["workspace_dir"] = workspace_dir

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            async with httpx.AsyncClient(timeout=600.0) as http:
                r = await http.post(f"{base_url}/agent/run", json=payload)
                r.raise_for_status()
                return r.json()
        except Exception as e:
            last_error = e
            if attempt < retries:
                wait = attempt * 5  # 5s, 10s
                print(f"[RETRY] {agent_name} attempt {attempt} failed: {e}. Retrying in {wait}s...")
                await asyncio.sleep(wait)
            else:
                print(f"[FAIL] {agent_name} failed after {retries} attempts: {e}")

    raise last_error


# ---------------------------------------------------------------------------
# API — conversational chat with confirm-to-execute
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    phase: str            # "chat", "executing", "done"
    agent_reports: list = []


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    sid, messages = get_or_create_session(req.session_id)
    session = sessions[sid]

    # Auto-title from first user message
    if not session.get("title"):
        session["title"] = req.message[:80]

    messages.append({"role": "user", "content": req.message})
    _save_session(sid)

    # ── Chat phase: LLM responds, force tool use on confirmation ──────
    # If user confirmed ("go", "yes", etc.), force the LLM to call tools
    confirmed = _is_confirmation(req.message)
    resp = llm.chat.completions.create(
        model=ORCHESTRATOR_MODEL,
        messages=messages,
        tools=TOOLS,
        tool_choice="required" if confirmed else "auto",
    )
    msg = resp.choices[0].message
    messages.append(msg)

    # If no tool calls → just chatting / presenting plan
    if not msg.tool_calls:
        session["phase"] = "chat"
        _save_session(sid)
        return ChatResponse(
            session_id=sid,
            reply=msg.content or "",
            phase="chat",
            agent_reports=[],
        )

    # ── Execution phase: LLM decided to call tools (user confirmed) ──
    session["phase"] = "executing"
    agent_reports = session["agent_reports"]
    agent_files = session["agent_files"]

    # Create a per-session workspace directory for agent collaboration
    session_workspace = os.path.join(WORKSPACE_DIR, f"chat_{sid[:8]}")
    os.makedirs(session_workspace, exist_ok=True)
    session["workspace_dir"] = session_workspace

    # Process tool calls in a loop
    for _ in range(15):
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
                    workspace_dir=session_workspace,
                )
                agent_reports.append({"agent": agent_name, **receipt})
                if receipt.get("output_file"):
                    agent_files.append(receipt["output_file"])
                result_str = json.dumps(receipt, default=str)
            except Exception as e:
                error_report = {"agent": agent_name, "error": str(e)}
                agent_reports.append(error_report)
                result_str = json.dumps(error_report)

            messages.append(
                {"role": "tool", "tool_call_id": tc.id, "content": result_str}
            )

        # Let LLM continue (may delegate more or finish)
        resp = llm.chat.completions.create(
            model=ORCHESTRATOR_MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )
        msg = resp.choices[0].message
        messages.append(msg)

    # ── Documentation phase: Scribe writes up everything ─────────────
    # Scribe ALWAYS runs — even if some agents failed, it documents what we got
    if agent_files:
        files_list = ", ".join(agent_files)
        scribe_prompt = (
            f"All investigation agents have reported. Their work is saved at: {files_list}\n\n"
            "Write a brief for the Scribe to document everything. "
            "Use depends_on to point Scribe at those files."
        )
    else:
        scribe_prompt = (
            "Investigation agents encountered errors and produced no output files. "
            "Delegate to the Scribe to write an incident report documenting the failures "
            "and what was attempted. The Scribe should note which agents failed and recommend retrying."
        )
    messages.append({"role": "user", "content": scribe_prompt, "_internal": True})

    scribe_tools = [t for t in TOOLS if "scribe" in t["function"]["name"]]
    resp = llm.chat.completions.create(
        model=ORCHESTRATOR_MODEL,
        messages=messages,
        tools=scribe_tools,
        tool_choice="auto",
    )
    msg = resp.choices[0].message
    messages.append(msg)

    if msg.tool_calls:
        tc = msg.tool_calls[0]
        args = json.loads(tc.function.arguments)
        depends_on = list(set((args.get("depends_on") or []) + agent_files))

        try:
            scribe_receipt = await delegate_to_agent(
                "scribe", goal=args["goal"],
                brief=args.get("brief"), depends_on=depends_on,
                workspace_dir=session_workspace,
            )
            agent_reports.append({"agent": "scribe", **scribe_receipt})
            messages.append(
                {"role": "tool", "tool_call_id": tc.id,
                 "content": json.dumps(scribe_receipt, default=str)}
            )
        except Exception as e:
            agent_reports.append({"agent": "scribe", "error": str(e)})

    # ── Executive summary ────────────────────────────────────────────
    # Check if ALL investigation agents failed (no real data at all)
    investigation_reports = [r for r in agent_reports if r.get("agent") != "scribe"]
    all_failed = all("error" in r for r in investigation_reports) if investigation_reports else True

    if all_failed and not agent_files:
        # Don't let the LLM summarize nothing — it will hallucinate
        failed_agents = [f"{r['agent']}: {r['error']}" for r in investigation_reports if "error" in r]
        summary = (
            "**All investigation agents failed.** No real data was collected.\n\n"
            "**Errors:**\n" + "\n".join(f"- {e}" for e in failed_agents) + "\n\n"
            "**Recommendation:** Please check agent logs and retry. "
            "This could be a transient API issue (rate limit, timeout) or a configuration problem."
        )
        messages.append({"role": "assistant", "content": summary})
    else:
        messages.append({
            "role": "user",
            "_internal": True,
            "content": (
                "All agents have reported and documentation is written. "
                "Provide your executive summary as Tech Lead. Be concise. "
                "Highlight the most critical findings and recommended next steps. "
                "IMPORTANT: Only reference REAL data from agent reports. "
                "If an agent failed with an error, say so — do NOT invent fake data."
            ),
        })
        resp = llm.chat.completions.create(
            model=ORCHESTRATOR_MODEL,
            messages=messages,
        )
        summary = resp.choices[0].message.content or ""
        messages.append({"role": "assistant", "content": summary})

    session["phase"] = "done"
    _save_session(sid)
    return ChatResponse(
        session_id=sid,
        reply=summary,
        phase="done",
        agent_reports=agent_reports,
    )


# ---------------------------------------------------------------------------
# WebSocket — real-time chat with streamed events
# ---------------------------------------------------------------------------
async def ws_send(ws: WebSocket, event: str, **data):
    """Send a typed JSON event over WebSocket."""
    await ws.send_json({"event": event, **data})


@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    # Check auth from cookie
    token = ws.cookies.get("sentinel_token")
    if not token or not _verify_token(token):
        await ws.close(code=4001, reason="Not authenticated")
        return
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_json()
            user_msg = raw.get("message", "").strip()
            session_id = raw.get("session_id")
            if not user_msg:
                continue

            sid, messages = get_or_create_session(session_id)
            session = sessions[sid]

            if not session.get("title"):
                session["title"] = user_msg[:80]

            messages.append({"role": "user", "content": user_msg})
            _save_session(sid)

            await ws_send(ws, "session", session_id=sid, title=session["title"])
            await ws_send(ws, "phase", phase="thinking")

            # ── LLM decides: chat or execute ─────────────────────────
            # Force tool calling when user confirms
            confirmed = _is_confirmation(user_msg)
            try:
                resp = llm.chat.completions.create(
                    model=ORCHESTRATOR_MODEL,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="required" if confirmed else "auto",
                )
            except Exception as e:
                await ws_send(ws, "error", message=f"LLM error: {e}")
                continue

            msg = resp.choices[0].message
            messages.append(msg)

            # No tool calls → chat reply
            if not msg.tool_calls:
                session["phase"] = "chat"
                _save_session(sid)
                await ws_send(ws, "reply", content=msg.content or "")
                await ws_send(ws, "phase", phase="chat")
                continue

            # ── Execution ─────────────────────────────────────────────
            session["phase"] = "executing"
            agent_reports = session["agent_reports"]
            agent_files = session["agent_files"]

            session_workspace = os.path.join(WORKSPACE_DIR, f"chat_{sid[:8]}")
            os.makedirs(session_workspace, exist_ok=True)
            session["workspace_dir"] = session_workspace

            await ws_send(ws, "phase", phase="executing")

            for _ in range(15):
                if not msg.tool_calls:
                    break

                for tc in msg.tool_calls:
                    args = json.loads(tc.function.arguments)
                    agent_name = TOOL_ROUTING[tc.function.name]

                    await ws_send(ws, "agent_start", agent=agent_name,
                                  goal=args.get("goal", ""))

                    try:
                        receipt = await delegate_to_agent(
                            agent_name,
                            goal=args["goal"],
                            brief=args.get("brief"),
                            depends_on=args.get("depends_on"),
                            workspace_dir=session_workspace,
                        )
                        report = {"agent": agent_name, **receipt}
                        agent_reports.append(report)
                        if receipt.get("output_file"):
                            agent_files.append(receipt["output_file"])
                        result_str = json.dumps(receipt, default=str)
                        await ws_send(ws, "agent_done", **report)
                    except Exception as e:
                        report = {"agent": agent_name, "error": str(e)}
                        agent_reports.append(report)
                        result_str = json.dumps(report)
                        await ws_send(ws, "agent_done", **report)

                    messages.append(
                        {"role": "tool", "tool_call_id": tc.id, "content": result_str}
                    )

                resp = llm.chat.completions.create(
                    model=ORCHESTRATOR_MODEL,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                )
                msg = resp.choices[0].message
                messages.append(msg)

            # ── Scribe (always) ───────────────────────────────────────
            await ws_send(ws, "phase", phase="documenting")
            await ws_send(ws, "agent_start", agent="scribe", goal="Document findings")

            if agent_files:
                files_list = ", ".join(agent_files)
                scribe_prompt = (
                    f"All investigation agents have reported. Their work is saved at: {files_list}\n\n"
                    "Write a brief for the Scribe to document everything. "
                    "Use depends_on to point Scribe at those files."
                )
            else:
                scribe_prompt = (
                    "Investigation agents encountered errors and produced no output files. "
                    "Delegate to the Scribe to write an incident report documenting the failures."
                )
            messages.append({"role": "user", "content": scribe_prompt, "_internal": True})

            scribe_tools = [t for t in TOOLS if "scribe" in t["function"]["name"]]
            resp = llm.chat.completions.create(
                model=ORCHESTRATOR_MODEL,
                messages=messages,
                tools=scribe_tools,
                tool_choice="auto",
            )
            msg = resp.choices[0].message
            messages.append(msg)

            if msg.tool_calls:
                tc = msg.tool_calls[0]
                args = json.loads(tc.function.arguments)
                depends_on = list(set((args.get("depends_on") or []) + agent_files))
                try:
                    scribe_receipt = await delegate_to_agent(
                        "scribe", goal=args["goal"],
                        brief=args.get("brief"), depends_on=depends_on,
                        workspace_dir=session_workspace,
                    )
                    report = {"agent": "scribe", **scribe_receipt}
                    agent_reports.append(report)
                    messages.append(
                        {"role": "tool", "tool_call_id": tc.id,
                         "content": json.dumps(scribe_receipt, default=str)}
                    )
                    await ws_send(ws, "agent_done", **report)
                except Exception as e:
                    agent_reports.append({"agent": "scribe", "error": str(e)})
                    await ws_send(ws, "agent_done", agent="scribe", error=str(e))

            # ── Executive summary ─────────────────────────────────────
            await ws_send(ws, "phase", phase="summarizing")

            investigation_reports = [r for r in agent_reports if r.get("agent") != "scribe"]
            all_failed = all("error" in r for r in investigation_reports) if investigation_reports else True

            if all_failed and not agent_files:
                failed_agents = [f"{r['agent']}: {r['error']}" for r in investigation_reports if "error" in r]
                summary = (
                    "**All investigation agents failed.** No real data was collected.\n\n"
                    "**Errors:**\n" + "\n".join(f"- {e}" for e in failed_agents) + "\n\n"
                    "**Recommendation:** Please check agent logs and retry."
                )
                messages.append({"role": "assistant", "content": summary})
            else:
                messages.append({
                    "role": "user", "_internal": True,
                    "content": (
                        "All agents have reported and documentation is written. "
                        "Provide your executive summary as Tech Lead. Be concise. "
                        "Highlight the most critical findings and recommended next steps. "
                        "IMPORTANT: Only reference REAL data from agent reports. "
                        "If an agent failed with an error, say so — do NOT invent fake data."
                    ),
                })
                resp = llm.chat.completions.create(
                    model=ORCHESTRATOR_MODEL,
                    messages=messages,
                )
                summary = resp.choices[0].message.content or ""
                messages.append({"role": "assistant", "content": summary})

            session["phase"] = "done"
            _save_session(sid)
            await ws_send(ws, "reply", content=summary)

            # Send Scribe's .md report file as downloadable attachment
            for r in agent_reports:
                if r.get("agent") == "scribe" and not r.get("error"):
                    # Find .md files Scribe created in the session workspace
                    import glob
                    md_files = sorted(glob.glob(os.path.join(session_workspace, "*.md")))
                    for md_path in md_files:
                        md_name = os.path.basename(md_path)
                        rel_path = f"chat_{sid[:8]}/{md_name}"
                        await ws_send(ws, "scribe_report",
                                      filename=md_name,
                                      download_path=rel_path)

            await ws_send(ws, "phase", phase="done")

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws_send(ws, "error", message=str(e))
        except:
            pass


@app.get("/chat/sessions")
async def list_sessions():
    """List all chat sessions (most recent first)."""
    _load_all_sessions()
    result = []
    for sid, session in sessions.items():
        result.append({
            "session_id": sid,
            "title": session.get("title", "Untitled"),
            "created": session.get("created", ""),
            "updated": session.get("updated", ""),
            "phase": session.get("phase", "chat"),
        })
    result.sort(key=lambda s: s.get("updated", ""), reverse=True)
    return {"sessions": result}


@app.get("/chat/{session_id}/messages")
async def get_session_messages(session_id: str):
    """Get all messages for a session (for loading a chat)."""
    if session_id not in sessions:
        data = _load_session(session_id)
        if not data:
            raise HTTPException(status_code=404, detail="Session not found")
        # Reconstruct into memory
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + data.get("messages", [])
        sessions[session_id] = {
            "messages": messages,
            "agent_reports": data.get("agent_reports", []),
            "agent_files": [],
            "phase": data.get("phase", "chat"),
            "title": data.get("title", ""),
            "created": data.get("created", ""),
            "updated": data.get("updated", ""),
        }

    session = sessions[session_id]
    # Return only user/assistant messages (not system/tool/internal)
    chat_messages = []
    for m in session["messages"]:
        role = m.get("role") if isinstance(m, dict) else getattr(m, "role", None)
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", None)
        internal = m.get("_internal", False) if isinstance(m, dict) else getattr(m, "_internal", False)
        if role in ("user", "assistant") and content and not internal:
            chat_messages.append({"role": role, "content": content})
    return {
        "session_id": session_id,
        "title": session.get("title", ""),
        "phase": session.get("phase", "chat"),
        "agent_reports": session.get("agent_reports", []),
        "messages": chat_messages,
    }
@app.delete("/chat/{session_id}")
async def delete_session(session_id: str):
    sessions.pop(session_id, None)
    path = _session_path(session_id)
    if os.path.exists(path):
        os.remove(path)
    return {"status": "deleted"}


# Keep the old /command endpoint for backward compat
class CommandRequest(BaseModel):
    command: str


class CommandResponse(BaseModel):
    plan: str
    agent_reports: list
    summary: str


@app.post("/command", response_model=CommandResponse)
async def run_command(req: CommandRequest):
    # Legacy: direct execution without chat
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": req.command},
    ]

    agent_reports: list[dict] = []
    agent_files: list[str] = []
    plan_text = ""

    # Create a workspace directory for this command
    cmd_id = str(uuid.uuid4())[:8]
    cmd_workspace = os.path.join(WORKSPACE_DIR, f"cmd_{cmd_id}")
    os.makedirs(cmd_workspace, exist_ok=True)

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
                    workspace_dir=cmd_workspace,
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
    else:
        scribe_planning_prompt = (
            "Investigation agents encountered errors and produced no output files. "
            "Delegate to the Scribe to write an incident report documenting the failures "
            "and what was attempted. The Scribe should note which agents failed and recommend retrying."
        )
    messages.append({"role": "user", "content": scribe_planning_prompt})

    scribe_tools = [t for t in TOOLS if "scribe" in t["function"]["name"]]

    resp = llm.chat.completions.create(
        model=ORCHESTRATOR_MODEL,
        messages=messages,
        tools=scribe_tools,
        tool_choice="auto",
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
                workspace_dir=cmd_workspace,
            )
            agent_reports.append({"agent": "scribe", **scribe_receipt})
            messages.append(
                {"role": "tool", "tool_call_id": tc.id,
                 "content": json.dumps(scribe_receipt, default=str)}
            )
        except Exception as e:
            agent_reports.append({"agent": "scribe", "error": str(e)})

    # ── Phase 3: Executive Summary (Tech Lead wraps up) ───────────────
    investigation_reports = [r for r in agent_reports if r.get("agent") != "scribe"]
    all_failed = all("error" in r for r in investigation_reports) if investigation_reports else True

    if all_failed and not agent_files:
        summary = (
            "**All investigation agents failed.** No real data was collected.\n\n"
            "**Errors:**\n" + "\n".join(f"- {r['agent']}: {r['error']}" for r in investigation_reports if "error" in r) + "\n\n"
            "**Recommendation:** Please check agent logs and retry."
        )
    else:
        messages.append({
            "role": "user",
            "content": (
                "All agents have reported and documentation is written. "
                "Provide your executive summary as Tech Lead. Be concise. "
                "Highlight the most critical findings and recommended next steps. "
                "IMPORTANT: Only reference REAL data from agent reports. "
                "If an agent failed with an error, say so — do NOT invent fake data."
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


@app.get("/status/llm")
async def llm_status():
    """Deep health check — pings every agent's LLM provider and the orchestrator's own."""
    results = {}

    # Orchestrator's own LLM
    try:
        resp = llm.chat.completions.create(
            model=ORCHESTRATOR_MODEL,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=5,
        )
        results["orchestrator"] = {"ok": True, "model": ORCHESTRATOR_MODEL, "base_url": ORCHESTRATOR_BASE_URL}
    except Exception as e:
        results["orchestrator"] = {"ok": False, "model": ORCHESTRATOR_MODEL, "base_url": ORCHESTRATOR_BASE_URL, "error": str(e)}

    # Worker agents' LLMs
    for name, info in AGENTS.items():
        try:
            async with httpx.AsyncClient(timeout=30.0) as http:
                r = await http.get(f"{info['url']}/health/llm")
                data = r.json()
                results[name] = data.get("llm", data)
        except Exception as e:
            results[name] = {"ok": False, "error": str(e)}

    return results


@app.get("/health")
async def health():
    return {"status": "ok", "service": "orchestrator"}


# ---------------------------------------------------------------------------
# Workspace file browsing
# ---------------------------------------------------------------------------


@app.get("/workspace/files")
async def list_workspace_files(path: str = ""):
    """List files and directories in the shared workspace."""
    # Prevent path traversal
    safe_path = os.path.normpath(path).lstrip(os.sep).lstrip("/")
    if ".." in safe_path.split(os.sep):
        raise HTTPException(status_code=400, detail="Invalid path")
    target = os.path.join(WORKSPACE_DIR, safe_path) if safe_path else WORKSPACE_DIR

    items = []
    if os.path.isdir(target):
        for f in sorted(os.listdir(target)):
            if f.startswith("."):
                continue
            fp = os.path.join(target, f)
            entry = {
                "name": f,
                "path": os.path.join(safe_path, f) if safe_path else f,
                "modified": os.path.getmtime(fp),
            }
            if os.path.isdir(fp):
                entry["type"] = "directory"
                entry["size"] = 0
            else:
                entry["type"] = "file"
                entry["size"] = os.path.getsize(fp)
            items.append(entry)
    return {"files": items, "current_path": safe_path}


@app.get("/workspace/files/{file_path:path}")
async def read_workspace_file(file_path: str):
    """Read a specific file from the shared workspace."""
    # Prevent path traversal
    safe_path = os.path.normpath(file_path).lstrip(os.sep).lstrip("/")
    if ".." in safe_path.split(os.sep):
        raise HTTPException(status_code=400, detail="Invalid path")
    fp = os.path.join(WORKSPACE_DIR, safe_path)
    if not os.path.isfile(fp):
        raise HTTPException(status_code=404, detail="File not found")
    with open(fp, "r", encoding="utf-8", errors="replace") as fh:
        return {"name": os.path.basename(safe_path), "path": safe_path, "content": fh.read()}


@app.get("/workspace/download/{file_path:path}")
async def download_workspace_file(file_path: str):
    """Download a file from the workspace."""
    safe_path = os.path.normpath(file_path).lstrip(os.sep).lstrip("/")
    if ".." in safe_path.split(os.sep):
        raise HTTPException(status_code=400, detail="Invalid path")
    fp = os.path.join(WORKSPACE_DIR, safe_path)
    if not os.path.isfile(fp):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(fp, filename=os.path.basename(safe_path), media_type="application/octet-stream")
