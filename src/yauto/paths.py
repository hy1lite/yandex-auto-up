"""Filesystem path helpers for yandex auto up."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


KEYS_DIR_NAME = "keys"
KEYS_NOTICE_FILENAME = "ПРОЧИТАЙ МЕНЯ.txt"
KEYS_NOTICE_TEXT = (
    "Переносите сюда ключи Service Account Yandex Cloud.\n"
    "\n"
    "Подхватываются ВСЕ файлы из этой папки автоматически:\n"
    "  - любые имена файлов (не только *.json)\n"
    "  - любое количество ключей\n"
    "  - файлы проверяются по содержимому, а не по расширению\n"
    "\n"
    "Просто скопируйте сюда файл(ы) ключей и перезапустите панель.\n"
)

# Legacy directory name from previous version
LEGACY_KEYS_DIR_NAME = "service-accounts"


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path
    profile_dir: Path
    state_dir: Path
    runtime_dir: Path
    config_file: Path
    keys_dir: Path
    keys_notice_file: Path
    legacy_service_account_file: Path
    state_file: Path
    events_file: Path
    pid_file: Path


def build_paths() -> AppPaths:
    config_dir = Path(os.environ.get("YAUTO_CONFIG_DIR", "/etc/yandex-auto-up"))
    state_dir = Path(os.environ.get("YAUTO_STATE_DIR", "/var/lib/yandex-auto-up"))
    runtime_dir = Path(os.environ.get("YAUTO_RUNTIME_DIR", "/run/yandex-auto-up"))
    profile_dir = config_dir / "profiles"
    keys_dir = config_dir / KEYS_DIR_NAME
    return AppPaths(
        config_dir=config_dir,
        profile_dir=profile_dir,
        state_dir=state_dir,
        runtime_dir=runtime_dir,
        config_file=config_dir / "config.json",
        keys_dir=keys_dir,
        keys_notice_file=keys_dir / KEYS_NOTICE_FILENAME,
        legacy_service_account_file=config_dir / "service-account.json",
        state_file=state_dir / "state.json",
        events_file=state_dir / "events.jsonl",
        pid_file=runtime_dir / "daemon.pid",
    )


def ensure_layout(paths: AppPaths) -> None:
    for directory in (paths.config_dir, paths.profile_dir, paths.state_dir, paths.runtime_dir, paths.keys_dir):
        directory.mkdir(parents=True, exist_ok=True)
    if not paths.keys_notice_file.exists():
        paths.keys_notice_file.write_text(KEYS_NOTICE_TEXT, encoding="utf-8")
