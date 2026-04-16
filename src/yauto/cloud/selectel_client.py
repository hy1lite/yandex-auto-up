"""Minimal REST client for Selectel Cloud operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from yauto import __version__
from yauto.cloud.selectel_auth import SelectelTokenProvider


class SelectelCloudClient:
    def __init__(self, token_provider: SelectelTokenProvider, region: str = "ru-3", timeout: float = 10.0):
        self.token_provider = token_provider
        self.region = region
        self.timeout = timeout
        self.http = httpx.Client(timeout=timeout, headers={"User-Agent": f"yauto/{__version__}"})

    @classmethod
    def from_credentials_file(cls, credentials_file: Path, region: str = "ru-3", timeout: float = 10.0) -> SelectelCloudClient:
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

    def _get_project_region(self, project_id: str) -> str:
        """Get the region where the project is located."""
        # Get account-scoped token to query project details
        token = self.token_provider.get_token(project_scoped=False)
        
        # Query project details from resell API
        url = f"https://api.selectel.ru/vpc/resell/v2/projects/{project_id}"
        response = self.http.get(url, headers={"X-Auth-Token": token})
        response.raise_for_status()
        
        project_data = response.json()
        project = project_data.get("project", {})
        
        # Extract region from project quotas
        # Selectel stores region info in quotas
        quotas = project.get("quotas", {})
        for quota in quotas.get("resources", []):
            region = quota.get("region")
            if region:
                print(f"DEBUG: Project region detected: {region}")
                return region
        
        # Fallback to default region
        print(f"DEBUG: Could not detect project region, using default: {self.region}")
        return self.region
    
    def _get_compute_endpoint(self, project_id: str) -> str:
        """Get compute endpoint from service catalog for the project's region."""
        # Get project-scoped token which includes service catalog
        token_data = self.token_provider.get_token_with_catalog(project_id)
        catalog = token_data.get("catalog", [])
        
        # Detect project region
        project_region = self._get_project_region(project_id)
        
        # Find compute service endpoint for the project's region
        for service in catalog:
            if service.get("type") == "compute":
                for endpoint in service.get("endpoints", []):
                    if endpoint.get("interface") == "public" and endpoint.get("region") == project_region:
                        url = endpoint.get("url", "")
                        print(f"DEBUG: Using compute endpoint for region {project_region}: {url}")
                        return url
        
        # Fallback: construct URL from detected region
        print(f"DEBUG: No endpoint found in catalog for region {project_region}, constructing URL")
        return f"https://{project_region}.cloud.api.selcloud.ru/compute/v2.1"

    def list_servers(self, project_id: str) -> list[dict[str, Any]]:
        # Get project-scoped token with catalog
        token_data = self.token_provider.get_token_with_catalog(project_id)
        token = token_data.get("token")
        catalog = token_data.get("catalog", [])
        
        # Debug: print catalog
        print(f"DEBUG: Service catalog has {len(catalog)} services")
        for service in catalog:
            if service.get("type") == "compute":
                print(f"DEBUG: Found compute service: {service.get('name')}")
                for endpoint in service.get("endpoints", []):
                    print(f"DEBUG: Endpoint: region={endpoint.get('region')}, interface={endpoint.get('interface')}, url={endpoint.get('url')}")
        
        # Get compute endpoint from catalog
        compute_url = self._get_compute_endpoint(project_id)
        
        # OpenStack Nova API: GET /servers/detail
        url = f"{compute_url}/servers/detail"
        print(f"DEBUG: Requesting servers from: {url}")
        response = self.http.get(url, headers={"X-Auth-Token": token})
        print(f"DEBUG: Response status: {response.status_code}")
        print(f"DEBUG: Response body: {response.text[:500]}")
        response.raise_for_status()
        data = response.json()
        servers = data.get("servers", [])
        print(f"DEBUG: Found {len(servers)} servers")
        return servers

    def get_server(self, project_id: str, server_id: str) -> dict[str, Any]:
        token_data = self.token_provider.get_token_with_catalog(project_id)
        token = token_data.get("token")
        compute_url = self._get_compute_endpoint(project_id)
        url = f"{compute_url}/servers/{server_id}"
        response = self.http.get(url, headers={"X-Auth-Token": token})
        response.raise_for_status()
        data = response.json()
        return data.get("server", {})

    def get_server_status(self, project_id: str, server_id: str) -> str:
        server = self.get_server(project_id, server_id)
        return server.get("status", "UNKNOWN")

    def start_server(self, project_id: str, server_id: str) -> str:
        token_data = self.token_provider.get_token_with_catalog(project_id)
        token = token_data.get("token")
        compute_url = self._get_compute_endpoint(project_id)
        url = f"{compute_url}/servers/{server_id}/action"
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
