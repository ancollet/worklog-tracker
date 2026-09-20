"""Plain dataclass models that mirror the DB rows."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(slots=True)
class Customer:
    id: int
    name: str
    booking_system: Optional[str] = None  # 'jira' | 'salesforce' | None
    external_ref: Optional[str] = None    # e.g. Salesforce Account-ID, Jira project key
    archived: bool = False
    created_at: Optional[datetime] = None


@dataclass(slots=True)
class Project:
    id: int
    customer_id: int
    name: str
    color: Optional[str] = None
    round_minutes: Optional[int] = None
    external_ref: Optional[str] = None  # e.g. Salesforce project-ID
    archived: bool = False
    created_at: Optional[datetime] = None
    customer_name: Optional[str] = None  # joined view
    customer_booking_system: Optional[str] = None  # joined view

    @property
    def display_name(self) -> str:
        if self.customer_name:
            return f"{self.customer_name} · {self.name}"
        return self.name


@dataclass(slots=True)
class Flag:
    id: int
    name: str
    color: Optional[str] = None
    sort_order: int = 0
    created_at: Optional[datetime] = None


@dataclass(slots=True)
class Snippet:
    id: int
    text: str
    sort_order: int = 0
    created_at: Optional[datetime] = None


@dataclass(slots=True)
class LogEntry:
    id: int
    project_id: int
    task: Optional[str]
    description: Optional[str]
    started_at: datetime
    ended_at: Optional[datetime]
    duration_seconds: Optional[int]
    rounded_to_minutes: Optional[int]
    is_manual: bool = False
    external_worklog_id: Optional[str] = None
    external_worklog_url: Optional[str] = None
    external_synced_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # joined fields
    project_name: Optional[str] = None
    customer_name: Optional[str] = None
    project_color: Optional[str] = None
    customer_booking_system: Optional[str] = None
    flags: list["Flag"] = field(default_factory=list)


@dataclass(slots=True)
class AppState:
    running_log_id: Optional[int]
    last_project_id: Optional[int]
    default_round_minutes: int
