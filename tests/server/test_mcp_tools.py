from __future__ import annotations

import asyncio
import time

import pytest

pytest.importorskip("mcp")
ToolError = pytest.importorskip("mcp.server.mcpserver.exceptions").ToolError
create_server = pytest.importorskip("goldilocks_core.server.mcp").create_server


def _call(server, name: str, arguments: dict) -> dict:
    """Call an MCP tool through the in-process harness."""

    async def call() -> dict:
        result = await server.call_tool(name, arguments)
        assert not result.is_error
        assert result.structured_content is not None
        return result.structured_content

    return asyncio.run(call())


def test_mcp_lists_six_tools_with_constrained_outputs(test_service) -> None:
    """Publish the three transport tools plus three discovery tools."""
    server = create_server(test_service)
    tools = asyncio.run(server.list_tools())

    assert {tool.name for tool in tools} == {
        "recommend",
        "generate",
        "compute",
        "list_tasks",
        "list_codes",
        "list_models",
    }
    compute = next(tool for tool in tools if tool.name == "compute")
    output_names = compute.input_schema["properties"]["outputs"]["items"]["enum"]
    assert "analysis" in output_names
    assert "advice" in output_names
    assert compute.input_schema["$defs"]["_Hints"]["additionalProperties"] is False
    assert compute.input_schema["additionalProperties"] is False


@pytest.mark.parametrize(
    "removed", ["kmesh_model", "pseudo_metadata", "pseudo_root", "output_dir"]
)
def test_mcp_tool_schemas_exclude_deployment_configuration(
    test_service, removed: str
) -> None:
    """Tool schemas never expose deployment configuration to clients."""
    server = create_server(test_service)
    tools = asyncio.run(server.list_tools())

    for tool in tools:
        assert removed not in tool.input_schema.get("properties", {})


def test_mcp_recommend_returns_core_result(test_service, request_body) -> None:
    """Return CoreResult JSON from the recommend tool."""
    server = create_server(test_service)

    data = _call(server, "recommend", request_body)

    assert data["analysis"]["reduced_formula"] == "Si"
    assert data["k_points"]["grid"] == [3, 3, 3]
    assert data["generated_files"] == []


def test_mcp_rejects_unknown_root_arguments(test_service, request_body) -> None:
    """Reject fields outside the published root tool schema."""
    server = create_server(test_service)

    with pytest.raises(ToolError, match="Unknown recommend arguments: surprise"):
        asyncio.run(
            server.call_tool(
                "recommend",
                {**request_body, "surprise": True},
            )
        )


def test_mcp_rejects_type_coercion_in_hints(test_service, request_body) -> None:
    """Reject string-to-bool and string-to-int coercion instead of converting."""
    server = create_server(test_service)

    with pytest.raises(ToolError):
        asyncio.run(
            server.call_tool(
                "recommend",
                {**request_body, "hints": {"spin_polarized": "yes"}},
            )
        )
    with pytest.raises(ToolError):
        asyncio.run(
            server.call_tool(
                "recommend",
                {**request_body, "hints": {"k_grid": ["3", "3", "3"]}},
            )
        )


class _SlowPresetService:
    """Service stub whose preset runs are long enough to outlast a tick."""

    def __init__(self, delay: float) -> None:
        self._delay = delay

    def run_preset(self, request):
        time.sleep(self._delay)

        class _Result:
            def to_dict(self) -> dict:
                return {}

        return _Result()


def test_mcp_list_tools_stays_responsive_during_slow_compute(
    sample_structure_text: str,
) -> None:
    """Answer discovery while a recommendation runs in a worker thread."""
    server = create_server(_SlowPresetService(delay=0.8))
    body = {"structure": sample_structure_text}

    async def scenario() -> float:
        pending = asyncio.create_task(server.call_tool("recommend", body))
        await asyncio.sleep(0.1)
        started = time.perf_counter()
        await server.list_tools()
        elapsed = time.perf_counter() - started
        await pending
        return elapsed

    elapsed = asyncio.run(scenario())
    assert elapsed < 0.5


def test_mcp_generate_without_server_pseudopotentials_raises_tool_error(
    test_service, request_body
) -> None:
    """Surface the generate rejection as a ToolError for the agent."""
    server = create_server(test_service)

    with pytest.raises(ToolError, match="Pseudopotential selection"):
        _call(server, "generate", request_body)


def test_mcp_rejects_deployment_configuration_arguments(
    test_service, request_body
) -> None:
    """Reject client-supplied model and filesystem configuration."""
    server = create_server(test_service)

    with pytest.raises(ToolError, match="Unknown recommend arguments: kmesh_model"):
        _call(
            server,
            "recommend",
            {
                **request_body,
                "kmesh_model": {
                    "name": "m",
                    "version": "1",
                    "model_type": "random_forest",
                    "target": "k_index",
                    "feature_set": "cslr",
                    "source": "local",
                    "location": "/tmp/model.pkl",
                },
            },
        )


def test_mcp_compute_returns_requested_records(test_service, request_body) -> None:
    """Return only records named by the compute outputs argument."""
    server = create_server(test_service)

    data = _call(
        server,
        "compute",
        {
            **request_body,
            "outputs": ["analysis", "advice"],
        },
    )

    assert set(data) == {"analysis", "advice"}
    assert data["analysis"]["reduced_formula"] == "Si"
