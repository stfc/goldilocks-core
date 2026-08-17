from __future__ import annotations

import pytest

from goldilocks_core.runtime import Service
from goldilocks_core.server.http import create_app

TestClient = pytest.importorskip("fastapi.testclient").TestClient


class _CountingService(Service):
    """Record preset calls made through one service instance."""

    def __init__(self) -> None:
        super().__init__()
        self.preset_calls = 0

    def run_preset(self, request):
        self.preset_calls += 1
        return super().run_preset(request)


def test_http_reuses_one_service_across_requests(request_body) -> None:
    """Serve multiple requests through the same process service."""
    service = _CountingService()
    try:
        with TestClient(create_app(service)) as client:
            first = client.post("/recommend", json=request_body)
            second = client.post("/recommend", json=request_body)

        assert first.status_code == 200
        assert second.status_code == 200
        assert service.preset_calls == 2
        assert not service.is_closed
    finally:
        service.close()


def test_http_closes_its_owned_service_on_shutdown() -> None:
    """Close the process service (and its runtime) when the app lifespan ends."""
    app = create_app()

    with TestClient(app) as client:
        client.get("/health")
        runtime = app.state.goldilocks.runtime
        assert runtime is not None
        assert not runtime.is_closed

    assert runtime.is_closed
