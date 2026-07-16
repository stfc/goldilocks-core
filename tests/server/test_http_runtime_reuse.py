from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.contracts import KPointAdvice, KPointSelection, Provenance
from goldilocks_core.jobs import CoreRuntime, Pipeline

if TYPE_CHECKING:
    pass


def _si_cif() -> str:
    """Return CIF text for a small Si structure."""
    return Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]]).to(fmt="cif")


def _tracking_kmesh(calls: dict[str, int]):
    """Return a k-mesh backend that counts invocations and reuses one object."""

    def kmesh(structure, hints, advice: KPointAdvice) -> KPointSelection:  # noqa: ANN001
        calls["count"] += 1
        return KPointSelection(
            grid=hints.k_grid or (1, 1, 1),
            shift=(0, 0, 0),
            mesh_type=advice.mesh_type,
            provenance=Provenance(source="user_hint", reason="test"),
        )

    return kmesh


def _make_upf(*, element: str, pseudo_type: str, functional: str) -> str:
    """Return a minimal UPF string that parse_upf_metadata can read."""
    return (
        "<UPF>"
        f'<PP_HEADER element="{element}" '
        f'pseudo_type="{pseudo_type}" '
        f'functional="{functional}" '
        f'relativistic="scalar" '
        f'z_valence="4.0" />'
        "</UPF>"
    )


def _recommend_body() -> dict:
    """Return a /recommend body with an explicit k-grid hint."""
    return {
        "structure": {"content": _si_cif(), "format": "cif"},
        "hints": {"k_grid": [3, 3, 3]},
    }


def test_two_requests_share_one_runtime_and_one_kmesh_backend() -> None:
    """One app-owned runtime serves repeated requests without rebuilding backends."""
    from fastapi.testclient import TestClient

    from goldilocks_core.server.http import create_app

    calls: dict[str, int] = {"count": 0}
    runtime = CoreRuntime(pipeline=Pipeline(kmesh=_tracking_kmesh(calls)))
    app = create_app(runtime=runtime, bundle_root=Path("/tmp/bundles"))

    with TestClient(app) as client:
        first = client.post("/recommend", json=_recommend_body())
        second = client.post("/recommend", json=_recommend_body())

    assert first.status_code == 200
    assert second.status_code == 200
    # One shared kmesh object served both requests; a per-request pipeline would
    # have reset the counter each time.
    assert calls["count"] == 2


def test_app_owned_runtime_is_closed_on_shutdown() -> None:
    """The runtime built by the lifespan is closed when the app shuts down."""
    from fastapi.testclient import TestClient

    from goldilocks_core.server.http import create_app

    app = create_app(bundle_root=Path("/tmp/bundles"))

    with TestClient(app) as client:
        runtime = app.state.goldilocks.runtime
        assert runtime is not None
        assert not runtime.is_closed
        assert client.post("/recommend", json=_recommend_body()).status_code == 200

    assert runtime.is_closed


def test_app_owned_runtime_is_closed_even_without_requests() -> None:
    """Startup then immediate shutdown still closes the app-owned runtime."""
    from fastapi.testclient import TestClient

    from goldilocks_core.server.http import create_app

    app = create_app(bundle_root=Path("/tmp/bundles"))

    with TestClient(app):
        runtime = app.state.goldilocks.runtime
        assert runtime is not None

    assert runtime.is_closed


def test_provided_runtime_is_not_closed_by_app() -> None:
    """A caller-provided runtime stays open after shutdown for the caller to manage."""
    from fastapi.testclient import TestClient

    from goldilocks_core.server.http import create_app

    calls: dict[str, int] = {"count": 0}
    runtime = CoreRuntime(pipeline=Pipeline(kmesh=_tracking_kmesh(calls)))
    app = create_app(runtime=runtime, bundle_root=Path("/tmp/bundles"))

    with TestClient(app) as client:
        assert client.post("/recommend", json=_recommend_body()).status_code == 200

    assert not runtime.is_closed
    runtime.close()
    assert runtime.is_closed


def test_default_pseudo_metadata_is_loaded_once_at_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Configured pseudo metadata loads at startup and is reused for every request."""
    import goldilocks_core.server.http as server_http

    pseudo_root = tmp_path / "pseudos" / "pslibrary"
    pseudo_root.mkdir(parents=True)
    (pseudo_root / "Si.pbe-n-nc.UPF").write_text(
        _make_upf(element="Si", pseudo_type="NC", functional="PBE")
    )

    loads = {"count": 0}
    original = server_http.load_pseudo_metadata

    def counting_loader(root: object) -> object:
        loads["count"] += 1
        return original(root)

    monkeypatch.setattr(server_http, "load_pseudo_metadata", counting_loader)

    from fastapi.testclient import TestClient

    from goldilocks_core.server.http import create_app

    app = create_app(pseudo_root=pseudo_root, bundle_root=tmp_path / "bundles")

    with TestClient(app) as client:
        first = client.post("/recommend", json=_recommend_body())
        second = client.post("/recommend", json=_recommend_body())

    assert first.status_code == 200
    assert second.status_code == 200
    assert loads["count"] == 1
    for response in (first, second):
        selection = response.json()["selection"]["pseudopotentials"]
        assert any(p["filename"] == "Si.pbe-n-nc.UPF" for p in selection)


def test_request_pseudo_metadata_overrides_configured_default(
    tmp_path: Path,
) -> None:
    """Per-request pseudo_metadata overrides the configured default."""
    pseudo_root = tmp_path / "pseudos" / "pslibrary"
    pseudo_root.mkdir(parents=True)
    (pseudo_root / "Si.pbe-n-nc.UPF").write_text(
        _make_upf(element="Si", pseudo_type="NC", functional="PBE")
    )

    from fastapi.testclient import TestClient

    from goldilocks_core.server.http import create_app

    app = create_app(pseudo_root=pseudo_root, bundle_root=tmp_path / "bundles")
    override = {
        "filepath": "/override/Si.UPF",
        "filename": "Si.override.UPF",
        "header_format": "attr",
        "element": "Si",
        "pseudo_type": "NC",
        "functional": "PBE",
        "relativistic": "scalar",
        "sssp_recommended_cutoff": {"ecutwfc_ry": 40.0, "ecutrho_ry": 160.0},
    }
    body = {
        "structure": {"content": _si_cif(), "format": "cif"},
        "hints": {"k_grid": [3, 3, 3]},
        "pseudo_metadata": [override],
    }

    with TestClient(app) as client:
        response = client.post("/recommend", json=body)

    assert response.status_code == 200
    selection = response.json()["selection"]["pseudopotentials"]
    assert any(p["filename"] == "Si.override.UPF" for p in selection)
    assert not any(p["filename"] == "Si.pbe-n-nc.UPF" for p in selection)


# --- Reviewer probe regressions (issue #44) ------------------------------------


def test_concurrent_requests_do_not_serialize_on_event_loop() -> None:
    """Blocking parse+run is offloaded so two concurrent requests overlap, not queue."""
    import asyncio
    import time

    import httpx
    from httpx import ASGITransport

    from goldilocks_core.server.http import create_app

    def slow_kmesh(
        structure,
        hints,
        advice: KPointAdvice,  # noqa: ANN001
    ) -> KPointSelection:
        time.sleep(0.2)
        return KPointSelection(
            grid=hints.k_grid or (1, 1, 1),
            shift=(0, 0, 0),
            mesh_type=advice.mesh_type,
            provenance=Provenance(source="user_hint", reason="test"),
        )

    runtime = CoreRuntime(pipeline=Pipeline(kmesh=slow_kmesh))
    app = create_app(runtime=runtime, bundle_root=Path("/tmp/bundles"))
    # ASGITransport does not run the lifespan, so initialize app state directly.
    app_state = app.state.goldilocks
    app_state.runtime = runtime
    app_state.default_pseudo_metadata = ()

    async def main() -> tuple[float, list[httpx.Response]]:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            start = time.perf_counter()
            responses = await asyncio.gather(
                client.post("/recommend", json=_recommend_body()),
                client.post("/recommend", json=_recommend_body()),
            )
        return time.perf_counter() - start, list(responses)

    elapsed, responses = asyncio.run(main())

    assert all(response.status_code == 200 for response in responses)
    # Two 0.2s blocking runs overlap off the event loop, finishing well under
    # the ~0.4s a serialized event-loop execution would take.
    assert elapsed < 0.38


def test_app_owned_runtime_is_closed_on_startup_pseudo_load_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A startup pseudo-load failure still closes the app-owned runtime."""
    from fastapi.testclient import TestClient

    import goldilocks_core.server.http as server_http
    from goldilocks_core.server.http import create_app

    def boom(root: object) -> object:
        raise RuntimeError("pseudo load boom")

    monkeypatch.setattr(server_http, "load_pseudo_metadata", boom)
    pseudo_root = tmp_path / "pseudos"
    pseudo_root.mkdir()
    app = create_app(pseudo_root=pseudo_root, bundle_root=tmp_path / "bundles")

    with pytest.raises(RuntimeError, match="pseudo load boom"):
        with TestClient(app):
            pass

    assert app.state.goldilocks.runtime is not None
    assert app.state.goldilocks.runtime.is_closed


def test_serve_owns_and_closes_runtime_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """serve() builds an app-owned runtime that closes on shutdown."""
    import uvicorn
    from fastapi.testclient import TestClient

    from goldilocks_core.server.http import serve

    captured: dict[str, object] = {}

    def fake_run(app: object, *, host: str, port: int) -> None:
        captured["app"] = app

    monkeypatch.setattr(uvicorn, "run", fake_run)
    serve(host="127.0.0.1", port=8043, heuristic_kpoints=True)

    app = captured["app"]
    app_state = app.state.goldilocks
    with TestClient(app) as client:
        runtime = app_state.runtime
        assert runtime is not None
        assert not runtime.is_closed
        assert client.get("/health").status_code == 200

    assert runtime.is_closed
