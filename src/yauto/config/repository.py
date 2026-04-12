"""Configuration and profile persistence."""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from yauto.models import AppConfig, ServiceAccountKey, VMProfile
from yauto.paths import LEGACY_KEYS_DIR_NAME, AppPaths, build_paths, ensure_layout

LOGGER = logging.getLogger(__name__)


class ConfigRepository:
    def __init__(self, paths: AppPaths | None = None):
        self.paths = paths or build_paths()
        ensure_layout(self.paths)
        self._rescue_stray_keys()

    # ── app config ──────────────────────────────────────────────

    def load_app_config(self) -> AppConfig:
        if not self.paths.config_file.exists():
            return AppConfig(
                service_account_file=str(self.paths.keys_dir),
                profile_dir=str(self.paths.profile_dir),
                state_file=str(self.paths.state_file),
                events_file=str(self.paths.events_file),
            )
        payload = self._read_json(self.paths.config_file)
        config = AppConfig.model_validate(payload)
        config.service_account_file = str(self.paths.keys_dir)
        return config

    def save_app_config(self, config: AppConfig) -> None:
        payload = config.model_dump(mode="json")
        self._write_json_atomic(self.paths.config_file, payload)

    # ── service account keys ────────────────────────────────────

    def get_keys_dir(self) -> Path:
        return self.paths.keys_dir

    def get_keys_notice_file(self) -> Path:
        return self.paths.keys_notice_file

    def list_key_files(self) -> list[Path]:
        """Return all files in keys/ that are valid SA keys (by content, any extension)."""
        return self._probe_valid_keys(self.paths.keys_dir)

    def validate_keys(self) -> list[Path]:
        """Return validated key file list, raise if empty."""
        files = self.list_key_files()
        if not files:
            raise FileNotFoundError(self.paths.keys_dir)
        return files

    def has_keys(self) -> bool:
        try:
            return bool(self.list_key_files())
        except OSError:
            return False

    def save_service_account(self, raw_text: str) -> ServiceAccountKey:
        payload = json.loads(raw_text)
        key = ServiceAccountKey.model_validate(payload)
        target = self.paths.keys_dir / self._key_filename(key)
        self._write_json_atomic(target, payload)
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        return key

    def load_service_account(self) -> ServiceAccountKey | None:
        files = self.list_key_files()
        if not files:
            return None
        payload = self._read_json(files[0])
        return ServiceAccountKey.model_validate(payload)

    def diagnose_keys_dir(self) -> dict[str, Any]:
        """Return a diagnostic summary for the keys directory (for UI)."""
        keys_dir = self.paths.keys_dir
        result: dict[str, Any] = {
            "keys_dir": keys_dir,
            "exists": keys_dir.exists(),
            "valid": [],
            "invalid": [],
            "rescued": 0,
        }
        if not keys_dir.exists():
            return result

        for path in sorted(keys_dir.iterdir()):
            if not path.is_file():
                continue
            if path == self.paths.keys_notice_file:
                continue
            ok, reason = self._probe_file(path)
            if ok:
                result["valid"].append(path)
            else:
                result["invalid"].append((path, reason))
        return result

    # ── profiles ────────────────────────────────────────────────

    def list_profiles(self) -> list[VMProfile]:
        profiles: list[VMProfile] = []
        for path in sorted(self.paths.profile_dir.glob("*.json")):
            try:
                payload = self._read_json(path)
                profiles.append(VMProfile.model_validate(payload))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return profiles

    def get_profile(self, profile_id: str) -> VMProfile | None:
        path = self.paths.profile_dir / f"{profile_id}.json"
        if not path.exists():
            return None
        return VMProfile.model_validate(self._read_json(path))

    def save_profile(self, profile: VMProfile) -> None:
        profile.touch()
        path = self.paths.profile_dir / f"{profile.profile_id}.json"
        self._write_json_atomic(path, profile.model_dump(mode="json"))

    def delete_profile(self, profile_id: str) -> None:
        path = self.paths.profile_dir / f"{profile_id}.json"
        if path.exists():
            path.unlink()

    # ── backward-compat aliases (used externally) ───────────────

    def get_service_account_source(self) -> Path:
        return self.get_keys_dir()

    def get_service_account_notice_file(self) -> Path:
        return self.get_keys_notice_file()

    def list_service_account_files(self) -> list[Path]:
        return self.list_key_files()

    def validate_service_account_source(self) -> list[Path]:
        return self.validate_keys()

    def has_service_account_source(self) -> bool:
        return self.has_keys()

    # ── key probing (content-based, not extension-based) ────────

    @classmethod
    def _probe_valid_keys(cls, directory: Path) -> list[Path]:
        """Scan *all* files in directory, return those that are valid SA keys."""
        if not directory.is_dir():
            return []
        valid: list[Path] = []
        for path in sorted(directory.iterdir()):
            if not path.is_file():
                continue
            ok, _ = cls._probe_file(path)
            if ok:
                valid.append(path)
        return valid

    @staticmethod
    def _probe_file(path: Path) -> tuple[bool, str]:
        """Try to read a file as a service account key. Return (ok, reason)."""
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return False, f"cannot read: {exc}"
        if not raw.strip():
            return False, "empty file"
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return False, "not valid JSON"
        if not isinstance(data, dict):
            return False, "JSON is not an object"
        missing = [f for f in ("id", "service_account_id", "private_key") if f not in data]
        if missing:
            return False, f"missing fields: {', '.join(missing)}"
        try:
            ServiceAccountKey.model_validate(data)
        except Exception as exc:
            return False, f"validation error: {exc}"
        return True, "ok"

    @staticmethod
    def _key_filename(key: ServiceAccountKey) -> str:
        return f"{key.service_account_id}-{key.id}.json"

    # ── auto-rescue: find stray keys and move to keys/ ──────────

    def _rescue_stray_keys(self) -> None:
        """
        Search common wrong locations for SA key files and move them
        into the canonical keys/ directory. Handles:
        - legacy /etc/yandex-auto-up/service-account.json
        - legacy /etc/yandex-auto-up/service-accounts/ directory
        - any SA key files dropped directly in config root
        """
        rescued = 0
        rescued += self._rescue_single_legacy_file()
        rescued += self._rescue_legacy_directory()
        rescued += self._rescue_config_root_keys()
        if rescued:
            LOGGER.info("auto-rescued %d key(s) into %s", rescued, self.paths.keys_dir)

    def _rescue_single_legacy_file(self) -> int:
        """Move legacy single service-account.json into keys/."""
        legacy = self.paths.legacy_service_account_file
        if not legacy.exists():
            return 0
        return self._try_move_key(legacy)

    def _rescue_legacy_directory(self) -> int:
        """Move all keys from old service-accounts/ dir into keys/."""
        legacy_dir = self.paths.config_dir / LEGACY_KEYS_DIR_NAME
        if not legacy_dir.is_dir() or legacy_dir == self.paths.keys_dir:
            return 0
        rescued = 0
        for path in list(legacy_dir.iterdir()):
            if not path.is_file():
                continue
            rescued += self._try_move_key(path)
        # Remove legacy dir if empty
        try:
            if legacy_dir.exists() and not any(legacy_dir.iterdir()):
                legacy_dir.rmdir()
        except OSError:
            pass
        return rescued

    def _rescue_config_root_keys(self) -> int:
        """Scan config root for files that look like SA keys and move them."""
        rescued = 0
        config_dir = self.paths.config_dir
        for path in sorted(config_dir.iterdir()):
            if not path.is_file():
                continue
            # Skip config.json and other known files
            if path.name in ("config.json",):
                continue
            ok, _ = self._probe_file(path)
            if ok:
                rescued += self._try_move_key(path)
        return rescued

    def _try_move_key(self, source: Path) -> int:
        """Try to move a file into keys/. Returns 1 on success, 0 on skip."""
        ok, _ = self._probe_file(source)
        if not ok:
            return 0

        target = self.paths.keys_dir / source.name
        if target.exists():
            # Already there; just remove the stray copy
            try:
                source.unlink()
            except OSError:
                pass
            return 0

        try:
            shutil.move(str(source), str(target))
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass
            LOGGER.info("rescued key %s -> %s", source, target)
            return 1
        except OSError:
            return 0

    # ── JSON I/O ────────────────────────────────────────────────

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
        temp_path = path.with_suffix(f"{path.suffix}.tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        temp_path.replace(path)
