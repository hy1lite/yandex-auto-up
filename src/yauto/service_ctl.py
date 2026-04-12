"""Helpers around systemd service management."""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class ServiceStatus:
    supported: bool
    installed: bool
    active: bool
    enabled: bool
    detail: str


def systemd_supported() -> bool:
    return platform.system().lower() == "linux" and shutil.which("systemctl") is not None


def get_service_status(service_name: str) -> ServiceStatus:
    if not systemd_supported():
        return ServiceStatus(False, False, False, False, "systemd is not available in this environment")

    show_result = _call(["systemctl", "show", service_name, "--property=LoadState,ActiveState,UnitFileState"])
    values = {}
    if show_result.returncode == 0:
        for line in show_result.stdout.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = value

    installed = values.get("LoadState") == "loaded"
    active = values.get("ActiveState") == "active"
    enabled = values.get("UnitFileState") == "enabled"
    detail = values.get("LoadState", "service file is not installed")
    return ServiceStatus(True, installed, active, enabled, detail)


def run_service_action(service_name: str, action: str) -> tuple[bool, str]:
    if not systemd_supported():
        return False, "systemd is not available in this environment"
    command = ["systemctl", action, service_name]
    result = _call(command)
    if result.returncode == 0:
        return True, f"systemctl {action} {service_name} succeeded"
    message = result.stderr.strip() or result.stdout.strip() or "unknown error"
    return False, message


def read_journal(service_name: str, limit: int = 50) -> str:
    if not systemd_supported() or shutil.which("journalctl") is None:
        return "systemd journal is not available in this environment"
    result = _call(["journalctl", "-u", service_name, "-n", str(limit), "--no-pager"])
    return result.stdout.strip() or result.stderr.strip() or "No journal output."


def _call(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)
