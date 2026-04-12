"""Core models for yandex auto up."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from yauto import __version__


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_profile_id() -> str:
    return uuid4().hex[:8]


class TelegramConfig(BaseModel):
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""
    notify_on_start: bool = True
    notify_on_recovery: bool = True
    notify_on_error: bool = True


class AppConfig(BaseModel):
    project_name: str = "yandex auto up"
    service_name: str = "yandex-auto-up"
    language: str = "en"
    log_level: str = "INFO"
    config_reload_seconds: int = Field(default=30, ge=5, le=3600)
    max_workers: int = Field(default=2, ge=1, le=8)
    service_account_file: str = "/etc/yandex-auto-up/keys"
    profile_dir: str = "/etc/yandex-auto-up/profiles"
    state_file: str = "/var/lib/yandex-auto-up/state.json"
    events_file: str = "/var/lib/yandex-auto-up/events.jsonl"
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.upper()

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str) -> str:
        normalized = value.lower().strip()
        if normalized not in {"en", "ru"}:
            return "en"
        return normalized


class VMProfile(BaseModel):
    profile_id: str = Field(default_factory=create_profile_id)
    name: str = Field(min_length=1, max_length=80)
    folder_id: str = Field(min_length=1)
    instance_id: str = Field(min_length=1)
    check_host: str = Field(min_length=1)
    enabled: bool = True
    auto_start_stopped: bool = True
    check_interval_seconds: int = Field(default=60, ge=15, le=3600)
    ping_timeout_seconds: int = Field(default=3, ge=1, le=30)
    startup_grace_seconds: int = Field(default=180, ge=30, le=3600)
    cooldown_seconds: int = Field(default=300, ge=30, le=7200)
    max_start_attempts: int = Field(default=3, ge=1, le=20)
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def touch(self) -> None:
        self.updated_at = utc_now()


class ServiceAccountKey(BaseModel):
    id: str
    service_account_id: str
    private_key: str


class VMRuntimeState(BaseModel):
    profile_id: str
    name: str
    status: str = "unknown"
    cloud_status: str | None = None
    reachable: bool | None = None
    last_check_at: datetime | None = None
    next_check_at: datetime | None = None
    last_action: str | None = None
    last_operation_id: str | None = None
    last_error: str | None = None
    last_transition_at: datetime | None = None
    consecutive_failures: int = 0
    start_attempts: int = 0


class AppState(BaseModel):
    version: str = __version__
    service_state: str = "starting"
    started_at: datetime = Field(default_factory=utc_now)
    last_loop_at: datetime | None = None
    message: str = ""
    profiles: dict[str, VMRuntimeState] = Field(default_factory=dict)


class EventRecord(BaseModel):
    timestamp: datetime = Field(default_factory=utc_now)
    level: str = "INFO"
    category: str = "system"
    message: str
    profile_id: str | None = None
    profile_name: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
