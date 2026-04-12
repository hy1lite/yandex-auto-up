"""Lightweight GitHub update checks for the CLI panel."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from yauto import __version__, get_version_metadata
from yauto.paths import AppPaths

CACHE_TTL = timedelta(hours=6)


@dataclass
class UpdateStatus:
    latest_version: str | None = None
    has_update: bool = False
    checked_at: datetime | None = None


def get_update_status(paths: AppPaths) -> UpdateStatus:
    metadata = get_version_metadata()
    repo = metadata.get("github_repo", "").strip()
    if not repo:
        return UpdateStatus()

    cache_path = paths.state_dir / "update-check.json"
    cached = _load_cache(cache_path)
    now = datetime.now(timezone.utc)
    if cached and cached.checked_at and now - cached.checked_at < CACHE_TTL:
        return cached

    try:
        latest_version = _fetch_latest_version(repo)
    except Exception:
        return cached or UpdateStatus()

    status = UpdateStatus(
        latest_version=latest_version,
        has_update=_compare_versions(latest_version, __version__) > 0,
        checked_at=now,
    )
    _save_cache(cache_path, status)
    return status


def _fetch_latest_version(repo: str) -> str:
    with httpx.Client(timeout=2.5, headers={"Accept": "application/vnd.github+json"}) as client:
        release = client.get(f"https://api.github.com/repos/{repo}/releases/latest")
        if release.status_code == 200:
            tag = release.json().get("tag_name", "").strip()
            if tag:
                return _normalize_version(tag)

        raw = client.get(f"https://raw.githubusercontent.com/{repo}/main/src/yauto/version.json")
        if raw.status_code == 200:
            payload = raw.json()
            version = str(payload.get("version", "")).strip()
            if version:
                return _normalize_version(version)

    raise RuntimeError("latest version metadata is unavailable")


def _normalize_version(value: str) -> str:
    return value.strip().removeprefix("v")


def _compare_versions(left: str, right: str) -> int:
    left_parts = _version_key(left)
    right_parts = _version_key(right)
    if left_parts > right_parts:
        return 1
    if left_parts < right_parts:
        return -1
    return 0


def _version_key(value: str) -> tuple[int, ...]:
    cleaned = _normalize_version(value)
    parts = []
    for chunk in cleaned.split("."):
        number = "".join(character for character in chunk if character.isdigit())
        parts.append(int(number or "0"))
    return tuple(parts)


def _load_cache(path: Path) -> UpdateStatus | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        checked_at = payload.get("checked_at")
        return UpdateStatus(
            latest_version=payload.get("latest_version"),
            has_update=bool(payload.get("has_update")),
            checked_at=datetime.fromisoformat(checked_at) if checked_at else None,
        )
    except Exception:
        return None


def _save_cache(path: Path, status: UpdateStatus) -> None:
    payload = {
        "latest_version": status.latest_version,
        "has_update": status.has_update,
        "checked_at": status.checked_at.isoformat() if status.checked_at else None,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
