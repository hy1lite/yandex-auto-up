"""Minimal REST client for Yandex Cloud operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from yauto import __version__
from yauto.cloud.auth import ServiceAccountTokenProvider

RESOURCE_MANAGER_URL = "https://resource-manager.api.cloud.yandex.net/resource-manager/v1"
COMPUTE_URL = "https://compute.api.cloud.yandex.net/compute/v1"


class CloudApiError(RuntimeError):
    pass


class YandexCloudClient:
    def __init__(self, token_provider: ServiceAccountTokenProvider | list[ServiceAccountTokenProvider], timeout: float = 10.0):
        if isinstance(token_provider, ServiceAccountTokenProvider):
            self.token_providers = [token_provider]
        else:
            self.token_providers = list(token_provider)
        if not self.token_providers:
            raise ValueError("at least one service account provider is required")
        self.http = httpx.Client(timeout=timeout, headers={"User-Agent": f"yauto/{__version__}"})
        self._provider_cache: dict[str, ServiceAccountTokenProvider] = {}

    @classmethod
    def from_service_account_files(cls, files: list[Path], timeout: float = 10.0) -> YandexCloudClient:
        providers = [ServiceAccountTokenProvider(path, timeout=timeout) for path in files]
        return cls(providers, timeout=timeout)

    def close(self) -> None:
        self.http.close()

    def ensure_authenticated(self) -> int:
        authenticated = 0
        errors: list[str] = []

        for provider in self.token_providers:
            try:
                self._get_provider_token(provider)
            except CloudApiError as exc:
                errors.append(self._describe_provider_error(provider, exc))
                continue
            authenticated += 1

        if not authenticated:
            raise CloudApiError(self._combine_provider_errors(errors))
        return authenticated

    def list_clouds(self) -> list[dict[str, Any]]:
        return self._collect("clouds", "GET", f"{RESOURCE_MANAGER_URL}/clouds")

    def list_folders(self, cloud_id: str) -> list[dict[str, Any]]:
        return self._collect("folders", "GET", f"{RESOURCE_MANAGER_URL}/folders", params={"cloudId": cloud_id})

    def list_instances(self, folder_id: str) -> list[dict[str, Any]]:
        return self._collect("instances", "GET", f"{COMPUTE_URL}/instances", params={"folderId": folder_id})

    def get_instance(self, instance_id: str) -> dict[str, Any]:
        return self._request("GET", f"{COMPUTE_URL}/instances/{instance_id}", cache_key=f"instance:{instance_id}")

    def get_instance_status(self, instance_id: str) -> str:
        payload = self.get_instance(instance_id)
        return payload.get("status", "UNKNOWN")

    def start_instance(self, instance_id: str) -> str:
        payload = self._request("POST", f"{COMPUTE_URL}/instances/{instance_id}:start", cache_key=f"instance:{instance_id}")
        return payload.get("id", "")

    def _collect(self, collection_key: str, method: str, url: str, **kwargs: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        errors: list[str] = []
        success = False

        for provider in self.token_providers:
            try:
                payload = self._request_with_provider(provider, method, url, **kwargs)
            except CloudApiError as exc:
                errors.append(self._describe_provider_error(provider, exc))
                continue

            success = True
            for item in payload.get(collection_key, []):
                item_id = str(item.get("id", "")).strip()
                if item_id and item_id in seen_ids:
                    continue
                if item_id:
                    seen_ids.add(item_id)
                items.append(item)

        if not success:
            raise CloudApiError(self._combine_provider_errors(errors))
        return items

    def _request(self, method: str, url: str, cache_key: str | None = None, **kwargs: Any) -> dict[str, Any]:
        errors: list[str] = []
        cached_provider = self._provider_cache.get(cache_key) if cache_key else None

        if cached_provider is not None:
            try:
                return self._request_with_provider(cached_provider, method, url, **kwargs)
            except CloudApiError as exc:
                errors.append(self._describe_provider_error(cached_provider, exc))

        for provider in self.token_providers:
            if provider is cached_provider:
                continue
            try:
                payload = self._request_with_provider(provider, method, url, **kwargs)
                if cache_key:
                    self._provider_cache[cache_key] = provider
                return payload
            except CloudApiError as exc:
                errors.append(self._describe_provider_error(provider, exc))

        raise CloudApiError(self._combine_provider_errors(errors))

    def _request_with_provider(self, provider: ServiceAccountTokenProvider, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        token = self._get_provider_token(provider)

        request_kwargs = dict(kwargs)
        headers = dict(request_kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {token}"
        response = self.http.request(method, url, headers=headers, **request_kwargs)
        if response.is_error:
            raise CloudApiError(self._format_error(response))
        return response.json()

    @staticmethod
    def _get_provider_token(provider: ServiceAccountTokenProvider) -> str:
        try:
            return provider.get_token()
        except Exception as exc:
            raise CloudApiError(str(exc)) from exc

    @staticmethod
    def _describe_provider_error(provider: ServiceAccountTokenProvider, error: CloudApiError) -> str:
        return f"{provider.service_account_file}: {error}"

    @staticmethod
    def _combine_provider_errors(errors: list[str]) -> str:
        if not errors:
            return "all configured service accounts failed"
        return "all configured service accounts failed: " + " | ".join(errors)

    @staticmethod
    def extract_primary_ip(instance: dict[str, Any]) -> str:
        interfaces = instance.get("networkInterfaces", [])
        if not interfaces:
            return ""
        address = interfaces[0].get("primaryV4Address", {})
        nat = address.get("oneToOneNat", {})
        return nat.get("address") or address.get("address") or ""

    @staticmethod
    def _format_error(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        return f"{response.status_code}: {payload}"
