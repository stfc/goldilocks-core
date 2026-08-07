from __future__ import annotations

import asyncio

import pytest


def test_mcp_reuses_one_core_runtime_across_two_tool_calls(
    si_cif_path,
    si_pseudo_metadata: dict,
) -> None:
    """The same CoreRuntime instance serves two tool calls (model loaded once)."""
    pytest.importorskip("mcp")
    from goldilocks_core.runtime import CoreRuntime
    from goldilocks_core.server.mcp import create_server

    runtime = CoreRuntime()
    server = create_server(runtime=runtime)

    args = {
        "args": {
            "structure": {"path": str(si_cif_path)},
            "hints": {"k_grid": [3, 3, 3]},
            "pseudo_metadata": [si_pseudo_metadata],
        }
    }

    async def main() -> None:
        await server.call_tool("recommend", args)
        await server.call_tool("recommend", args)

    asyncio.run(main())

    # The provided runtime was reused, not closed by the server.
    assert not runtime.is_closed
    runtime.close()


def test_mcp_does_not_close_caller_provided_runtime(
    si_cif_path,
    si_pseudo_metadata: dict,
) -> None:
    """A caller-provided runtime is left open after tool calls."""
    pytest.importorskip("mcp")
    from goldilocks_core.runtime import CoreRuntime
    from goldilocks_core.server.mcp import create_server

    runtime = CoreRuntime()
    server = create_server(runtime=runtime)

    args = {
        "args": {
            "structure": {"path": str(si_cif_path)},
            "hints": {"k_grid": [3, 3, 3]},
            "pseudo_metadata": [si_pseudo_metadata],
        }
    }

    asyncio.run(server.call_tool("recommend", args))

    assert not runtime.is_closed
    runtime.close()


def test_mcp_has_no_module_global_runtime() -> None:
    """No CoreRuntime instance lingers as a module global in server.mcp."""
    pytest.importorskip("mcp")
    from goldilocks_core.runtime import CoreRuntime
    from goldilocks_core.server import mcp as mcp_module

    assert not any(
        isinstance(value, CoreRuntime) for value in vars(mcp_module).values()
    )
