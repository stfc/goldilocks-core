from __future__ import annotations

import asyncio
import json

import pytest


def _pipeline_args(si_cif_path, si_pseudo_metadata: dict) -> dict:
    """Return call_tool arguments for a pipeline tool (nested under 'args')."""
    return {
        "args": {
            "structure": {"path": str(si_cif_path)},
            "hints": {"k_grid": [3, 3, 3]},
            "pseudo_metadata": [si_pseudo_metadata],
        }
    }


def _stage_args(si_cif_path) -> dict:
    """Return call_tool arguments for a raw stage tool."""
    return {
        "args": {
            "structure": {"path": str(si_cif_path)},
            "hints": {"k_grid": [3, 3, 3]},
        }
    }


async def _call_tool(server, name: str, arguments: dict) -> dict:
    """Call a tool and parse the JSON text content into a dict."""

    result = await server.call_tool(name, arguments)
    assert not result.is_error, f"tool {name} returned error: {result.content}"
    return json.loads(result.content[0].text)


def test_mcp_lists_six_core_tools(mcp_server) -> None:
    """The server publishes all six Core entrypoint tools."""

    tools = asyncio.run(mcp_server.list_tools())
    names = {tool.name for tool in tools}
    assert names == {"recommend", "generate", "analyze", "kmesh", "advise", "select"}


def test_mcp_tool_schemas_have_constrained_structure(mcp_server) -> None:
    """Tool input schemas include additionalProperties: false (extra='forbid')."""

    tools = asyncio.run(mcp_server.list_tools())
    schema_by_name = {tool.name: tool.input_schema for tool in tools}

    # The root argument model forbids extra properties.
    recommend_schema = schema_by_name["recommend"]
    defs = recommend_schema.get("$defs", {})
    pipeline_def = defs.get("_PipelineArgs", {})
    assert pipeline_def.get("additionalProperties") is False

    # The structure sub-schema forbids extra properties too.
    structure_def = defs.get("_StructureArg", {})
    assert structure_def.get("additionalProperties") is False


def test_mcp_recommend_returns_core_result(
    mcp_server, si_cif_path, si_pseudo_metadata: dict
) -> None:
    """The recommend tool returns a CoreResult JSON."""

    data = asyncio.run(
        _call_tool(
            mcp_server, "recommend", _pipeline_args(si_cif_path, si_pseudo_metadata)
        )
    )

    assert set(data) == {
        "intent",
        "analysis",
        "advice",
        "k_points",
        "selection",
        "generated_files",
        "warnings",
        "bundle",
    }
    assert data["k_points"]["grid"] == [3, 3, 3]
    assert data["analysis"]["reduced_formula"] == "Si"
    assert data["generated_files"] == []


def test_mcp_generate_returns_generated_files(
    mcp_server, si_cif_path, si_pseudo_metadata: dict, tmp_path
) -> None:
    """The generate tool returns generated input files and a bundle."""

    args = _pipeline_args(si_cif_path, si_pseudo_metadata)
    args["args"]["output_dir"] = str(tmp_path / "bundle")

    data = asyncio.run(_call_tool(mcp_server, "generate", args))

    assert [f["path"] for f in data["generated_files"]] == ["inputs/qe.in"]
    assert data["bundle"] is not None
    assert (tmp_path / "bundle" / "inputs" / "qe.in").exists()


def test_mcp_analyze_returns_analysis_record(mcp_server, si_cif_path) -> None:
    """The analyze tool returns the StructureAnalysisRecord JSON."""

    data = asyncio.run(_call_tool(mcp_server, "analyze", _stage_args(si_cif_path)))

    assert data["reduced_formula"] == "Si"
    assert "Si" in data["elements"]


def test_mcp_kmesh_returns_kpoint_selection(mcp_server, si_cif_path) -> None:
    """The kmesh tool returns the KPointSelection JSON."""

    data = asyncio.run(_call_tool(mcp_server, "kmesh", _stage_args(si_cif_path)))

    assert data["grid"] == [3, 3, 3]
    assert data["provenance"]["source"] == "user_hint"


def test_mcp_advise_returns_parameter_advice(
    mcp_server, si_cif_path, si_pseudo_metadata: dict
) -> None:
    """The advise tool returns the ParameterAdvice JSON."""

    data = asyncio.run(
        _call_tool(
            mcp_server, "advise", _pipeline_args(si_cif_path, si_pseudo_metadata)
        )
    )

    assert "smearing" in data
    assert "pseudopotentials" in data


def test_mcp_select_returns_selection_record(
    mcp_server, si_cif_path, si_pseudo_metadata: dict
) -> None:
    """The select tool returns the SelectionRecord JSON."""

    data = asyncio.run(
        _call_tool(
            mcp_server, "select", _pipeline_args(si_cif_path, si_pseudo_metadata)
        )
    )

    assert data["pseudopotentials"][0]["element"] == "Si"


def test_mcp_rejects_unknown_argument(mcp_server, si_cif_path) -> None:
    """An unknown argument field is rejected by the schema (extra='forbid')."""

    from mcp.server.mcpserver.exceptions import ToolError

    args = {
        "args": {
            "structure": {"path": str(si_cif_path)},
            "bogus_field": 1,
        }
    }
    with pytest.raises(ToolError, match="Extra inputs are not permitted"):
        asyncio.run(mcp_server.call_tool("recommend", args))


def test_mcp_rejects_bad_argument_type(mcp_server, si_cif_path) -> None:
    """A wrong-typed argument is rejected by the schema."""

    from mcp.server.mcpserver.exceptions import ToolError

    args = {
        "args": {
            "structure": {"path": str(si_cif_path)},
            "hints": {"k_grid": [1, 2, "not_an_int"]},
        }
    }
    with pytest.raises(ToolError, match="integer"):
        asyncio.run(mcp_server.call_tool("recommend", args))


def test_mcp_stage_error_surfaces_as_tool_error(
    mcp_server,
) -> None:
    """A stage ValueError (missing structure file) surfaces as a ToolError."""

    from mcp.server.mcpserver.exceptions import ToolError

    args = {"args": {"structure": {"path": "/nonexistent/structure.cif"}}}
    with pytest.raises(ToolError):
        asyncio.run(mcp_server.call_tool("recommend", args))
