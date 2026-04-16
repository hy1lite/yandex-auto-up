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
    catalog: list[dict] | None = None


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
        token_data = self.get_token_with_catalog(project_scoped=project_scoped)
        return token_data.get("token")
    
    def get_token_with_catalog(self, project_id: str | None = None, project_scoped: bool = True) -> dict:
        """Get token with service catalog. Returns dict with 'token' and 'catalog' keys."""
        now = datetime.now(timezone.utc)
        if self._cached and self._cached.expires_at - now > timedelta(seconds=60):
            return {"token": self._cached.token, "catalog": self._cached.catalog or []}

        creds = self.load_credentials()
        
        # Use provided project_id or fall back to credentials
        target_project_id = project_id or creds.project_id
        
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

        if project_scoped and target_project_id:
            auth_payload["auth"]["scope"] = {
                "project": {
                    "id": target_project_id
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
        
        # Extract service catalog from response body
        response_data = response.json()
        catalog = response_data.get("token", {}).get("catalog", [])
        
        self._cached = CachedToken(token=token, expires_at=now + timedelta(hours=23), catalog=catalog)
        return {"token": token, "catalog": catalog}
