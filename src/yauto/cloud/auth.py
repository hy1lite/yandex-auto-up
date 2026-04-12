"""Service account authentication for Yandex Cloud."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import jwt

from yauto.models import ServiceAccountKey

IAM_TOKEN_URL = "https://iam.api.cloud.yandex.net/iam/v1/tokens"


@dataclass
class CachedToken:
    token: str
    expires_at: datetime


class ServiceAccountTokenProvider:
    def __init__(self, service_account_file: Path, timeout: float = 10.0):
        self.service_account_file = service_account_file
        self.timeout = timeout
        self._cached: CachedToken | None = None

    def is_configured(self) -> bool:
        return self.service_account_file.exists()

    def load_key(self) -> ServiceAccountKey:
        payload = self.service_account_file.read_text(encoding="utf-8")
        return ServiceAccountKey.model_validate_json(payload)

    def get_token(self) -> str:
        now = datetime.now(timezone.utc)
        if self._cached and self._cached.expires_at - now > timedelta(seconds=60):
            return self._cached.token

        key = self.load_key()
        issued_at = int(now.timestamp())
        payload = {
            "aud": IAM_TOKEN_URL,
            "iss": key.service_account_id,
            "iat": issued_at,
            "exp": issued_at + 360,
        }
        encoded = jwt.encode(
            payload,
            key.private_key,
            algorithm="PS256",
            headers={"kid": key.id},
        )

        response = httpx.post(IAM_TOKEN_URL, json={"jwt": encoded}, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        token = data["iamToken"]
        self._cached = CachedToken(token=token, expires_at=now + timedelta(hours=1))
        return token
