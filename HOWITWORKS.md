# Sentinel MAS — How It Works

## System Overview

Sentinel is a **Multi-Agent System (MAS)** for SRE, security auditing, and monitoring. It runs as four isolated Docker containers that communicate over REST, with a shared filesystem as the data backbone.

```
                         User
                          │
                     POST /command
                          │
                          ▼
               ┌─────────────────────┐
               │    Orchestrator     │
               │    (Tech Lead)      │
               │                     │
               │  Expensive LLM      │
               │  Plans, briefs,     │
               │  coordinates        │
               └──┬──────┬───────┬───┘
                  │      │       │
            brief │      │ brief │ brief
          + goal  │      │       │ + depends_on
                  │      │       │
         ┌────────┘      │       └────────┐
         ▼               ▼                ▼
   ┌──────────┐   ┌──────────┐    ┌──────────┐
   │ Watchman │   │  Shield  │    │  Scribe  │
   │ (SRE     │   │ (Sec     │    │ (Tech    │
   │  Eng)    │   │  Eng)    │    │  Writer) │
   │          │   │          │    │          │
   │ Cheaper  │   │ Cheaper  │    │ Cheaper  │
   │ LLM      │   │ LLM      │    │ LLM      │
   └────┬─────┘   └────┬─────┘    └────┬─────┘
        │               │               │
        ▼               ▼               ▼
   ┌─────────────────────────────────────────┐
   │         Shared Workspace Volume         │
   │         /app/workspace                  │
   │                                         │
   │  watchman_20250404T120000Z.json         │
   │  shield_20250404T120030Z.json           │
   │  security_audit.md                      │
   │  system_health.md                       │
   │  audit_data.json                        │
   └─────────────────────────────────────────┘
```

---

## The Two Brains: Tech Lead vs Engineers

The system uses **two tiers of LLMs**:

| Role | Model Tier | Why |
|------|-----------|-----|
| **Orchestrator** (Tech Lead) | Expensive / smart (e.g. 72B) | Strategic planning, brief writing, synthesis. Sees the big picture. |
| **Workers** (Engineers) | Cheaper / faster (e.g. 7B) | Tool execution, interpretation. They get a good brief so they don't need the expensive model. |

The Tech Lead's intelligence is multiplied across the team via well-crafted briefs. Engineers don't need to be as smart when they know exactly *why* they're doing something and *what* matters.

---

## Connection Workflow: A Full Audit

### Step 1 — User sends a command

```
POST http://localhost:6000/command
{
  "command": "Run a full security and health audit on the system"
}
```

### Step 2 — Orchestrator plans (Phase 1: Investigation)

The Tech Lead LLM thinks strategically:

> "I need to know what's running before I can scan it. Watchman first, then Shield uses Watchman's findings."

It crafts a **brief** for Watchman — not orders, but strategic context:

```json
{
  "goal": "Map all running services and assess system health",
  "brief": {
    "objective": "We need a full inventory of what's running so the security team can target their scans",
    "strategic_context": "User requested a full security audit. Your findings become Shield's target list.",
    "suggested_approach": ["Check containers first — they're the primary attack surface",
                           "Then check host metrics for anything abnormal"],
    "priorities": ["Running containers and their images are most critical",
                   "Flag anything unusual even if it seems like a health issue"],
    "output_format": "Container names, images, ports, and any anomalies Shield should investigate"
  }
}
```

### Step 3 — Watchman works autonomously

Watchman's own LLM receives the brief and decides HOW to execute:

```
Brief says check containers first → I'll do that.
But CPU looks high → Brief didn't mention this, but I'm going to investigate anyway.
Found a container restarting in a loop → That's a health issue AND a potential security flag.
```

Watchman calls its own tools (`check_cpu`, `list_containers`, `get_container_logs`, etc.), iterates through its reasoning loop, and when done:

1. **Saves full work** to workspace: `watchman_20250404T120000Z.json`
2. **Returns a receipt** to the orchestrator:

```json
{
  "agent": "watchman",
  "output_file": "watchman_20250404T120000Z.json",
  "summary": "3 containers running, 1 in restart loop (nginx). CPU at 87% due to runaway log process...",
  "tool_calls_made": 5
}
```

The orchestrator sees **200 characters**, not 50KB of metrics.

### Step 4 — Orchestrator briefs Shield with a file reference

The Tech Lead reads Watchman's short summary and crafts Shield's brief:

```json
{
  "goal": "Security assessment of all running services",
  "brief": {
    "objective": "Assess the attack surface of all running containers and the host network",
    "strategic_context": "Watchman found 3 containers running, one (nginx) is in a restart loop which could indicate compromise. Their full findings are in the workspace.",
    "suggested_approach": ["Start with nmap recon of the container network",
                           "Scan Docker images with trivy — especially nginx",
                           "The restart loop on nginx deserves extra attention"],
    "targets": ["sentinel-net network", "nginx:latest", "python:3.12-slim"],
    "priorities": ["The restarting nginx container is suspicious — prioritize it"]
  },
  "depends_on": ["watchman_20250404T120000Z.json"]
}
```

### Step 5 — Shield reads Watchman's work and scans

Shield's agent loop:

1. **Reads** `watchman_20250404T120000Z.json` directly from `/app/workspace/`
2. Gets the full container list, images, ports — all the detail
3. Plans its own scan strategy based on both the brief AND the raw data
4. Runs nmap, trivy, checkov as it sees fit
5. Saves full results: `shield_20250404T120030Z.json`
6. Returns a lightweight receipt to the orchestrator

**Key: Shield reads 50KB of Watchman data from disk. The orchestrator never touches it.**

### Step 6 — Scribe always fires (Phase 2: Documentation)

The system **guarantees** Scribe runs. This is code, not a prompt hope:

```python
# Phase 2 always executes — tool_choice="required" forces it
scribe_tools = [t for t in TOOLS if "scribe" in t["function"]["name"]]
resp = llm.chat.completions.create(
    tools=scribe_tools,
    tool_choice="required",  # MUST call Scribe
)
```

The orchestrator briefs Scribe with `depends_on` pointing to both files:

```json
{
  "goal": "Create a combined security and health audit report",
  "brief": {
    "objective": "Turn raw agent findings into actionable reports for both technical team and leadership",
    "strategic_context": "Watchman found a restarting container and high CPU. Shield found open ports and image vulnerabilities.",
    "priorities": ["The nginx restart loop + its CVEs should be the lead finding"]
  },
  "depends_on": [
    "watchman_20250404T120000Z.json",
    "shield_20250404T120030Z.json"
  ]
}
```

Scribe reads both files, decides report structure, writes:
- `security_audit.md`
- `system_health.md`
- `audit_data.json`

### Step 7 — Tech Lead executive summary (Phase 3)

The orchestrator writes a final summary based on the receipts it collected. It never saw the raw data — only short summaries — so its context window stays lean.

---

## Data Flow: What Goes Where

```
Orchestrator context window:         Shared workspace (disk):
┌────────────────────────────┐      ┌────────────────────────────┐
│ System prompt              │      │ watchman_20250404T.json    │
│ User command               │      │   → full metrics, logs,    │
│ Watchman receipt (200 ch)  │      │     container details      │
│ Shield receipt (200 ch)    │      │                            │
│ Scribe receipt (200 ch)    │      │ shield_20250404T.json      │
│                            │      │   → nmap XML, trivy CVEs,  │
│ TOTAL: ~2K tokens          │      │     checkov results        │
│                            │      │                            │
└────────────────────────────┘      │ security_audit.md          │
                                    │ system_health.md           │
                                    │ audit_data.json            │
                                    │                            │
                                    │ TOTAL: could be 200KB+     │
                                    └────────────────────────────┘
```

The orchestrator stays at ~2K tokens no matter how big the scan results are. Engineers read from disk.

---

## The Three Phases (Structural, Not Hopeful)

| Phase | What | Guaranteed? | Why |
|-------|------|-------------|-----|
| **1. Investigation** | Orchestrator briefs Watchman + Shield | LLM-driven (decides order, briefs, follow-ups) | Needs flexibility to adapt |
| **2. Documentation** | Scribe gets all agent file paths | **Yes** — `tool_choice="required"` in code | Undocumented work didn't happen |
| **3. Summary** | Tech Lead writes executive summary | **Yes** — hardcoded final LLM call | User always gets a conclusion |

---

## Agent Autonomy: Engineers, Not Scripts

Each agent can:

- **Deviate from the brief** if they find something better to investigate
- **Go deeper** when initial results look suspicious
- **Flag things outside their scope** for the Tech Lead to route elsewhere
- **Challenge assumptions** from other agents' work
- **Decide their own tool order** — the brief suggests, the engineer decides

What the agent loop looks like internally:

```
Receive goal + brief + depends_on file paths
         │
         ▼
   Read prior agent work from workspace (if depends_on)
         │
         ▼
   ┌─── LLM Reasoning Loop (up to 15 iterations) ───┐
   │                                                   │
   │  LLM thinks: "Based on the brief and what I      │
   │  read from Watchman, I should scan port 22 first" │
   │       │                                           │
   │       ▼                                           │
   │  Calls tool (nmap_scan, check_cpu, etc.)          │
   │       │                                           │
   │       ▼                                           │
   │  LLM interprets: "Port 22 has old OpenSSH,       │
   │  let me run vuln scripts — brief didn't ask       │
   │  for this but it's important"                     │
   │       │                                           │
   │       ▼                                           │
   │  Calls another tool... (loops)                    │
   │                                                   │
   └───────────────────────────────────────────────────┘
         │
         ▼
   Save full work to /app/workspace/<agent>_<timestamp>.json
         │
         ▼
   Return receipt to orchestrator (file path + 500 char summary)
```

---

## Network & Container Isolation

```yaml
# Each agent is an isolated container
orchestrator:  port 6000  →  has API key, no tools
watchman:      port 6001  →  has docker socket (read-only), psutil
shield:        port 6002  →  has nmap, trivy, checkov, NET_RAW capability
scribe:        port 6003  →  has pandoc, git, file writing

# They share ONLY:
# 1. The sentinel-net Docker network (REST calls)
# 2. The /app/workspace volume (file-based data passing)
```

Security boundaries:
- Shield gets `cap_add: NET_RAW` (for nmap), NOT `privileged: true`
- Watchman gets the Docker socket as **read-only**
- Scribe has no network tools and no Docker access
- Orchestrator has the API key but no system tools
