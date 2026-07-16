from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# Tool input schemas are derived from the Core contract ``Literal`` aliases and
# field sets. These tests guard against schema drift from ``CoreJobRequest`` /
# ``CalculationHints`` / ``PseudoMetadata`` so agents get constrained inputs.


def _tool_schemas(server: object) -> dict[str, dict]:
    """Return {tool_name: inputSchema} for a server via one in-process session."""
    import anyio
    from mcp.shared.memory import create_connected_server_and_client_session

    async def _run() -> dict[str, dict]:
        async with create_connected_server_and_client_session(server) as session:
            await session.initialize()
            tools = await session.list_tools()
            return {tool.name: tool.inputSchema for tool in tools.tools}

    return anyio.run(_run)


def _make_server() -> object:
    """Return an MCP server with a heuristic runtime (no model load for schemas)."""
    from pathlib import Path

    from goldilocks_core.jobs import CoreRuntime, Pipeline
    from goldilocks_core.kmesh import resolve_kpoints_from_advice
    from goldilocks_core.server.mcp import create_server

    return create_server(
        runtime=CoreRuntime(pipeline=Pipeline(kmesh=resolve_kpoints_from_advice)),
        bundle_root=Path("/tmp/mcp-bundles"),
    )


def _defs(tool_schema: dict) -> dict[str, dict]:
    """Return the ``$defs`` model definitions for a tool input schema."""
    return tool_schema["$defs"]


def test_intent_schema_constrains_code_and_task_enums() -> None:
    """intent.code and intent.task are enums sourced from the contract Literals."""
    schemas = _tool_schemas(_make_server())
    intent_def = _defs(schemas["recommend"])["IntentArg"]

    code = intent_def["properties"]["code"]
    task = intent_def["properties"]["task"]
    # Pydantic renders a single-value Literal as ``const`` and a multi-value one
    # as ``enum``; both constrain the agent's input to the contract Literal.
    assert code.get("const") == "quantum_espresso" or code.get("enum") == [
        "quantum_espresso"
    ]
    assert code.get("default") == "quantum_espresso"
    assert task.get("const") == "scf_single_point" or task.get("enum") == [
        "scf_single_point"
    ]
    assert task.get("default") == "scf_single_point"


def test_hints_schema_constrains_vdw_method_enum_and_k_grid_shape() -> None:
    """hints.vdw_method is an enum and hints.k_grid is a 3-integer array."""
    schemas = _tool_schemas(_make_server())
    hints_def = _defs(schemas["recommend"])["HintsArg"]

    vdw = hints_def["properties"]["vdw_method"]
    # Optional enum: anyOf [enum-string, null].
    if "anyOf" in vdw:
        enum_branch = next(branch for branch in vdw["anyOf"] if "enum" in branch)
        assert enum_branch["enum"] == ["d3", "d3bj", "ts", "mbd"]
    else:
        assert vdw.get("enum") == ["d3", "d3bj", "ts", "mbd"]

    k_grid = hints_def["properties"]["k_grid"]
    if "anyOf" in k_grid:
        array_branch = next(
            branch for branch in k_grid["anyOf"] if branch.get("type") == "array"
        )
    else:
        array_branch = k_grid
    assert array_branch["type"] == "array"
    assert array_branch["minItems"] == 3
    assert array_branch["maxItems"] == 3
    assert len(array_branch["prefixItems"]) == 3
    assert all(item["type"] == "integer" for item in array_branch["prefixItems"])


def test_hints_schema_has_no_accuracy_level() -> None:
    """hints has no accuracy_level field (it was removed from the contracts)."""
    schemas = _tool_schemas(_make_server())
    hints_def = _defs(schemas["recommend"])["HintsArg"]
    assert "accuracy_level" not in hints_def["properties"]


def test_hints_schema_mirrors_calculation_hints_field_set() -> None:
    """hints exposes the CalculationHints field names (drift guard)."""
    schemas = _tool_schemas(_make_server())
    hints_def = _defs(schemas["recommend"])["HintsArg"]
    from dataclasses import fields

    from goldilocks_core.contracts import CalculationHints

    expected = {field.name for field in fields(CalculationHints)}
    assert set(hints_def["properties"]) == expected


def test_bundle_schema_requires_output_dir_and_structure() -> None:
    """bundle requires structure and output_dir; output_dir is a string."""
    schemas = _tool_schemas(_make_server())
    bundle = schemas["bundle"]
    assert bundle["required"] == ["structure", "output_dir"]
    output_dir = bundle["properties"]["output_dir"]
    assert output_dir["type"] == "string"


def test_analyze_schema_has_only_structure() -> None:
    """analyze accepts only a structure argument."""
    schemas = _tool_schemas(_make_server())
    analyze = schemas["analyze"]
    assert list(analyze["properties"]) == ["structure"]
    assert analyze["required"] == ["structure"]


def test_pseudo_metadata_schema_mirrors_pseudo_fields() -> None:
    """pseudo_metadata items expose the PseudoMetadata.from_dict field set."""
    schemas = _tool_schemas(_make_server())
    pseudo_def = _defs(schemas["recommend"])["PseudoMetadataArg"]
    from dataclasses import fields

    from goldilocks_core.pseudo.pp_metadata import PseudoMetadata

    fields_names = set(pseudo_def["properties"])
    expected = {field.name for field in fields(PseudoMetadata)}
    assert fields_names == expected
    assert pseudo_def["required"] == ["filepath", "filename", "header_format"]
    assert "is_sssp" in fields_names
    assert "sssp_recommended_cutoff" in fields_names


def test_pseudo_free_form_maps_are_the_two_open_object_exceptions() -> None:
    """``pseudo_info`` and ``sssp_recommended_cutoff`` are intentionally open.

    The Core ``PseudoMetadata`` contract models these two as ``dict[str, Any]``
    (raw UPF header metadata and raw SSSP cutoff maps whose keys are not part of
    the Core contract), so their published schemas are open objects
    (``additionalProperties: true``) rather than closed. Every *other* nested
    schema model — including ``PseudoMetadataArg`` itself — is closed
    (``additionalProperties: false``). These two maps are still validated at
    runtime: ``PseudoMetadata.from_dict`` requires them to be JSON objects and
    rejects unknown *typed* ``PseudoMetadata`` keys; only their free-form
    *contents* are accepted by contract design.
    """
    schemas = _tool_schemas(_make_server())
    defs = _defs(schemas["recommend"])
    pseudo_def = defs["PseudoMetadataArg"]

    # The two intentional free-form metadata-map exceptions publish open objects.
    pseudo_info = pseudo_def["properties"]["pseudo_info"]
    assert pseudo_info["type"] == "object"
    assert pseudo_info["additionalProperties"] is True

    sssp = pseudo_def["properties"]["sssp_recommended_cutoff"]
    sssp_object_branch = next(
        branch for branch in sssp["anyOf"] if branch.get("type") == "object"
    )
    assert sssp_object_branch["additionalProperties"] is True

    # Every named nested model is closed, including PseudoMetadataArg itself;
    # only the two free-form map *fields* above are open.
    for name in ("StructureArg", "IntentArg", "HintsArg", "PseudoMetadataArg"):
        assert defs[name]["additionalProperties"] is False, name


def test_structure_schema_constrains_format_enum() -> None:
    """structure.format is a cif/poscar enum; content and path are optional strings."""
    schemas = _tool_schemas(_make_server())
    struct_def = _defs(schemas["recommend"])["StructureArg"]

    fmt = struct_def["properties"]["format"]
    if "anyOf" in fmt:
        enum_branch = next(b for b in fmt["anyOf"] if "enum" in b)
        assert enum_branch["enum"] == ["cif", "poscar"]
    else:
        assert fmt.get("enum") == ["cif", "poscar"]

    # content and path are Optional strings (anyOf [string, null]).
    content = struct_def["properties"]["content"]
    content_branch = next(b for b in content["anyOf"] if b.get("type") == "string")
    assert content_branch["type"] == "string"
    path = struct_def["properties"]["path"]
    path_branch = next(b for b in path["anyOf"] if b.get("type") == "string")
    assert path_branch["type"] == "string"
    # additionalProperties is false so unknown structure sub-keys are rejected.
    assert struct_def.get("additionalProperties") is False


def test_intent_schema_mirrors_calculation_intent_field_set() -> None:
    """intent exposes the CalculationIntent field names (drift guard)."""
    schemas = _tool_schemas(_make_server())
    intent_def = _defs(schemas["recommend"])["IntentArg"]
    from dataclasses import fields

    from goldilocks_core.contracts import CalculationIntent

    assert set(intent_def["properties"]) == {
        field.name for field in fields(CalculationIntent)
    }


def test_schemas_serialize_to_json() -> None:
    """All tool input schemas are JSON-serializable (no non-JSON-safe values)."""
    schemas = _tool_schemas(_make_server())
    for name, schema in schemas.items():
        json.dumps(schema)  # raises if not JSON-serializable
        assert schema["type"] == "object", name


def test_schemas_have_no_mode_or_accuracy_level_keys() -> None:
    """No model definition or top-level property is named 'mode' or 'accuracy_level'."""
    schemas = _tool_schemas(_make_server())
    for name, schema in schemas.items():
        for prop in schema["properties"]:
            assert prop != "mode"
            assert prop != "accuracy_level"
        for def_name, def_schema in schema.get("$defs", {}).items():
            for prop in def_schema.get("properties", {}):
                assert prop != "mode", f"{name}.$defs.{def_name}.{prop}"
                assert prop != "accuracy_level", f"{name}.$defs.{def_name}.{prop}"
