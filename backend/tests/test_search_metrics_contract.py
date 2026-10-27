from fastapi.testclient import TestClient

from ragops.config import Settings
from ragops.main import create_app


def test_search_counter_increments_for_the_locked_router_template() -> None:
    app = create_app(Settings(environment="test", _env_file=None))
    with TestClient(app) as client:
        before = client.get("/metrics").text
        response = client.post("/v1/search", json={})
        after = client.get("/metrics").text
    assert response.status_code == 422
    expected = 'ragops_http_requests_total{method="POST",route="/search",status="422"}'
    assert expected in after, after
    def count(snapshot: str) -> float:
        values = [line.split()[-1] for line in snapshot.splitlines() if line.startswith(expected)]
        return sum(float(value) for value in values)
    assert count(after) - count(before) == 1
