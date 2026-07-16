from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.contracts import KPointAdvice, KPointSelection, Provenance
from goldilocks_core.jobs import CoreRuntime, Pipeline

if TYPE_CHECKING:
    pass

# Runtime lifetime tests over the in-process MCP memory transport. No real
# model is loaded (explicit k-grid hint + heuristic-kpoints / tracking kmesh)
# and no network is involved.


def _si_cif() -> str:
    """Return CIF text for a small Si structure."""
    return Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]]).to(fmt="cif")


def _tracking_kmesh(calls: dict[str, int]):
    """Return a k-mesh backend that counts invocations."""

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


def _recommend_args() -> dict:
    """Return recommend tool arguments with an explicit k-grid hint."""
    return {
        "structure": {"content": _si_cif(), "format": "cif"},
        "hints": {"k_grid": [3, 3, 3]},
    }


def _run(server: object, body) -> object:
    """Run an async body against one in-process session (one lifespan)."""
    import anyio
    from mcp.shared.memory import create_connected_server_and_client_session

    async def _run_async() -> object:
        async with create_connected_server_and_client_session(server) as session:
            await session.initialize()
            return await body(session)

    return anyio.run(_run_async)


# --- reuse ------------------------------------------------------------------


def test_two_calls_share_one_runtime_and_one_kmesh_backend() -> None:
    """One server-owned runtime serves repeated calls without rebuilding backends."""
    from goldilocks_core.server.mcp import create_server

    calls: dict[str, int] = {"count": 0}
    runtime = CoreRuntime(pipeline=Pipeline(kmesh=_tracking_kmesh(calls)))
    server = create_server(runtime=runtime, bundle_root=Path("/tmp/mcp-bundles"))

    async def body(session) -> tuple[object, object]:
        first = await session.call_tool("recommend", _recommend_args())
        second = await session.call_tool("recommend", _recommend_args())
        return first, second

    first, second = _run(server, body)

    assert first.isError is False
    assert second.isError is False
    # One shared kmesh object served both calls.
    assert calls["count"] == 2


def test_app_owned_runtime_is_built_once_and_closed_on_shutdown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The app-owned runtime is built once and closed when the session ends."""
    import goldilocks_core.server.mcp as server_mcp
    from goldilocks_core.server.mcp import create_server

    builds = {"count": 0}
    runtime = CoreRuntime(pipeline=Pipeline(kmesh=_tracking_kmesh({"count": 0})))

    def fake_build(**kwargs: object) -> CoreRuntime:
        builds["count"] += 1
        return runtime

    monkeypatch.setattr(server_mcp, "_build_runtime", fake_build)
    server = create_server(heuristic_kpoints=True, bundle_root=tmp_path / "bundles")

    async def body(session) -> object:
        # Two calls share the one lifespan-built runtime.
        await session.call_tool("recommend", _recommend_args())
        await session.call_tool("recommend", _recommend_args())
        return None

    _run(server, body)

    assert builds["count"] == 1
    assert runtime.is_closed


def test_app_owned_runtime_is_closed_even_without_tool_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Startup then immediate shutdown still closes the app-owned runtime."""
    import goldilocks_core.server.mcp as server_mcp
    from goldilocks_core.server.mcp import create_server

    runtime = CoreRuntime(pipeline=Pipeline(kmesh=_tracking_kmesh({"count": 0})))
    monkeypatch.setattr(server_mcp, "_build_runtime", lambda **kw: runtime)
    server = create_server(heuristic_kpoints=True, bundle_root=tmp_path / "bundles")

    async def body(session) -> object:
        return None

    _run(server, body)

    assert runtime.is_closed


def test_app_owned_runtime_is_closed_on_startup_pseudo_load_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A startup pseudo-load failure still closes the app-owned runtime."""
    import goldilocks_core.server.mcp as server_mcp
    from goldilocks_core.server.mcp import create_server

    runtime = CoreRuntime(pipeline=Pipeline(kmesh=_tracking_kmesh({"count": 0})))
    monkeypatch.setattr(server_mcp, "_build_runtime", lambda **kw: runtime)

    def boom(root: object) -> object:
        raise RuntimeError("pseudo load boom")

    monkeypatch.setattr(server_mcp, "load_pseudo_metadata", boom)
    pseudo_root = tmp_path / "pseudos"
    pseudo_root.mkdir()
    server = create_server(
        pseudo_root=pseudo_root,
        heuristic_kpoints=True,
        bundle_root=tmp_path / "bundles",
    )

    async def body(session) -> object:
        return None

    with pytest.raises(BaseException):
        _run(server, body)

    assert runtime.is_closed


def test_provided_runtime_is_not_closed_by_server(tmp_path: Path) -> None:
    """A caller-provided runtime stays open after shutdown for the caller to manage."""
    from goldilocks_core.server.mcp import create_server

    runtime = CoreRuntime(pipeline=Pipeline(kmesh=_tracking_kmesh({"count": 0})))
    server = create_server(runtime=runtime, bundle_root=tmp_path / "bundles")

    async def body(session) -> object:
        return await session.call_tool("recommend", _recommend_args())

    result = _run(server, body)
    assert result.isError is False
    assert not runtime.is_closed
    runtime.close()
    assert runtime.is_closed


# --- analyze does not invoke kmesh ------------------------------------------


def test_analyze_does_not_invoke_kmesh() -> None:
    """analyze runs only the Analyze stage and never calls the kmesh backend."""
    from goldilocks_core.server.mcp import create_server

    calls = {"count": 0}
    runtime = CoreRuntime(pipeline=Pipeline(kmesh=_tracking_kmesh(calls)))
    server = create_server(runtime=runtime, bundle_root=Path("/tmp/mcp-bundles"))

    async def body(session) -> tuple[object, object]:
        analyze = await session.call_tool(
            "analyze", {"structure": {"content": _si_cif(), "format": "cif"}}
        )
        recommend = await session.call_tool("recommend", _recommend_args())
        return analyze, recommend

    analyze, recommend = _run(server, body)
    # analyze did not touch kmesh; recommend did.
    assert calls["count"] == 1
    assert analyze.isError is False
    assert recommend.isError is False


# --- configured default pseudo metadata -------------------------------------


def test_default_pseudo_metadata_is_loaded_once_at_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Configured pseudo metadata loads at startup and is reused for every call."""
    import goldilocks_core.server.mcp as server_mcp
    from goldilocks_core.server.mcp import create_server

    pseudo_root = tmp_path / "pseudos" / "pslibrary"
    pseudo_root.mkdir(parents=True)
    (pseudo_root / "Si.pbe-n-nc.UPF").write_text(
        _make_upf(element="Si", pseudo_type="NC", functional="PBE")
    )

    loads = {"count": 0}
    original = server_mcp.load_pseudo_metadata

    def counting_loader(root: object) -> object:
        loads["count"] += 1
        return original(root)

    monkeypatch.setattr(server_mcp, "load_pseudo_metadata", counting_loader)
    server = create_server(pseudo_root=pseudo_root, bundle_root=tmp_path / "bundles")

    async def body(session) -> tuple[object, object]:
        first = await session.call_tool("recommend", _recommend_args())
        second = await session.call_tool("recommend", _recommend_args())
        return first, second

    first, second = _run(server, body)
    assert first.isError is False
    assert second.isError is False
    assert loads["count"] == 1
    for response in (first, second):
        import json

        selection = json.loads(response.content[0].text)["selection"][
            "pseudopotentials"
        ]
        assert any(p["filename"] == "Si.pbe-n-nc.UPF" for p in selection)


def test_request_pseudo_metadata_overrides_configured_default(tmp_path: Path) -> None:
    """Per-call pseudo_metadata overrides the configured default."""
    from goldilocks_core.server.mcp import create_server

    pseudo_root = tmp_path / "pseudos" / "pslibrary"
    pseudo_root.mkdir(parents=True)
    (pseudo_root / "Si.pbe-n-nc.UPF").write_text(
        _make_upf(element="Si", pseudo_type="NC", functional="PBE")
    )

    server = create_server(pseudo_root=pseudo_root, bundle_root=tmp_path / "bundles")
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
    args = {
        "structure": {"content": _si_cif(), "format": "cif"},
        "hints": {"k_grid": [3, 3, 3]},
        "pseudo_metadata": [override],
    }

    async def body(session) -> object:
        return await session.call_tool("recommend", args)

    response = _run(server, body)
    assert response.isError is False
    import json

    selection = json.loads(response.content[0].text)["selection"]["pseudopotentials"]
    assert any(p["filename"] == "Si.override.UPF" for p in selection)
    assert not any(p["filename"] == "Si.pbe-n-nc.UPF" for p in selection)


# --- serve() CLI entry owns/closes runtime ----------------------------------


def test_serve_owns_and_closes_runtime_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """serve() builds a server whose app-owned runtime closes on shutdown.

    ``serve()`` runs the public ``_serve_stdio`` entry; replacing it with an
    async no-op capture lets the test drive an in-process session against the
    built server without touching stdin/stdout.
    """
    import goldilocks_core.server.mcp as server_mcp
    from goldilocks_core.server.mcp import serve

    captured: dict[str, object] = {}

    async def fake_serve_stdio(server: object) -> None:
        captured["server"] = server

    monkeypatch.setattr(server_mcp, "_serve_stdio", fake_serve_stdio)
    serve(heuristic_kpoints=True)

    server = captured["server"]
    # Drive one in-process session so the lifespan builds and closes the runtime.
    runtime_marker = CoreRuntime(pipeline=Pipeline(kmesh=_tracking_kmesh({"count": 0})))
    builds = {"count": 0}

    def fake_build(**kwargs: object) -> CoreRuntime:
        builds["count"] += 1
        return runtime_marker

    monkeypatch.setattr(server_mcp, "_build_runtime", fake_build)

    async def body(session) -> object:
        return await session.call_tool("recommend", _recommend_args())

    _run(server, body)
    assert builds["count"] == 1
    assert runtime_marker.is_closed
