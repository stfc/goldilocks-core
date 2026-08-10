from __future__ import annotations

import pytest

from goldilocks_core.runtime import CoreRuntime
from goldilocks_core.server.http import create_app

TestClient = pytest.importorskip("fastapi.testclient").TestClient


class _CountingRuntime(CoreRuntime):
    """Record recommend calls made through one runtime instance."""

    def __init__(self) -> None:
        super().__init__()
        self.recommend_calls = 0

    def recommend(self, request):
        self.recommend_calls += 1
        return super().recommend(request)


def test_http_reuses_one_runtime_across_requests(request_body) -> None:
    """Serve multiple requests through the same process runtime."""
    runtime = _CountingRuntime()
    try:
        with TestClient(create_app(runtime)) as client:
            first = client.post("/recommend", json=request_body)
            second = client.post("/recommend", json=request_body)

        assert first.status_code == 200
        assert second.status_code == 200
        assert runtime.recommend_calls == 2
        assert not runtime.is_closed
    finally:
        runtime.close()


def test_http_closes_its_owned_runtime_on_shutdown() -> None:
    """Close the process runtime when the app lifespan ends."""
    app = create_app()

    with TestClient(app) as client:
        client.get("/health")
        runtime = app.state.goldilocks.runtime
        assert runtime is not None
        assert not runtime.is_closed

    assert runtime.is_closed
