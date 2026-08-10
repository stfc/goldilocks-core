"""Tests for the bounded computation gate and its server_busy failure."""

import pytest

from goldilocks_core.server.concurrency import (
    RETRY_AFTER_SECONDS,
    ComputeBusyError,
    ComputeGate,
)
from goldilocks_core.server.config import DeploymentConfig
from goldilocks_core.server.http import create_app

TestClient = pytest.importorskip("fastapi.testclient").TestClient


def test_gate_bounds_concurrency_to_limit() -> None:
    """Acquire fails once every configured slot is held."""
    gate = ComputeGate(limit=2, wait_seconds=0)

    gate.acquire()
    gate.acquire()

    with pytest.raises(ComputeBusyError):
        gate.acquire()

    gate.release()
    gate.release()
    gate.acquire()  # A freed slot is reusable.
    gate.release()


def test_gate_context_manager_releases_its_slot() -> None:
    """The gate is a context manager that releases on exit."""
    gate = ComputeGate(limit=1, wait_seconds=0)

    with gate:
        with pytest.raises(ComputeBusyError):
            gate.acquire()

    gate.acquire()  # Released on context exit.
    gate.release()


def test_gate_rejects_invalid_capacity() -> None:
    """Reject non-positive limits and negative wait bounds."""
    with pytest.raises(ValueError):
        ComputeGate(limit=0, wait_seconds=1)
    with pytest.raises(ValueError):
        ComputeGate(limit=1, wait_seconds=-1)


def test_server_busy_maps_to_retryable_503(test_runtime, request_body) -> None:
    """A saturated gate surfaces a structured retryable server_busy response."""
    app = create_app(
        test_runtime,
        config=DeploymentConfig(compute_limit=1, compute_wait_seconds=0),
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        # Occupy the only computation slot directly on the shared gate.
        gate = app.state.goldilocks.gate
        gate.acquire()
        try:
            response = client.post("/recommend", json=request_body)
        finally:
            gate.release()

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["kind"] == "server_busy"
    assert error["status"] == 503
    assert error["details"] == {"retryable": True}
    assert response.headers["retry-after"] == str(RETRY_AFTER_SECONDS)


def test_computation_succeeds_when_a_slot_is_free(test_runtime, request_body) -> None:
    """A free slot still serves a normal computation."""
    app = create_app(
        test_runtime,
        config=DeploymentConfig(compute_limit=2, compute_wait_seconds=5.0),
    )

    with TestClient(app) as client:
        response = client.post("/recommend", json=request_body)

    assert response.status_code == 200
    assert response.json()["analysis"]["reduced_formula"] == "Si"


def test_parallel_http_computations_do_not_corrupt_shared_runtime(
    test_runtime, request_body
) -> None:
    """Concurrent HTTP computations serialize through the shared runtime seam.

    Fires many parallel /recommend requests over the ASGI transport against one
    runtime and asserts every result is complete and correct, proving shared
    runtime execution and lazy initialization cannot overlap or corrupt state.
    """
    import asyncio

    import httpx

    app = create_app(
        test_runtime,
        config=DeploymentConfig(compute_limit=8, compute_wait_seconds=30.0),
    )

    async def run():
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:

                async def fire(_: int):
                    return await client.post("/recommend", json=request_body)

                responses = await asyncio.gather(*(fire(i) for i in range(8)))
                return responses

    responses = asyncio.run(run())
    assert len(responses) == 8
    for response in responses:
        assert response.status_code == 200
        data = response.json()
        assert data["analysis"]["reduced_formula"] == "Si"
        assert data["k_points"]["grid"] == [3, 3, 3]
        assert data["core_version"]
        assert data["selection"]["pseudopotentials"][0]["element"] == "Si"
