from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum
from datetime import datetime, timezone


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class TaskRequest(BaseModel):
    task_id: str
    description: str
    parameters: dict = {}


class TaskResult(BaseModel):
    task_id: str
    agent: str
    status: str  # "success", "error", "partial"
    data: dict = {}
    summary: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SecurityFinding(BaseModel):
    target: str
    finding: str
    severity: Severity
    details: str = ""
    remediation: str = ""


class SystemMetric(BaseModel):
    metric: str
    value: float
    unit: str
    status: str  # "ok", "warning", "critical"


class ContainerInfo(BaseModel):
    name: str
    image: str
    status: str
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
