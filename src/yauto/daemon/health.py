"""Lightweight health checks."""

from __future__ import annotations

import platform
import subprocess


def ping_host(host: str, timeout_seconds: int) -> bool:
    if platform.system().lower() == "windows":
        command = ["ping", "-n", "1", "-w", str(timeout_seconds * 1000), host]
    else:
        command = ["ping", "-c", "1", "-W", str(timeout_seconds), host]

    try:
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_seconds + 2,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False
