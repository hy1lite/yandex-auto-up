"""Monitoring daemon for yandex auto up."""

from __future__ import annotations

import logging
import signal
import threading
from datetime import timedelta
from typing import Iterable

from yauto import __version__
from yauto.cloud.client import CloudApiError, YandexCloudClient
from yauto.cloud.selectel_client import SelectelCloudClient
from yauto.config.repository import ConfigRepository
from yauto.daemon.health import ping_host
from yauto.models import AppState, EventRecord, VMProfile, VMRuntimeState, utc_now
from yauto.notify.telegram import TelegramNotifier
from yauto.storage.repository import RuntimeRepository

LOGGER = logging.getLogger(__name__)

STARTING_STATUSES = {"PROVISIONING", "STARTING"}


class MonitorDaemon:
    def __init__(self, config_repo: ConfigRepository | None = None, runtime_repo: RuntimeRepository | None = None):
        self.config_repo = config_repo or ConfigRepository()
        self.runtime_repo = runtime_repo or RuntimeRepository(self.config_repo.paths)
        self.stop_event = threading.Event()
        self.reload_event = threading.Event()

    def install_signal_handlers(self) -> None:
        signal.signal(signal.SIGINT, self._handle_stop)
        signal.signal(signal.SIGTERM, self._handle_stop)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, self._handle_reload)

    def run(self) -> None:
        self.install_signal_handlers()
        state = self.runtime_repo.load_state()
        state.version = __version__
        state.service_state = "starting"
        state.message = "daemon booting"
        self.runtime_repo.save_state(state)
        self.reload_event.set()
        LOGGER.info("yandex auto up daemon starting")

        while not self.stop_event.is_set():
            loop_started = utc_now()
            try:
                config = self.config_repo.load_app_config()
                notifier = TelegramNotifier(config.telegram)
                profiles = self.config_repo.list_profiles()
                self._sync_known_profiles(state, profiles)

                enabled_profiles = [profile for profile in profiles if profile.enabled]
                if not enabled_profiles:
                    state.service_state = "idle"
                    state.message = "no enabled profiles configured"
                    self._save_state(state, loop_started)
                    self._sleep(config.config_reload_seconds)
                    continue

                yandex_profiles = [p for p in enabled_profiles if p.provider == "yandex"]
                selectel_profiles = [p for p in enabled_profiles if p.provider == "selectel"]

                yandex_client = None
                selectel_client = None

                try:
                    if yandex_profiles:
                        try:
                            service_account_files = self.config_repo.validate_service_account_source()
                            yandex_client = YandexCloudClient.from_service_account_files(service_account_files)
                        except (FileNotFoundError, OSError, ValueError) as exc:
                            LOGGER.warning("Yandex credentials not available: %s", exc)

                    if selectel_profiles:
                        from pathlib import Path
                        selectel_creds_file = Path(config.selectel_credentials_file)
                        if selectel_creds_file.exists():
                            selectel_client = SelectelCloudClient.from_credentials_file(selectel_creds_file)
                        else:
                            LOGGER.warning("Selectel credentials file not found: %s", selectel_creds_file)

                    if not yandex_client and not selectel_client:
                        state.service_state = "needs-setup"
                        state.message = "no cloud credentials configured"
                        self._save_state(state, loop_started)
                        self._sleep(config.config_reload_seconds)
                        continue

                    due_profiles = self._select_due_profiles(enabled_profiles, state)
                    for profile in due_profiles:
                        current = state.profiles.get(profile.profile_id) or VMRuntimeState(
                            profile_id=profile.profile_id,
                            name=profile.name,
                        )
                        
                        if profile.provider == "yandex" and yandex_client:
                            updated, events = self._evaluate_yandex_profile(profile, current, yandex_client, notifier)
                        elif profile.provider == "selectel" and selectel_client:
                            updated, events = self._evaluate_selectel_profile(profile, current, selectel_client, notifier)
                        else:
                            current.status = "error"
                            current.last_error = f"no client available for provider {profile.provider}"
                            updated, events = current, []
                        
                        state.profiles[profile.profile_id] = updated
                        for event in events:
                            self._publish_event(event)

                    state.service_state = "running"
                    state.message = f"watching {len(enabled_profiles)} profile(s)"
                    self._save_state(state, loop_started)
                    self.reload_event.clear()
                    self._sleep(self._compute_sleep_seconds(enabled_profiles, state, config.config_reload_seconds))
                finally:
                    if yandex_client:
                        yandex_client.close()
                    if selectel_client:
                        selectel_client.close()
            except CloudApiError as exc:
                LOGGER.exception("cloud API failure")
                state.service_state = "error"
                state.message = str(exc)
                self._publish_event(EventRecord(level="ERROR", category="cloud", message="cloud API failure", details={"error": str(exc)}))
                self._save_state(state, loop_started)
                self._sleep(10)
            except Exception as exc:  # pragma: no cover - outer safety net
                LOGGER.exception("daemon loop failure")
                state.service_state = "error"
                state.message = str(exc)
                self._publish_event(EventRecord(level="ERROR", category="system", message="daemon loop failure", details={"error": str(exc)}))
                self._save_state(state, loop_started)
                self._sleep(10)

        LOGGER.info("yandex auto up daemon stopped")

    def _sync_known_profiles(self, state: AppState, profiles: Iterable[VMProfile]) -> None:
        known_ids = {profile.profile_id for profile in profiles}
        for profile in profiles:
            current = state.profiles.get(profile.profile_id) or VMRuntimeState(profile_id=profile.profile_id, name=profile.name)
            current.name = profile.name
            if not profile.enabled:
                current.status = "disabled"
                current.next_check_at = None
                current.last_action = "disabled"
            state.profiles[profile.profile_id] = current

        for stale_id in list(state.profiles.keys()):
            if stale_id not in known_ids:
                del state.profiles[stale_id]

    def _select_due_profiles(self, profiles: list[VMProfile], state: AppState) -> list[VMProfile]:
        if self.reload_event.is_set():
            return profiles
        now = utc_now()
        due: list[VMProfile] = []
        for profile in profiles:
            current = state.profiles.get(profile.profile_id)
            if current is None or current.next_check_at is None or current.next_check_at <= now:
                due.append(profile)
        return due

    def _evaluate_yandex_profile(
        self,
        profile: VMProfile,
        runtime_state: VMRuntimeState,
        client: YandexCloudClient,
        notifier: TelegramNotifier,
    ) -> tuple[VMRuntimeState, list[EventRecord]]:
        now = utc_now()
        previous_status = runtime_state.status
        previous_error = runtime_state.last_error
        runtime_state.name = profile.name
        runtime_state.last_check_at = now
        events: list[EventRecord] = []

        reachable = ping_host(profile.check_host, profile.ping_timeout_seconds)
        runtime_state.reachable = reachable

        if reachable:
            runtime_state.status = "online"
            runtime_state.cloud_status = "RUNNING"
            runtime_state.last_error = None
            runtime_state.last_action = "health-check-ok"
            runtime_state.consecutive_failures = 0
            runtime_state.start_attempts = 0
            runtime_state.last_transition_at = now if previous_status != "online" else runtime_state.last_transition_at
            runtime_state.next_check_at = now + timedelta(seconds=profile.check_interval_seconds)
            if previous_status not in {"unknown", "online", "disabled"}:
                notifier.notify_recovery(profile.name, profile.check_host)
                events.append(
                    EventRecord(
                        level="INFO",
                        category="recovery",
                        message="profile recovered",
                        profile_id=profile.profile_id,
                        profile_name=profile.name,
                        details={"host": profile.check_host},
                    )
                )
            return runtime_state, events

        runtime_state.consecutive_failures += 1

        try:
            cloud_status = client.get_instance_status(profile.instance_id)
            runtime_state.cloud_status = cloud_status
        except CloudApiError as exc:
            runtime_state.status = "error"
            runtime_state.last_error = str(exc)
            runtime_state.last_action = "cloud-status-failed"
            runtime_state.next_check_at = now + timedelta(seconds=min(profile.check_interval_seconds, 60))
            if previous_status != runtime_state.status or previous_error != runtime_state.last_error:
                notifier.notify_error(profile.name, runtime_state.last_error)
                events.append(
                    EventRecord(
                        level="ERROR",
                        category="cloud",
                        message="failed to fetch instance status",
                        profile_id=profile.profile_id,
                        profile_name=profile.name,
                        details={"error": runtime_state.last_error},
                    )
                )
            return runtime_state, events

        if runtime_state.cloud_status in STARTING_STATUSES:
            runtime_state.status = "starting"
            runtime_state.last_error = None
            runtime_state.last_action = "waiting-for-cloud-start"
            runtime_state.last_transition_at = now if previous_status != "starting" else runtime_state.last_transition_at
            runtime_state.next_check_at = now + timedelta(seconds=max(30, min(profile.startup_grace_seconds, profile.check_interval_seconds)))
            if previous_status != runtime_state.status:
                events.append(
                    EventRecord(
                        level="INFO",
                        category="monitor",
                        message="instance is already starting",
                        profile_id=profile.profile_id,
                        profile_name=profile.name,
                        details={"cloud_status": runtime_state.cloud_status},
                    )
                )
            return runtime_state, events

        if runtime_state.cloud_status == "STOPPED":
            if not profile.auto_start_stopped:
                runtime_state.status = "stopped"
                runtime_state.last_action = "auto-start-disabled"
                runtime_state.last_error = "instance is stopped and auto-start is disabled"
                runtime_state.next_check_at = now + timedelta(seconds=profile.check_interval_seconds)
                if previous_status != runtime_state.status or previous_error != runtime_state.last_error:
                    notifier.notify_error(profile.name, runtime_state.last_error)
                    events.append(
                        EventRecord(
                            level="WARN",
                            category="monitor",
                            message="instance is stopped but auto-start is disabled",
                            profile_id=profile.profile_id,
                            profile_name=profile.name,
                        )
                    )
                return runtime_state, events

            if runtime_state.start_attempts >= profile.max_start_attempts:
                runtime_state.status = "cooldown"
                runtime_state.last_action = "cooldown"
                runtime_state.last_error = "max start attempts reached"
                runtime_state.start_attempts = 0
                runtime_state.next_check_at = now + timedelta(seconds=profile.cooldown_seconds)
                if previous_status != runtime_state.status or previous_error != runtime_state.last_error:
                    notifier.notify_error(profile.name, runtime_state.last_error)
                    events.append(
                        EventRecord(
                            level="WARN",
                            category="cooldown",
                            message="profile entered cooldown",
                            profile_id=profile.profile_id,
                            profile_name=profile.name,
                            details={"cooldown_seconds": profile.cooldown_seconds},
                        )
                    )
                return runtime_state, events

            operation_id = client.start_instance(profile.instance_id)
            runtime_state.status = "starting"
            runtime_state.start_attempts += 1
            runtime_state.last_action = "start-issued"
            runtime_state.last_operation_id = operation_id
            runtime_state.last_error = None
            runtime_state.last_transition_at = now
            runtime_state.next_check_at = now + timedelta(seconds=profile.startup_grace_seconds)
            notifier.notify_start(profile.name, profile.check_host, operation_id)
            events.append(
                EventRecord(
                    level="WARN",
                    category="start",
                    message="start command issued",
                    profile_id=profile.profile_id,
                    profile_name=profile.name,
                    details={"operation_id": operation_id, "host": profile.check_host},
                )
            )
            return runtime_state, events

        if runtime_state.cloud_status == "RUNNING":
            runtime_state.status = "degraded"
            runtime_state.last_action = "running-but-unreachable"
            runtime_state.last_error = "instance is RUNNING but the health check host is unreachable"
            runtime_state.next_check_at = now + timedelta(seconds=profile.check_interval_seconds)
            if previous_status != runtime_state.status or previous_error != runtime_state.last_error:
                notifier.notify_error(profile.name, runtime_state.last_error)
                events.append(
                    EventRecord(
                        level="ERROR",
                        category="health",
                        message="instance is running but unreachable",
                        profile_id=profile.profile_id,
                        profile_name=profile.name,
                        details={"host": profile.check_host},
                    )
                )
            return runtime_state, events

        runtime_state.status = "error"
        runtime_state.last_action = "unhandled-status"
        runtime_state.last_error = f"unhandled cloud status: {runtime_state.cloud_status}"
        runtime_state.next_check_at = now + timedelta(seconds=profile.check_interval_seconds)
        if previous_status != runtime_state.status or previous_error != runtime_state.last_error:
            notifier.notify_error(profile.name, runtime_state.last_error)
            events.append(
                EventRecord(
                    level="ERROR",
                    category="cloud",
                    message="received unhandled cloud status",
                    profile_id=profile.profile_id,
                    profile_name=profile.name,
                    details={"cloud_status": runtime_state.cloud_status},
                )
            )
        return runtime_state, events

    def _evaluate_selectel_profile(
        self,
        profile: VMProfile,
        runtime_state: VMRuntimeState,
        client: SelectelCloudClient,
        notifier: TelegramNotifier,
    ) -> tuple[VMRuntimeState, list[EventRecord]]:
        now = utc_now()
        previous_status = runtime_state.status
        previous_error = runtime_state.last_error
        runtime_state.name = profile.name
        runtime_state.last_check_at = now
        events: list[EventRecord] = []

        reachable = ping_host(profile.check_host, profile.ping_timeout_seconds)
        runtime_state.reachable = reachable

        if reachable:
            runtime_state.status = "online"
            runtime_state.cloud_status = "ACTIVE"
            runtime_state.last_error = None
            runtime_state.last_action = "health-check-ok"
            runtime_state.consecutive_failures = 0
            runtime_state.start_attempts = 0
            runtime_state.last_transition_at = now if previous_status != "online" else runtime_state.last_transition_at
            runtime_state.next_check_at = now + timedelta(seconds=profile.check_interval_seconds)
            if previous_status not in {"unknown", "online", "disabled"}:
                notifier.notify_recovery(profile.name, profile.check_host)
                events.append(
                    EventRecord(
                        level="INFO",
                        category="recovery",
                        message="profile recovered",
                        profile_id=profile.profile_id,
                        profile_name=profile.name,
                        details={"host": profile.check_host},
                    )
                )
            return runtime_state, events

        runtime_state.consecutive_failures += 1

        try:
            if not profile.project_id:
                raise RuntimeError("project_id is required for Selectel profiles")
            cloud_status = client.get_server_status(profile.project_id, profile.instance_id)
            runtime_state.cloud_status = cloud_status
        except Exception as exc:
            runtime_state.status = "error"
            runtime_state.last_error = str(exc)
            runtime_state.last_action = "cloud-status-failed"
            runtime_state.next_check_at = now + timedelta(seconds=min(profile.check_interval_seconds, 60))
            if previous_status != runtime_state.status or previous_error != runtime_state.last_error:
                notifier.notify_error(profile.name, runtime_state.last_error)
                events.append(
                    EventRecord(
                        level="ERROR",
                        category="cloud",
                        message="failed to fetch server status",
                        profile_id=profile.profile_id,
                        profile_name=profile.name,
                        details={"error": runtime_state.last_error},
                    )
                )
            return runtime_state, events

        if runtime_state.cloud_status in {"BUILD", "REBOOT"}:
            runtime_state.status = "starting"
            runtime_state.last_error = None
            runtime_state.last_action = "waiting-for-cloud-start"
            runtime_state.last_transition_at = now if previous_status != "starting" else runtime_state.last_transition_at
            runtime_state.next_check_at = now + timedelta(seconds=max(30, min(profile.startup_grace_seconds, profile.check_interval_seconds)))
            if previous_status != runtime_state.status:
                events.append(
                    EventRecord(
                        level="INFO",
                        category="monitor",
                        message="server is already starting",
                        profile_id=profile.profile_id,
                        profile_name=profile.name,
                        details={"cloud_status": runtime_state.cloud_status},
                    )
                )
            return runtime_state, events

        if runtime_state.cloud_status == "SHUTOFF":
            if not profile.auto_start_stopped:
                runtime_state.status = "stopped"
                runtime_state.last_action = "auto-start-disabled"
                runtime_state.last_error = "server is stopped and auto-start is disabled"
                runtime_state.next_check_at = now + timedelta(seconds=profile.check_interval_seconds)
                if previous_status != runtime_state.status or previous_error != runtime_state.last_error:
                    notifier.notify_error(profile.name, runtime_state.last_error)
                    events.append(
                        EventRecord(
                            level="WARN",
                            category="monitor",
                            message="server is stopped but auto-start is disabled",
                            profile_id=profile.profile_id,
                            profile_name=profile.name,
                        )
                    )
                return runtime_state, events

            if runtime_state.start_attempts >= profile.max_start_attempts:
                runtime_state.status = "cooldown"
                runtime_state.last_action = "cooldown"
                runtime_state.last_error = "max start attempts reached"
                runtime_state.start_attempts = 0
                runtime_state.next_check_at = now + timedelta(seconds=profile.cooldown_seconds)
                if previous_status != runtime_state.status or previous_error != runtime_state.last_error:
                    notifier.notify_error(profile.name, runtime_state.last_error)
                    events.append(
                        EventRecord(
                            level="WARN",
                            category="cooldown",
                            message="profile entered cooldown",
                            profile_id=profile.profile_id,
                            profile_name=profile.name,
                            details={"cooldown_seconds": profile.cooldown_seconds},
                        )
                    )
                return runtime_state, events

            server_id = client.start_server(profile.project_id, profile.instance_id)
            runtime_state.status = "starting"
            runtime_state.start_attempts += 1
            runtime_state.last_action = "start-issued"
            runtime_state.last_operation_id = server_id
            runtime_state.last_error = None
            runtime_state.last_transition_at = now
            runtime_state.next_check_at = now + timedelta(seconds=profile.startup_grace_seconds)
            notifier.notify_start(profile.name, profile.check_host, server_id)
            events.append(
                EventRecord(
                    level="WARN",
                    category="start",
                    message="start command issued",
                    profile_id=profile.profile_id,
                    profile_name=profile.name,
                    details={"operation_id": server_id, "host": profile.check_host},
                )
            )
            return runtime_state, events

        if runtime_state.cloud_status == "ACTIVE":
            runtime_state.status = "degraded"
            runtime_state.last_action = "running-but-unreachable"
            runtime_state.last_error = "server is ACTIVE but the health check host is unreachable"
            runtime_state.next_check_at = now + timedelta(seconds=profile.check_interval_seconds)
            if previous_status != runtime_state.status or previous_error != runtime_state.last_error:
                notifier.notify_error(profile.name, runtime_state.last_error)
                events.append(
                    EventRecord(
                        level="ERROR",
                        category="health",
                        message="server is active but unreachable",
                        profile_id=profile.profile_id,
                        profile_name=profile.name,
                        details={"host": profile.check_host},
                    )
                )
            return runtime_state, events

        runtime_state.status = "error"
        runtime_state.last_action = "unhandled-status"
        runtime_state.last_error = f"unhandled cloud status: {runtime_state.cloud_status}"
        runtime_state.next_check_at = now + timedelta(seconds=profile.check_interval_seconds)
        if previous_status != runtime_state.status or previous_error != runtime_state.last_error:
            notifier.notify_error(profile.name, runtime_state.last_error)
            events.append(
                EventRecord(
                    level="ERROR",
                    category="cloud",
                    message="received unhandled cloud status",
                    profile_id=profile.profile_id,
                    profile_name=profile.name,
                    details={"cloud_status": runtime_state.cloud_status},
                )
            )
        return runtime_state, events

    def _save_state(self, state: AppState, loop_started) -> None:
        state.last_loop_at = loop_started
        self.runtime_repo.save_state(state)

    def _publish_event(self, event: EventRecord) -> None:
        self.runtime_repo.append_event(event)
        level = event.level.upper()
        if level == "ERROR":
            LOGGER.error(event.message)
        elif level == "WARN":
            LOGGER.warning(event.message)
        else:
            LOGGER.info(event.message)

    def _compute_sleep_seconds(self, profiles: list[VMProfile], state: AppState, reload_seconds: int) -> int:
        next_checks = [
            state.profiles[profile.profile_id].next_check_at
            for profile in profiles
            if profile.profile_id in state.profiles and state.profiles[profile.profile_id].next_check_at is not None
        ]
        if not next_checks:
            return min(reload_seconds, 15)
        wait_seconds = int((min(next_checks) - utc_now()).total_seconds())
        if wait_seconds <= 0:
            return 1
        return min(wait_seconds, reload_seconds)

    def _sleep(self, seconds: int) -> None:
        self.stop_event.wait(max(1, seconds))

    def _handle_stop(self, *_args) -> None:
        self.stop_event.set()

    def _handle_reload(self, *_args) -> None:
        self.reload_event.set()
