from fastapi.testclient import TestClient

from ragops.config import Settings
from ragops.main import create_app


def test_health_and_request_id() -> None:
    app = create_app(Settings(environment="test", _env_file=None))

    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Request-ID": "test-request-42"})

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["X-Request-ID"] == "test-request-42"


def test_invalid_request_id_is_replaced() -> None:
    app = create_app(Settings(environment="test", _env_file=None))

    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Request-ID": "contains spaces"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "contains spaces"


def test_api_key_is_optional_but_enforced_when_configured() -> None:
    app = create_app(Settings(environment="test", api_key="expected", _env_file=None))

    with TestClient(app) as client:
        rejected = client.post(
            "/v1/search",
            json={
                "workspace_id": "00000000-0000-0000-0000-000000000001",
                "query": "hello",
            },
        )

    assert rejected.status_code == 401
    assert rejected.headers["X-Request-ID"]


def test_metrics_are_prometheus_text() -> None:
    app = create_app(Settings(environment="test", _env_file=None))

    with TestClient(app) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    assert "ragops_http_requests_total" in response.text
    assert response.headers["content-type"].startswith("text/plain")
