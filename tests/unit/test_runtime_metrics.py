from __future__ import annotations

from fastapi.testclient import TestClient

from ai_bridge.control import metrics
from ai_bridge.control.app import create_app


def test_http_metrics_use_route_templates(monkeypatch, tmp_path):
    requests = []
    durations = []
    monkeypatch.setattr(metrics, "record_http_request", lambda method, endpoint, status: requests.append((method, endpoint, status)))
    monkeypatch.setattr(metrics, "record_http_duration", lambda method, endpoint, duration: durations.append((method, endpoint, duration)))

    client = TestClient(create_app(admin_token="metrics-test", db_path=tmp_path / "control.db"))
    response = client.get("/health")
    assert response.status_code == 200
    assert ("GET", "/health", 200) in requests
    assert any(method == "GET" and endpoint == "/health" and duration >= 0 for method, endpoint, duration in durations)
