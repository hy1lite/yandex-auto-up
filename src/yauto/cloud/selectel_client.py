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

    def _get_all_regions_from_catalog(self, catalog: list[dict]) -> list[str]:
        """Extract all available regions from service catalog."""
        regions = set()
        for service in catalog:
            if service.get("type") == "compute":
                for endpoint in service.get("endpoints", []):
                    if endpoint.get("interface") == "public":
                        region = endpoint.get("region")
                        if region:
                            regions.add(region)
        return sorted(regions)

    def list_servers(self, project_id: str) -> list[dict[str, Any]]:
        # Get project-scoped token with catalog
        token_data = self.token_provider.get_token_with_catalog(project_id)
        token = token_data.get("token")
        catalog = token_data.get("catalog", [])
        
        # Debug: print catalog
        print(f"DEBUG: Service catalog has {len(catalog)} services")
        
        # Get all available regions
        regions = self._get_all_regions_from_catalog(catalog)
        print(f"DEBUG: Available regions: {', '.join(regions)}")
        
        # Try to find servers in each region
        all_servers = []
        for region in regions:
            # Find compute endpoint for this region
            compute_url = None
            for service in catalog:
                if service.get("type") == "compute":
                    for endpoint in service.get("endpoints", []):
                        if endpoint.get("interface") == "public" and endpoint.get("region") == region:
                            compute_url = endpoint.get("url", "")
                            break
                    if compute_url:
                        break
            
            if not compute_url:
                continue
            
            # Try to list servers in this region
            # Remove trailing slash from compute_url to avoid double slashes
            compute_url = compute_url.rstrip('/')
            url = f"{compute_url}/servers/detail"
            try:
                response = self.http.get(url, headers={"X-Auth-Token": token})
                if response.status_code == 200:
                    data = response.json()
                    servers = data.get("servers", [])
                    if servers:
                        print(f"DEBUG: Found {len(servers)} server(s) in region {region}")
                        all_servers.extend(servers)
                    else:
                        print(f"DEBUG: No servers in region {region}")
            except Exception as e:
                print(f"DEBUG: Error checking region {region}: {e}")
                continue
        
        print(f"DEBUG: Total servers found across all regions: {len(all_servers)}")
        return all_servers

    def get_server(self, project_id: str, server_id: str) -> dict[str, Any]:
        token_data = self.token_provider.get_token_with_catalog(project_id)
        token = token_data.get("token")
        catalog = token_data.get("catalog", [])
        
        # Get all available regions
        regions = self._get_all_regions_from_catalog(catalog)
        
        # Try to find server in each region
        for region in regions:
            # Find compute endpoint for this region
            compute_url = None
            for service in catalog:
                if service.get("type") == "compute":
                    for endpoint in service.get("endpoints", []):
                        if endpoint.get("interface") == "public" and endpoint.get("region") == region:
                            compute_url = endpoint.get("url", "")
                            break
                    if compute_url:
                        break
            
            if not compute_url:
                continue
            
            # Remove trailing slash to avoid double slashes
            compute_url = compute_url.rstrip('/')
            
            # Try to get server from this region
            url = f"{compute_url}/servers/{server_id}"
            try:
                response = self.http.get(url, headers={"X-Auth-Token": token})
                if response.status_code == 200:
                    data = response.json()
                    return data.get("server", {})
            except Exception:
                continue
        
        return {}

    def get_server_status(self, project_id: str, server_id: str) -> str:
        server = self.get_server(project_id, server_id)
        return server.get("status", "UNKNOWN")

    def start_server(self, project_id: str, server_id: str) -> str:
        token_data = self.token_provider.get_token_with_catalog(project_id)
        token = token_data.get("token")
        catalog = token_data.get("catalog", [])
        
        # Get all available regions
        regions = self._get_all_regions_from_catalog(catalog)
        
        # Try to start server in each region
        for region in regions:
            # Find compute endpoint for this region
            compute_url = None
            for service in catalog:
                if service.get("type") == "compute":
                    for endpoint in service.get("endpoints", []):
                        if endpoint.get("interface") == "public" and endpoint.get("region") == region:
                            compute_url = endpoint.get("url", "")
                            break
                    if compute_url:
                        break
            
            if not compute_url:
                continue
            
            # Remove trailing slash to avoid double slashes
            compute_url = compute_url.rstrip('/')
            
            # Try to start server in this region
            url = f"{compute_url}/servers/{server_id}/action"
            try:
                response = self.http.post(
                    url,
                    headers={"X-Auth-Token": token, "Content-Type": "application/json"},
                    json={"os-start": None}
                )
                if response.status_code in (200, 202):
                    return server_id
            except Exception:
                continue
        
        raise RuntimeError(f"Failed to start server {server_id} in any region")

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
