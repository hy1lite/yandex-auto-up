"""Service account authentication for Selectel Cloud."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from yauto.models import SelectelCredentials

SELECTEL_AUTH_URL = "https://cloud.api.selcloud.ru/identity/v3/auth/tokens"


@dataclass
class CachedToken:
    token: str
    expires_at: datetime


class SelectelTokenProvider:
    def __init__(self, credentials_file: Path, timeout: float = 10.0):
        self.credentials_file = credentials_file
        self.timeout = timeout
        self._cached: CachedToken | None = None

    def is_configured(self) -> bool:
        return self.credentials_file.exists()

    def load_credentials(self) -> SelectelCredentials:
        payload = self.credentials_file.read_text(encoding="utf-8")
        return SelectelCredentials.model_validate_json(payload)

    def get_token(self, project_scoped: bool = True) -> str:
        now = datetime.now(timezone.utc)
        if self._cached and self._cached.expires_at - now > timedelta(seconds=60):
            return self._cached.token

        creds = self.load_credentials()
        
        auth_payload = {
            "auth": {
                "identity": {
                    "methods": ["password"],
                    "password": {
                        "user": {
                            "name": creds.username,
                            "domain": {"name": creds.account_id},
                            "password": creds.password
                        }
                    }
                }
            }
        }

        if project_scoped and creds.project_id:
            auth_payload["auth"]["scope"] = {
                "project": {
                    "id": creds.project_id
                }
            }
        else:
            auth_payload["auth"]["scope"] = {
                "domain": {"name": creds.account_id}
            }

        response = httpx.post(
            SELECTEL_AUTH_URL,
            json=auth_payload,
            timeout=self.timeout
        )
        response.raise_for_status()
        
        token = response.headers.get("X-Subject-Token")
        if not token:
            raise RuntimeError("No X-Subject-Token in response")
        
        self._cached = CachedToken(token=token, expires_at=now + timedelta(hours=23))
        return token
