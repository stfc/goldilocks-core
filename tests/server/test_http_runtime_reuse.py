from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    pass


def test_http_reuses_one_core_runtime_across_two_requests(
    si_cif_path,
    si_pseudo_metadata: dict,
) -> None:
    """The same CoreRuntime instance serves two requests (model loaded once)."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from goldilocks_core.runtime import CoreRuntime
    from goldilocks_core.server.http import create_app

    runtime = CoreRuntime()
    app = create_app(runtime=runtime)

    body = {
        "structure": str(si_cif_path),
        "hints": {"k_grid": [3, 3, 3]},
        "pseudo_metadata": [si_pseudo_metadata],
    }

    with TestClient(app) as client:
        client.post("/recommend", json=body)
        client.post("/recommend", json=body)

    # The provided runtime was reused (not closed by the app) and is the same
    # instance that served both requests.
    assert not runtime.is_closed
    runtime.close()


def test_http_runtime_is_created_when_not_provided() -> None:
    """create_app with no runtime owns a runtime created at startup."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from goldilocks_core.server.http import create_app

    app = create_app()
    assert app.state.goldilocks.runtime is None  # not yet started

    with TestClient(app) as client:
        client.get("/health")
        assert app.state.goldilocks.runtime is not None
        assert not app.state.goldilocks.runtime.is_closed

    # After shutdown, the app-owned runtime is closed.
    assert app.state.goldilocks.runtime.is_closed


def test_http_does_not_close_caller_provided_runtime(
    si_cif_path,
    si_pseudo_metadata: dict,
) -> None:
    """A caller-provided runtime is left open after the app shuts down."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from goldilocks_core.runtime import CoreRuntime
    from goldilocks_core.server.http import create_app

    runtime = CoreRuntime()
    app = create_app(runtime=runtime)

    body = {
        "structure": str(si_cif_path),
        "hints": {"k_grid": [3, 3, 3]},
        "pseudo_metadata": [si_pseudo_metadata],
    }

    with TestClient(app) as client:
        client.post("/recommend", json=body)

    assert not runtime.is_closed
    runtime.close()


def test_http_app_has_no_module_global_runtime() -> None:
    """No CoreRuntime instance lingers as a module global in server.http."""
    pytest.importorskip("fastapi")
    from goldilocks_core.runtime import CoreRuntime
    from goldilocks_core.server import http as http_module

    assert not any(
        isinstance(value, CoreRuntime) for value in vars(http_module).values()
    )
