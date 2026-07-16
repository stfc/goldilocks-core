from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    pass

# In-process MCP tool tests over the memory transport. No real model is loaded
# (every request uses an explicit k-grid hint and a heuristic-kpoints runtime)
# and no network is involved.


def _text(result: object) -> str:
    """Return the text content of a CallToolResult."""
    return result.content[0].text  # type: ignore[union-attr]


def _parsed(result: object) -> dict:
    """Return the parsed JSON error/success body of a CallToolResult.

    Every client input failure (unknown root key, bad enum, coercion, explicit
    null, missing required field, path confinement, stage, internal) is routed
    through the shared deserializer and returned as the stable MCP ``isError``
    JSON body ``{"error": {"kind": ..., "message": ...}}``. Framework
    pre-validation is bypassed, so no SDK ``Error executing tool ...`` prose
    reaches the client.
    """
    return json.loads(_text(result))


def _si_recommend_args(
    si_cif: str, *, with_pseudo: bool = False, pseudo: dict | None = None
) -> dict:
    """Return recommend-shaped tool arguments with an explicit k-grid hint."""
    args: dict = {
        "structure": {"content": si_cif, "format": "cif"},
        "hints": {"k_grid": [3, 3, 3]},
    }
    if with_pseudo and pseudo is not None:
        args["pseudo_metadata"] = [pseudo]
    return args


# --- tool list and shape ----------------------------------------------------


def test_tools_list_exposes_four_constrained_tools(mcp_server, call_mcp) -> None:
    """The server exposes recommend, generate, bundle, analyze and nothing else."""
    tools = call_mcp(mcp_server, lambda s: s.list_tools())
    names = {tool.name for tool in tools.tools}
    assert names == {"recommend", "generate", "bundle", "analyze"}

    by_name = {tool.name: tool for tool in tools.tools}
    # structure is required on every tool; output_dir is required only on bundle.
    for name in names:
        props = by_name[name].inputSchema["properties"]
        assert "structure" in props
        assert by_name[name].inputSchema["required"][:1] == ["structure"]
    assert "output_dir" in by_name["bundle"].inputSchema["properties"]
    assert by_name["bundle"].inputSchema["required"] == ["structure", "output_dir"]
    assert "output_dir" not in by_name["recommend"].inputSchema["properties"]
    # analyze takes only structure.
    assert list(by_name["analyze"].inputSchema["properties"]) == ["structure"]
    assert by_name["analyze"].inputSchema["required"] == ["structure"]
    # No tool exposes a free JSON-string payload: structure is an object schema
    # (a direct $ref to StructureArg, an anyOf with a $ref, or an inline object).
    for name in names:
        structure_schema = by_name[name].inputSchema["properties"]["structure"]
        assert structure_schema.get("type") != "string"
        assert (
            "$ref" in structure_schema
            or "anyOf" in structure_schema
            or "properties" in structure_schema
        )


def test_schemas_do_not_expose_mode_or_accuracy_level(mcp_server, call_mcp) -> None:
    """No tool schema carries 'mode' (the tool selects it) or 'accuracy_level'."""
    tools = call_mcp(mcp_server, lambda s: s.list_tools())
    for tool in tools.tools:
        schema_str = json.dumps(tool.inputSchema)
        # 'mode' as a JSON property key (not the substring inside 'pseudo_mode').
        assert '"mode":' not in schema_str
        assert "accuracy_level" not in schema_str


# --- recommend --------------------------------------------------------------


def test_recommend_returns_strict_core_result_json(
    mcp_server, call_mcp, si_cif: str
) -> None:
    """recommend returns a CoreResult JSON with provenance and warnings."""
    result = call_mcp(
        mcp_server, lambda s: s.call_tool("recommend", _si_recommend_args(si_cif))
    )

    assert result.isError is False
    data = _parsed(result)
    assert set(data) == {
        "intent",
        "analysis",
        "advice",
        "selection",
        "generated_files",
        "warnings",
        "bundle",
        "stages",
    }
    assert [stage["name"] for stage in data["stages"]] == [
        "load",
        "analyze",
        "advise",
        "kmesh",
        "select",
    ]
    assert data["selection"]["k_points"]["grid"] == [3, 3, 3]
    assert data["selection"]["k_points"]["provenance"]["source"] == "user_hint"
    assert isinstance(data["warnings"], list)
    assert data["generated_files"] == []
    assert data["bundle"] is None


def test_recommend_with_missing_pseudo_returns_fallback_provenance(
    mcp_server, call_mcp, si_cif: str
) -> None:
    """Missing pseudo metadata is not an error; selection records fallback."""
    result = call_mcp(
        mcp_server, lambda s: s.call_tool("recommend", _si_recommend_args(si_cif))
    )

    assert result.isError is False
    pseudo = _parsed(result)["selection"]["pseudopotentials"][0]
    assert pseudo["provenance"]["source"] == "fallback"
    assert pseudo["filename"] is None


def test_generate_returns_generated_files(
    mcp_server, call_mcp, si_cif: str, si_pseudo_metadata: dict
) -> None:
    """generate runs through Generate and returns generated input files."""
    result = call_mcp(
        mcp_server,
        lambda s: s.call_tool(
            "generate",
            _si_recommend_args(si_cif, with_pseudo=True, pseudo=si_pseudo_metadata),
        ),
    )

    assert result.isError is False
    data = _parsed(result)
    assert [stage["name"] for stage in data["stages"]] == [
        "load",
        "analyze",
        "advise",
        "kmesh",
        "select",
        "generate",
    ]
    assert [file["path"] for file in data["generated_files"]] == ["inputs/qe.in"]
    assert "CONTROL" in data["generated_files"][0]["content"]


def test_bundle_writes_under_bundle_root(
    mcp_server, call_mcp, si_cif: str, si_pseudo_metadata: dict, bundle_root: Path
) -> None:
    """bundle publishes a bundle directory under the configured bundle root."""
    args = _si_recommend_args(si_cif, with_pseudo=True, pseudo=si_pseudo_metadata)
    args["output_dir"] = "run-001"

    result = call_mcp(mcp_server, lambda s: s.call_tool("bundle", args))

    assert result.isError is False
    data = _parsed(result)
    assert [stage["name"] for stage in data["stages"]] == [
        "load",
        "analyze",
        "advise",
        "kmesh",
        "select",
        "generate",
        "bundle",
    ]
    assert data["bundle"]["path"].endswith("run-001")
    assert (bundle_root / "run-001" / "manifest.json").exists()


def test_bundle_response_path_is_server_relative(
    mcp_server, call_mcp, si_cif: str, si_pseudo_metadata: dict, bundle_root: Path
) -> None:
    """The bundle response path is the server-relative output_dir, not absolute."""
    args = _si_recommend_args(si_cif, with_pseudo=True, pseudo=si_pseudo_metadata)
    args["output_dir"] = "run-001"

    result = call_mcp(mcp_server, lambda s: s.call_tool("bundle", args))

    assert result.isError is False
    text = _text(result)
    data = json.loads(text)
    assert data["bundle"]["path"] == "run-001"
    assert str(bundle_root) not in text


def test_bundle_rejects_existing_output_dir(
    mcp_server, call_mcp, si_cif: str, si_pseudo_metadata: dict, bundle_root: Path
) -> None:
    """An existing bundle destination is refused with a stage_error."""
    (bundle_root / "run-002").mkdir()
    args = _si_recommend_args(si_cif, with_pseudo=True, pseudo=si_pseudo_metadata)
    args["output_dir"] = "run-002"

    result = call_mcp(mcp_server, lambda s: s.call_tool("bundle", args))

    assert result.isError is True
    body = _parsed(result)
    assert body["error"]["kind"] == "stage_error"
    assert "run-002" in body["error"]["message"]
    # The absolute host path must not leak.
    assert str(bundle_root) not in _text(result)


# --- analyze ----------------------------------------------------------------


def test_analyze_returns_analysis_record_json(
    mcp_server, call_mcp, si_cif: str
) -> None:
    """analyze runs only the Analyze stage and returns the analysis record."""
    result = call_mcp(
        mcp_server,
        lambda s: s.call_tool(
            "analyze", {"structure": {"content": si_cif, "format": "cif"}}
        ),
    )

    assert result.isError is False
    data = _parsed(result)
    assert data["reduced_formula"] == "Si"
    assert "formula" in data
    assert "elements" in data
    assert "analysis_warnings" in data
    # No recommendation records leak into the fact-only tool.
    assert "advice" not in data
    assert "selection" not in data
    assert "stages" not in data


# --- errors: clean transport bodies (path / from_dict / stage) --------------


def test_bad_structure_content_returns_tool_error(mcp_server, call_mcp) -> None:
    """Unparseable inline structure content maps to a clean invalid_request."""
    result = call_mcp(
        mcp_server,
        lambda s: s.call_tool(
            "recommend",
            {"structure": {"content": "not a structure", "format": "cif"}},
        ),
    )

    assert result.isError is True
    body = _parsed(result)
    assert body["error"]["kind"] == "invalid_request"
    assert "Could not parse" in body["error"]["message"]


def test_bad_hint_k_grid_zeros_returns_tool_error(
    mcp_server, call_mcp, si_cif: str
) -> None:
    """A non-positive k_grid fails contract validation with a clean invalid_request."""
    result = call_mcp(
        mcp_server,
        lambda s: s.call_tool(
            "recommend",
            {
                "structure": {"content": si_cif, "format": "cif"},
                "hints": {"k_grid": [0, 0, 0]},
            },
        ),
    )

    assert result.isError is True
    body = _parsed(result)
    assert body["error"]["kind"] == "invalid_request"
    assert "k_grid" in body["error"]["message"]


def test_contradictory_vdw_hints_returns_tool_error(
    mcp_server, call_mcp, si_cif: str
) -> None:
    """use_vdw=False with a vdw_method is rejected by the contract cleanly."""
    result = call_mcp(
        mcp_server,
        lambda s: s.call_tool(
            "recommend",
            {
                "structure": {"content": si_cif, "format": "cif"},
                "hints": {"k_grid": [3, 3, 3], "use_vdw": False, "vdw_method": "d3"},
            },
        ),
    )

    assert result.isError is True
    body = _parsed(result)
    assert body["error"]["kind"] == "invalid_request"
    assert "vdw_method" in body["error"]["message"]


@pytest.mark.parametrize("output_dir", ["../../etc", "/etc", "a/../../b"])
def test_bundle_traversal_or_absolute_output_dir_returns_tool_error(
    mcp_server, call_mcp, si_cif: str, output_dir: str
) -> None:
    """Traversal or absolute output_dir maps to a clean invalid_request."""
    result = call_mcp(
        mcp_server,
        lambda s: s.call_tool(
            "bundle",
            {
                "structure": {"content": si_cif, "format": "cif"},
                "output_dir": output_dir,
            },
        ),
    )

    assert result.isError is True
    body = _parsed(result)
    assert body["error"]["kind"] == "invalid_request"


@pytest.mark.parametrize("path", ["../escape", "/etc/passwd", "sub/../.."])
def test_structure_path_traversal_or_absolute_returns_tool_error(
    mcp_server, call_mcp, path: str
) -> None:
    """Traversal or absolute structure paths map to a clean invalid_request."""
    result = call_mcp(
        mcp_server,
        lambda s: s.call_tool(
            "recommend",
            {"structure": {"path": path}, "hints": {"k_grid": [3, 3, 3]}},
        ),
    )

    assert result.isError is True
    body = _parsed(result)
    assert body["error"]["kind"] == "invalid_request"


def test_structure_path_missing_file_returns_tool_error(mcp_server, call_mcp) -> None:
    """A server-side structure path that does not exist maps to a clean not_found."""
    result = call_mcp(
        mcp_server,
        lambda s: s.call_tool(
            "recommend",
            {"structure": {"path": "missing.cif"}, "hints": {"k_grid": [3, 3, 3]}},
        ),
    )

    assert result.isError is True
    body = _parsed(result)
    assert body["error"]["kind"] == "not_found"


def test_structure_path_without_configured_root_returns_tool_error(
    si_cif: str, bundle_root: Path
) -> None:
    """A server-side path with no configured structure root maps to invalid_request."""
    from goldilocks_core.jobs import CoreRuntime, Pipeline
    from goldilocks_core.kmesh import resolve_kpoints_from_advice
    from goldilocks_core.server.mcp import create_server

    server = create_server(
        runtime=CoreRuntime(pipeline=Pipeline(kmesh=resolve_kpoints_from_advice)),
        structure_root=None,
        bundle_root=bundle_root,
    )

    result = call_mcp_helper(
        server,
        "recommend",
        {"structure": {"path": "Si.cif"}, "hints": {"k_grid": [3, 3, 3]}},
    )

    assert result.isError is True
    body = _parsed(result)
    assert body["error"]["kind"] == "invalid_request"


def test_both_content_and_path_returns_tool_error(
    mcp_server, call_mcp, si_cif: str
) -> None:
    """Specifying both content and path maps to a clean invalid_request."""
    result = call_mcp(
        mcp_server,
        lambda s: s.call_tool(
            "recommend",
            {"structure": {"content": si_cif, "path": "Si.cif"}},
        ),
    )

    assert result.isError is True
    body = _parsed(result)
    assert body["error"]["kind"] == "invalid_request"
    assert "exactly one" in body["error"]["message"]


def test_internal_failure_is_redacted(si_cif: str, bundle_root: Path) -> None:
    """Unexpected non-validation errors return a redacted internal_error."""
    from goldilocks_core.jobs import CoreRuntime, Pipeline
    from goldilocks_core.kmesh import resolve_kpoints_from_advice
    from goldilocks_core.server.mcp import create_server

    runtime = CoreRuntime(pipeline=Pipeline(kmesh=resolve_kpoints_from_advice))

    def explode(_request: object) -> object:
        raise KeyError("secret-internal-token")

    runtime.run = explode  # type: ignore[method-assign]
    server = create_server(runtime=runtime, bundle_root=bundle_root)

    result = call_mcp_helper(
        server,
        "recommend",
        {
            "structure": {"content": si_cif, "format": "cif"},
            "hints": {"k_grid": [3, 3, 3]},
        },
    )

    assert result.isError is True
    body = _parsed(result)
    assert body["error"]["kind"] == "internal_error"
    assert "secret-internal-token" not in _text(result)


def test_file_exists_error_in_non_bundle_mode_is_redacted(
    si_cif: str, bundle_root: Path
) -> None:
    """FileExistsError from a non-bundle stage is a redacted internal_error."""
    from goldilocks_core.jobs import CoreRuntime, Pipeline
    from goldilocks_core.kmesh import resolve_kpoints_from_advice
    from goldilocks_core.server.mcp import create_server

    runtime = CoreRuntime(pipeline=Pipeline(kmesh=resolve_kpoints_from_advice))

    def explode(_request: object) -> object:
        raise FileExistsError(17, "File exists", "/private/secret-dest")

    runtime.run = explode  # type: ignore[method-assign]
    server = create_server(runtime=runtime, bundle_root=bundle_root)

    result = call_mcp_helper(
        server,
        "recommend",
        {
            "structure": {"content": si_cif, "format": "cif"},
            "hints": {"k_grid": [3, 3, 3]},
        },
    )

    assert result.isError is True
    body = _parsed(result)
    assert body["error"]["kind"] == "internal_error"
    assert "/private/secret-dest" not in _text(result)


def test_file_exists_error_in_bundle_mode_is_stage_error_with_public_path(
    si_cif: str, bundle_root: Path
) -> None:
    """FileExistsError at the bundle boundary is a stage_error with the public path."""
    from goldilocks_core.jobs import CoreRuntime, Pipeline
    from goldilocks_core.kmesh import resolve_kpoints_from_advice
    from goldilocks_core.server.mcp import create_server

    runtime = CoreRuntime(pipeline=Pipeline(kmesh=resolve_kpoints_from_advice))

    def explode(_request: object) -> object:
        raise FileExistsError(17, "File exists", "/private/secret-dest")

    runtime.run = explode  # type: ignore[method-assign]
    server = create_server(runtime=runtime, bundle_root=bundle_root)

    result = call_mcp_helper(
        server,
        "bundle",
        {"structure": {"content": si_cif, "format": "cif"}, "output_dir": "run-001"},
    )

    assert result.isError is True
    body = _parsed(result)
    assert body["error"]["kind"] == "stage_error"
    assert "run-001" in body["error"]["message"]
    assert "/private/secret-dest" not in _text(result)
    assert str(bundle_root) not in _text(result)


# --- errors: request validation (shared deserializer, stable isError JSON) ----


def test_missing_structure_returns_tool_error(mcp_server, call_mcp) -> None:
    """A call without a structure field is a stable isError result."""
    result = call_mcp(
        mcp_server, lambda s: s.call_tool("recommend", {"hints": {"k_grid": [3, 3, 3]}})
    )

    assert result.isError is True
    body = _parsed(result)
    assert body["error"]["kind"] == "invalid_request"
    assert "structure" in body["error"]["message"]


def test_unsupported_code_returns_tool_error(mcp_server, call_mcp, si_cif: str) -> None:
    """An unsupported DFT code is a stable isError result naming the valid value."""
    result = call_mcp(
        mcp_server,
        lambda s: s.call_tool(
            "recommend",
            {
                "structure": {"content": si_cif, "format": "cif"},
                "intent": {"code": "vasp"},
            },
        ),
    )

    assert result.isError is True
    body = _parsed(result)
    assert body["error"]["kind"] == "invalid_request"
    assert "quantum_espresso" in body["error"]["message"]


def test_unknown_hint_key_returns_tool_error(mcp_server, call_mcp, si_cif: str) -> None:
    """Unknown hint keys are a stable isError result naming the bad key."""
    result = call_mcp(
        mcp_server,
        lambda s: s.call_tool(
            "recommend",
            {"structure": {"content": si_cif, "format": "cif"}, "hints": {"bogus": 1}},
        ),
    )

    assert result.isError is True
    body = _parsed(result)
    assert body["error"]["kind"] == "invalid_request"
    assert "bogus" in body["error"]["message"]


def test_unknown_structure_key_returns_tool_error(
    mcp_server, call_mcp, si_cif: str
) -> None:
    """Unknown structure sub-keys are a stable isError result naming the bad key."""
    result = call_mcp(
        mcp_server,
        lambda s: s.call_tool(
            "recommend",
            {"structure": {"content": si_cif, "format": "cif", "bogus": 1}},
        ),
    )

    assert result.isError is True
    body = _parsed(result)
    assert body["error"]["kind"] == "invalid_request"
    assert "bogus" in body["error"]["message"]


def test_bad_vdw_method_returns_tool_error(mcp_server, call_mcp, si_cif: str) -> None:
    """An unsupported vdw_method is a stable isError result."""
    result = call_mcp(
        mcp_server,
        lambda s: s.call_tool(
            "recommend",
            {
                "structure": {"content": si_cif, "format": "cif"},
                "hints": {"k_grid": [3, 3, 3], "vdw_method": "grimme"},
            },
        ),
    )

    assert result.isError is True
    body = _parsed(result)
    assert body["error"]["kind"] == "invalid_request"
    # The shared deserializer rejects 'grimme' against the contract Literal.
    assert "vdw_method" in body["error"]["message"]


def test_bundle_without_output_dir_returns_tool_error(
    mcp_server, call_mcp, si_cif: str
) -> None:
    """bundle without output_dir is a stable isError result naming output_dir."""
    result = call_mcp(
        mcp_server,
        lambda s: s.call_tool(
            "bundle",
            {
                "structure": {"content": si_cif, "format": "cif"},
                "hints": {"k_grid": [3, 3, 3]},
            },
        ),
    )

    assert result.isError is True
    body = _parsed(result)
    assert body["error"]["kind"] == "invalid_request"
    assert "output_dir" in body["error"]["message"]


def test_malformed_pseudo_metadata_returns_tool_error(
    mcp_server, call_mcp, si_cif: str, si_pseudo_metadata: dict
) -> None:
    """A malformed pseudo_metadata field is a stable isError result."""
    payload = dict(si_pseudo_metadata)
    payload["filename"] = 123  # filename must be a string
    result = call_mcp(
        mcp_server,
        lambda s: s.call_tool(
            "recommend",
            {
                "structure": {"content": si_cif, "format": "cif"},
                "hints": {"k_grid": [3, 3, 3]},
                "pseudo_metadata": [payload],
            },
        ),
    )

    assert result.isError is True
    body = _parsed(result)
    assert body["error"]["kind"] == "invalid_request"
    assert "filename" in body["error"]["message"]


# --- optional-extra guard ---------------------------------------------------


def test_create_server_raises_clear_error_when_mcp_extra_missing() -> None:
    """create_server raises a clear install hint when the [mcp] extra is absent."""
    from goldilocks_core.server import mcp as server_mcp

    original = (server_mcp.Server, server_mcp.Tool, server_mcp.CallToolResult)
    try:
        server_mcp.Server = None  # type: ignore[assignment]
        server_mcp.Tool = None  # type: ignore[assignment]
        server_mcp.CallToolResult = None  # type: ignore[assignment]
        with pytest.raises(ImportError, match=r"\[mcp\]"):
            server_mcp.create_server()
    finally:
        server_mcp.Server, server_mcp.Tool, server_mcp.CallToolResult = original


# --- helpers for standalone servers (no shared fixtures) --------------------


def call_mcp_helper(server: object, tool_name: str, arguments: dict) -> object:
    """Run one tool call against a standalone server in a fresh session."""
    import anyio
    from mcp.shared.memory import create_connected_server_and_client_session

    async def _run() -> object:
        async with create_connected_server_and_client_session(server) as session:
            await session.initialize()
            return await session.call_tool(tool_name, arguments)

    return anyio.run(_run)
