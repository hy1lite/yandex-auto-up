from pathlib import Path

import httpx

from yauto.cloud.auth import ServiceAccountTokenProvider
from yauto.cloud.client import CloudApiError, YandexCloudClient


class DummyProvider(ServiceAccountTokenProvider):
    def __init__(self, label: str, token: str = "", token_error: str | None = None):
        self.service_account_file = Path(label)
        self.token = token
        self.token_error = token_error
        self.timeout = 10.0
        self._cached = None

    def get_token(self) -> str:
        if self.token_error is not None:
            raise ValueError(self.token_error)
        return self.token


class FakeHTTPClient:
    def __init__(self, responses):
        self.responses = responses

    def request(self, method: str, url: str, headers=None, **kwargs):
        headers = headers or {}
        token = headers.get("Authorization", "").replace("Bearer ", "")
        params = tuple(sorted((kwargs.get("params") or {}).items()))
        status_code, payload = self.responses[(token, method, url, params)]
        request = httpx.Request(method, url, headers=headers, params=dict(params))
        return httpx.Response(status_code, json=payload, request=request)

    def close(self) -> None:
        return None


def test_list_clouds_aggregates_multiple_service_accounts():
    provider_a = DummyProvider("a.json", "token-a")
    provider_b = DummyProvider("b.json", "token-b")
    client = YandexCloudClient([provider_a, provider_b])
    client.http = FakeHTTPClient(
        {
            ("token-a", "GET", "https://resource-manager.api.cloud.yandex.net/resource-manager/v1/clouds", ()): (200, {"clouds": [{"id": "cloud-a", "name": "Cloud A"}]}),
            ("token-b", "GET", "https://resource-manager.api.cloud.yandex.net/resource-manager/v1/clouds", ()): (200, {"clouds": [{"id": "cloud-a", "name": "Cloud A"}, {"id": "cloud-b", "name": "Cloud B"}]}),
        }
    )

    clouds = client.list_clouds()

    assert [cloud["id"] for cloud in clouds] == ["cloud-a", "cloud-b"]


def test_ensure_authenticated_succeeds_without_cloud_listing_permissions():
    provider = DummyProvider("folder-only.json", "token-folder")
    client = YandexCloudClient([provider])

    authenticated = client.ensure_authenticated()

    assert authenticated == 1


def test_get_instance_status_falls_back_to_next_service_account():
    provider_a = DummyProvider("a.json", "token-a")
    provider_b = DummyProvider("b.json", "token-b")
    client = YandexCloudClient([provider_a, provider_b])
    client.http = FakeHTTPClient(
        {
            ("token-a", "GET", "https://compute.api.cloud.yandex.net/compute/v1/instances/instance-1", ()): (403, {"message": "forbidden"}),
            ("token-b", "GET", "https://compute.api.cloud.yandex.net/compute/v1/instances/instance-1", ()): (200, {"id": "instance-1", "status": "RUNNING"}),
        }
    )

    status = client.get_instance_status("instance-1")

    assert status == "RUNNING"


def test_get_instance_status_reports_all_provider_failures():
    provider_a = DummyProvider("a.json", "token-a")
    provider_b = DummyProvider("b.json", "token-b")
    client = YandexCloudClient([provider_a, provider_b])
    client.http = FakeHTTPClient(
        {
            ("token-a", "GET", "https://compute.api.cloud.yandex.net/compute/v1/instances/instance-1", ()): (403, {"message": "forbidden"}),
            ("token-b", "GET", "https://compute.api.cloud.yandex.net/compute/v1/instances/instance-1", ()): (404, {"message": "not found"}),
        }
    )

    try:
        client.get_instance_status("instance-1")
    except CloudApiError as exc:
        message = str(exc)
    else:
        raise AssertionError("CloudApiError was not raised")

    assert "a.json" in message
    assert "b.json" in message


def test_ensure_authenticated_reports_all_provider_failures():
    provider_a = DummyProvider("a.json", token_error="broken-a")
    provider_b = DummyProvider("b.json", token_error="broken-b")
    client = YandexCloudClient([provider_a, provider_b])

    try:
        client.ensure_authenticated()
    except CloudApiError as exc:
        message = str(exc)
    else:
        raise AssertionError("CloudApiError was not raised")

    assert "a.json" in message
    assert "b.json" in message