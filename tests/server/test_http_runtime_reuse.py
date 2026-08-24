from __future__ import annotations

import pytest

from goldilocks_core.runtime import Service
from goldilocks_core.server.http import create_app

TestClient = pytest.importorskip("fastapi.testclient").TestClient


class _CountingService(Service):
    def __init__(self) -> None:
        super().__init__()
        self.computation_calls = 0

    def compute(self, request):
        self.computation_calls += 1
        return super().compute(request)


def test_http_reuses_one_service_across_requests(request_body) -> None:
    service = _CountingService()
    try:
        with TestClient(create_app(service)) as client:
            first = client.post("/recommend", json=request_body)
            second = client.post("/recommend", json=request_body)

        assert first.status_code == 200
        assert second.status_code == 200
        assert service.computation_calls == 2
        assert not service.is_closed
    finally:
        service.close()


def test_http_closes_its_owned_service_on_shutdown() -> None:
    app = create_app()

    with TestClient(app) as client:
        client.get("/health")
        runtime = app.state.goldilocks.runtime
        assert runtime is not None
        assert not runtime.is_closed

    assert runtime.is_closed
