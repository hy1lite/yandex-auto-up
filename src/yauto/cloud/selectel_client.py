"""Minimal REST client for Selectel Cloud operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from yauto import __version__
from yauto.cloud.selectel_auth import SelectelTokenProvider


class SelectelCloudClient:
    def __init__(self, token_provider: SelectelTokenProvider, region: str = "ru-1", timeout: float = 10.0):
        self.token_provider = token_provider
        self.region = region
        self.timeout = timeout
        self.http = httpx.Client(timeout=timeout, headers={"User-Agent": f"yauto/{__version__}"})
        self.compute_url = f"https://api.selvpc.ru/servers/v2"

    @classmethod
    def from_credentials_file(cls, credentials_file: Path, region: str = "ru-1", timeout: float = 10.0) -> SelectelCloudClient:
        provider = SelectelTokenProvider(credentials_file, timeout=timeout)
        return cls(provider, region=region, timeout=timeout)

    def close(self) -> None:
        self.http.close()

    def ensure_authenticated(self) -> bool:
        try:
            self._get_token()
            return True
        except Exception:
            return False

    def list_projects(self) -> list[dict[str, Any]]:
        # Get account-scoped token for listing projects
        token = self.token_provider.get_token(project_scoped=False)
        # Use OpenStack Keystone API to list projects
        url = "https://cloud.api.selcloud.ru/identity/v3/auth/projects"
        response = self.http.get(url, headers={"X-Auth-Token": token})
        response.raise_for_status()
        data = response.json()
        return data.get("projects", [])

    def list_servers(self, project_id: str) -> list[dict[str, Any]]:
        # Get project-scoped token
        token = self._get_token()
        # Use OpenStack Nova API - project_id is in token scope, not URL
        url = "https://cloud.api.selcloud.ru/compute/v2.1/servers/detail"
        response = self.http.get(url, headers={"X-Auth-Token": token})
        response.raise_for_status()
        data = response.json()
        return data.get("servers", [])

    def get_server(self, project_id: str, server_id: str) -> dict[str, Any]:
        token = self._get_token()
        url = f"https://cloud.api.selcloud.ru/compute/v2.1/servers/{server_id}"
        response = self.http.get(url, headers={"X-Auth-Token": token})
        response.raise_for_status()
        data = response.json()
        return data.get("server", {})

    def get_server_status(self, project_id: str, server_id: str) -> str:
        server = self.get_server(project_id, server_id)
        return server.get("status", "UNKNOWN")

    def start_server(self, project_id: str, server_id: str) -> str:
        token = self._get_token()
        url = f"https://cloud.api.selcloud.ru/compute/v2.1/servers/{server_id}/action"
        response = self.http.post(
            url,
            headers={"X-Auth-Token": token, "Content-Type": "application/json"},
            json={"os-start": None}
        )
        response.raise_for_status()
        return server_id

    @staticmethod
    def extract_primary_ip(server: dict[str, Any]) -> str:
        addresses = server.get("addresses", {})
        for network_name, addr_list in addresses.items():
            for addr in addr_list:
                if addr.get("version") == 4:
                    ip = addr.get("addr", "")
                    if ip and not ip.startswith("10.") and not ip.startswith("192.168."):
                        return ip
        for network_name, addr_list in addresses.items():
            for addr in addr_list:
                if addr.get("version") == 4:
                    return addr.get("addr", "")
        return ""

    def _get_token(self) -> str:
        try:
            return self.token_provider.get_token()
        except Exception as exc:
            raise RuntimeError(f"Failed to get Selectel token: {exc}") from exc
