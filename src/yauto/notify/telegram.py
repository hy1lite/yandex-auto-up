"""Telegram notifications."""

from __future__ import annotations

from datetime import datetime

import httpx

from yauto.models import TelegramConfig


class TelegramNotifier:
    def __init__(self, config: TelegramConfig, timeout: float = 10.0):
        self.config = config
        self.timeout = timeout

    def configured(self) -> bool:
        return self.config.enabled and bool(self.config.bot_token and self.config.chat_id)

    def test_connection(self) -> tuple[bool, str]:
        if not self.config.bot_token:
            return False, "Bot token is missing."
        try:
            response = httpx.get(
                f"https://api.telegram.org/bot{self.config.bot_token}/getMe",
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("ok"):
                username = payload.get("result", {}).get("username", "unknown")
                return True, f"Telegram bot @{username} is reachable."
            return False, "Telegram API returned an unexpected response."
        except Exception as exc:  # pragma: no cover - network failure path
            return False, str(exc)

    def send(self, text: str) -> bool:
        if not self.configured():
            return False
        try:
            response = httpx.post(
                f"https://api.telegram.org/bot{self.config.bot_token}/sendMessage",
                json={
                    "chat_id": self.config.chat_id,
                    "text": text,
                    "disable_web_page_preview": True,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            return True
        except Exception:
            return False

    def notify_start(self, profile_name: str, host: str, operation_id: str) -> None:
        if self.config.notify_on_start:
            self.send(
                f"[yandex auto up] start issued\n"
                f"profile: {profile_name}\n"
                f"host: {host}\n"
                f"operation: {operation_id or 'n/a'}\n"
                f"time: {datetime.utcnow().isoformat()}Z"
            )

    def notify_recovery(self, profile_name: str, host: str) -> None:
        if self.config.notify_on_recovery:
            self.send(
                f"[yandex auto up] recovered\n"
                f"profile: {profile_name}\n"
                f"host: {host}\n"
                f"time: {datetime.utcnow().isoformat()}Z"
            )

    def notify_error(self, profile_name: str, message: str) -> None:
        if self.config.notify_on_error:
            self.send(
                f"[yandex auto up] issue\n"
                f"profile: {profile_name}\n"
                f"message: {message}\n"
                f"time: {datetime.utcnow().isoformat()}Z"
            )
