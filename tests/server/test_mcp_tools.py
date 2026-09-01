from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytest.importorskip("mcp")
ToolError = pytest.importorskip("mcp.server.mcpserver.exceptions").ToolError
create_server = pytest.importorskip("goldilocks_core.server.mcp").create_server


def _call(server, name: str, arguments: dict) -> dict:
    async def call() -> dict:
        result = await server.call_tool(name, arguments)
        assert not result.is_error
        assert result.structured_content is not None
        return result.structured_content

    return asyncio.run(call())


def test_mcp_exposes_exactly_three_scientific_tools(test_service) -> None:
    tools = asyncio.run(create_server(test_service).list_tools())

    assert {tool.name for tool in tools} == {
        "capabilities",
        "inspect_structure",
        "compute",
    }
    assert all(tool.input_schema["additionalProperties"] is False for tool in tools)
    compute = next(tool for tool in tools if tool.name == "compute")
    draft = compute.input_schema["$defs"]["CalculationDraft"]
    assert draft["additionalProperties"] is False
    assert set(draft["properties"]) == {
        "structure",
        "intent",
        "hints",
        "pseudo_table",
    }
    assert "DirectoryOutput" not in compute.input_schema["$defs"]
    assert "ArchiveOutput" not in compute.input_schema["$defs"]
    assert compute.input_schema["$defs"]["RecordSelection"]["properties"]["records"][
        "items"
    ] == {"type": "string"}


def test_mcp_capabilities_and_inspection_return_core_contracts(
    test_service,
    sample_structure_path: str,
    sample_structure_text: str,
) -> None:
    server = create_server(test_service)

    capabilities = _call(server, "capabilities", {})
    inline = _call(
        server,
        "inspect_structure",
        {
            "source": {
                "name": "uploaded.cif",
                "content": sample_structure_text,
                "format": "cif",
            }
        },
    )

    assert capabilities["tasks"][0]["id"] == "scf_single_point"
    assert inline["source"]["name"] == "uploaded.cif"
    with pytest.raises(ToolError, match="Transports do not accept file paths"):
        asyncio.run(
            server.call_tool("inspect_structure", {"source": sample_structure_path})
        )


def test_mcp_compute_memory_returns_canonical_result(
    test_service,
    sample_structure_text: str,
) -> None:
    result = _call(
        create_server(test_service),
        "compute",
        {
            "draft": {
                "structure": {
                    "name": "Si.cif",
                    "content": sample_structure_text,
                    "format": "cif",
                },
                "hints": {"k_grid": [3, 3, 3]},
            },
            "selection": {"records": ["k_points"]},
            "output": {"kind": "memory"},
        },
    )

    assert result["schema_version"] == 1
    assert result["selection"] == {"records": ["k_points"]}
    assert result["records"]["k_points"]["grid"] == [3, 3, 3]
    assert result["publication"] is None


def test_mcp_selects_custom_records_through_core_registry(
    custom_record_service,
    sample_structure_text: str,
) -> None:
    result = _call(
        create_server(custom_record_service),
        "compute",
        {
            "draft": {
                "structure": {
                    "name": "Si.cif",
                    "content": sample_structure_text,
                    "format": "cif",
                },
                "intent": {"task": "custom_task"},
            },
            "selection": {"records": ["custom_summary"]},
            "output": {"kind": "memory"},
        },
    )

    assert result["selection"] == {"records": ["custom_summary"]}
    assert result["records"] == {"custom_summary": {"value": "custom result"}}


def test_mcp_compute_automatically_publishes_complete_results(
    publishable_service,
    sample_structure_text: str,
    tmp_path,
    monkeypatch,
) -> None:
    import goldilocks_core.publication as publication_module

    class AutomaticRootPath(type(Path())):
        @classmethod
        def cwd(cls):
            return cls(tmp_path)

    monkeypatch.setattr(publication_module, "Path", AutomaticRootPath)
    result = _call(
        create_server(publishable_service),
        "compute",
        {
            "draft": {
                "structure": {
                    "name": "Si.cif",
                    "content": sample_structure_text,
                    "format": "cif",
                },
                "hints": {"k_grid": [3, 3, 3]},
                "pseudo_table": "fixture-table",
            },
            "selection": {"preset": "generate"},
        },
    )

    assert result["draft"]["pseudo_table"] == "fixture-table"
    assert result["draft"]["pseudo_root"] is None
    assert result["draft"]["pseudo_metadata"] is None
    assert result["draft"]["kmesh_model"] is None
    assert result["publication"]["kind"] == "directory"
    assert result["publication"]["path"] == str(tmp_path / "goldilocks_out")
    assert (tmp_path / "goldilocks_out" / "goldilocks.json").is_file()


@pytest.mark.parametrize("kind", ["directory", "archive"])
def test_mcp_rejects_explicit_local_output_paths(
    test_service,
    sample_structure_text: str,
    tmp_path,
    kind: str,
) -> None:
    destination = tmp_path / ("ready.zip" if kind == "archive" else "ready")
    with pytest.raises(ToolError):
        asyncio.run(
            create_server(test_service).call_tool(
                "compute",
                {
                    "draft": {
                        "structure": {
                            "name": "Si.cif",
                            "content": sample_structure_text,
                            "format": "cif",
                        }
                    },
                    "selection": {"records": ["analysis"]},
                    "output": {"kind": kind, "path": str(destination)},
                },
            )
        )
    assert not destination.exists()


def test_mcp_rejects_unknown_and_deployment_configuration(
    test_service, sample_structure_text: str
) -> None:
    server = create_server(test_service)
    inline = {
        "name": "Si.cif",
        "content": sample_structure_text,
        "format": "cif",
    }

    with pytest.raises(ToolError, match="Unknown compute arguments: unexpected"):
        asyncio.run(server.call_tool("compute", {"unexpected": True}))
    with pytest.raises(ToolError, match="Extra inputs are not permitted"):
        asyncio.run(
            server.call_tool(
                "compute",
                {
                    "draft": {"structure": inline},
                    "selection": {"preset": "recommend", "records": ["analysis"]},
                    "output": {"kind": "memory"},
                },
            )
        )
    for field, value in (
        ("pseudo_root", "/server/pseudos"),
        ("pseudo_metadata", []),
        ("kmesh_model", {"location": "/server/model.pkl"}),
    ):
        with pytest.raises(ToolError, match="Extra inputs are not permitted"):
            asyncio.run(
                server.call_tool(
                    "compute",
                    {
                        "draft": {"structure": inline, field: value},
                        "selection": {"records": ["analysis"]},
                        "output": {"kind": "memory"},
                    },
                )
            )
