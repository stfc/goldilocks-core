from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("mcp")
create_server = pytest.importorskip("goldilocks_core.server.mcp").create_server


def _call(server, name: str, arguments: dict) -> dict:
    """Call an MCP tool through the in-process harness."""

    async def call() -> dict:
        result = await server.call_tool(name, arguments)
        assert not result.is_error
        assert result.structured_content is not None
        return result.structured_content

    return asyncio.run(call())


def test_mcp_lists_three_tools_with_constrained_outputs(test_runtime) -> None:
    """Publish only the three transport tools and enumerate query records."""
    server = create_server(test_runtime)
    tools = asyncio.run(server.list_tools())

    assert {tool.name for tool in tools} == {"recommend", "generate", "compute"}
    compute = next(tool for tool in tools if tool.name == "compute")
    output_names = compute.input_schema["properties"]["outputs"]["items"]["enum"]
    assert "StructureAnalysisRecord" in output_names
    assert "ParameterAdvice" in output_names
    assert compute.input_schema["$defs"]["_Hints"]["additionalProperties"] is False


def test_mcp_recommend_returns_core_result(test_runtime, request_body) -> None:
    """Return CoreResult JSON from the recommend tool."""
    server = create_server(test_runtime)

    data = _call(server, "recommend", request_body)

    assert data["analysis"]["reduced_formula"] == "Si"
    assert data["k_points"]["grid"] == [3, 3, 3]
    assert data["generated_files"] == []


def test_mcp_generate_returns_core_result_and_bundle(
    test_runtime, request_body, tmp_path
) -> None:
    """Return generated files and publish a requested bundle."""
    server = create_server(test_runtime)
    output_dir = tmp_path / "bundle"

    data = _call(
        server,
        "generate",
        {**request_body, "output_dir": str(output_dir)},
    )

    assert data["generated_files"][0]["path"] == "inputs/qe.in"
    assert data["bundle"]["path"] == str(output_dir)
    assert (output_dir / "inputs" / "qe.in").is_file()


def test_mcp_compute_returns_requested_records(test_runtime, request_body) -> None:
    """Return only records named by the compute outputs argument."""
    server = create_server(test_runtime)

    data = _call(
        server,
        "compute",
        {
            **request_body,
            "outputs": ["StructureAnalysisRecord", "ParameterAdvice"],
        },
    )

    assert set(data) == {"StructureAnalysisRecord", "ParameterAdvice"}
    assert data["StructureAnalysisRecord"]["reduced_formula"] == "Si"
