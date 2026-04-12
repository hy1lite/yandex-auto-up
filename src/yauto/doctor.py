"""Doctor checks for yandex auto up."""

from __future__ import annotations

import os
from dataclasses import dataclass

from yauto.cloud.client import CloudApiError, YandexCloudClient
from yauto.config.repository import ConfigRepository
from yauto.service_ctl import get_service_status


@dataclass
class DoctorCheck:
    name: str
    status: str
    detail: str


def run_doctor(config_repo: ConfigRepository) -> list[DoctorCheck]:
    config = config_repo.load_app_config()
    service = get_service_status(config.service_name)
    checks: list[DoctorCheck] = []

    checks.append(_path_check("config directory", config_repo.paths.config_dir))
    checks.append(_path_check("profile directory", config_repo.paths.profile_dir))
    checks.append(_path_check("state directory", config_repo.paths.state_dir))

    source = config_repo.get_keys_dir()
    try:
        files = config_repo.validate_keys()
        client = YandexCloudClient.from_service_account_files(files)
        try:
            client.ensure_authenticated()
            clouds = client.list_clouds()
            if clouds:
                detail = f"source={source} keys={len(files)} visible clouds={len(clouds)}"
                checks.append(DoctorCheck("service account", "ok", detail))
            else:
                detail = f"source={source} keys={len(files)} visible clouds=0; use Folder ID import or grant viewer on the cloud"
                checks.append(DoctorCheck("service account", "warn", detail))
        except CloudApiError:
            detail = f"source={source} keys={len(files)} authenticated, but clouds are not listable; use Folder ID import or grant viewer on the cloud"
            checks.append(DoctorCheck("service account", "warn", detail))
        finally:
            client.close()
    except FileNotFoundError:
        checks.append(DoctorCheck("service account", "warn", f"service account source is missing: {source}"))
    except (CloudApiError, OSError, ValueError) as exc:
        checks.append(DoctorCheck("service account", "error", str(exc)))

    profiles = config_repo.list_profiles()
    if profiles:
        checks.append(DoctorCheck("profiles", "ok", f"configured profiles: {len(profiles)}"))
    else:
        checks.append(DoctorCheck("profiles", "warn", "no VM profiles configured yet"))

    checks.append(
        DoctorCheck(
            "service",
            "ok" if service.supported and service.installed else "warn",
            f"supported={service.supported} installed={service.installed} active={service.active} enabled={service.enabled}",
        )
    )

    if config.telegram.enabled and config.telegram.bot_token and config.telegram.chat_id:
        checks.append(DoctorCheck("telegram", "ok", "telegram notifications are configured"))
    else:
        checks.append(DoctorCheck("telegram", "warn", "telegram notifications are not configured"))

    return checks


def _path_check(name: str, path) -> DoctorCheck:
    exists = path.exists()
    writable = os.access(path, os.W_OK) if exists else False
    if exists and writable:
        return DoctorCheck(name, "ok", str(path))
    if exists:
        return DoctorCheck(name, "warn", f"{path} exists but is not writable")
    return DoctorCheck(name, "error", f"{path} does not exist")
