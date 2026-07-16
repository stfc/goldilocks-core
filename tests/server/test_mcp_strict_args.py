from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pymatgen.core import Lattice, Structure

if TYPE_CHECKING:
    pass

# In-process MCP client tests for the strict-argument contract: unknown root
# keys are rejected (not silently dropped), no Pydantic coercion of
# booleans/strings/floats into ints/floats, explicit ``null`` for optional
# sections is rejected (not collapsed to omitted), published ``inputSchema``
# expresses strict root objects (``additionalProperties: false``), every client
# input failure returns the stable ``{"error": {"kind", "message"}}`` JSON
# (never SDK ``Error executing tool ...`` prose), and internal stage failures
# redact private model/config paths.
#
# No real model is loaded (explicit k-grid hint + heuristic-kpoints runtime) and
# no network is involved.


def _text(result: object) -> str:
    """Return the text content of a CallToolResult."""
    return result.content[0].text  # type: ignore[union-attr]


def _body(result: object) -> dict:
    """Return the parsed JSON body, asserting the stable error/success shape."""
    return json.loads(_text(result))


def _si_cif() -> str:
    """Return CIF text for a small Si structure."""
    return Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]]).to(fmt="cif")


def _call(server: object, tool: str, arguments: dict) -> object:
    """Run one tool call against a server in a fresh in-process session."""
    import anyio
    from mcp.shared.memory import create_connected_server_and_client_session

    async def _run() -> object:
        async with create_connected_server_and_client_session(server) as session:
            await session.initialize()
            return await session.call_tool(tool, arguments)

    return anyio.run(_run)


def _list_schemas(server: object) -> dict[str, dict]:
    """Return {tool_name: inputSchema} for a server via one in-process session."""
    import anyio
    from mcp.shared.memory import create_connected_server_and_client_session

    async def _run() -> dict[str, dict]:
        async with create_connected_server_and_client_session(server) as session:
            await session.initialize()
            tools = await session.list_tools()
            return {tool.name: tool.inputSchema for tool in tools.tools}

    return anyio.run(_run)


def _strict_server(*, bundle_root: Path | None = None) -> object:
    """Return an MCP server with a heuristic runtime (no model load)."""
    from goldilocks_core.jobs import CoreRuntime, Pipeline
    from goldilocks_core.kmesh import resolve_kpoints_from_advice
    from goldilocks_core.server.mcp import create_server

    return create_server(
        runtime=CoreRuntime(pipeline=Pipeline(kmesh=resolve_kpoints_from_advice)),
        bundle_root=bundle_root or Path("/tmp/mcp-strict-bundles"),
    )


# --- unknown root keys are rejected, not silently dropped ------------------


@pytest.mark.parametrize(
    ("tool", "extra"),
    [
        ("recommend", {"mode": "bundle"}),
        ("recommend", {"output_dir": "/private/bundle"}),
        ("recommend", {"foo": 1}),
        ("recommend", {"mode": "recommend", "accuracy_level": "high"}),
        ("generate", {"output_dir": "run-001"}),
        ("generate", {"mode": "generate"}),
        ("bundle", {"mode": "bundle"}),
        ("bundle", {"foo": "bar"}),
        ("analyze", {"output_dir": "run-001"}),
        ("analyze", {"intent": {"code": "quantum_espresso"}}),
        ("analyze", {"hints": {"k_grid": [3, 3, 3]}}),
        ("analyze", {"mode": "analyze"}),
    ],
)
def test_unknown_root_key_is_rejected_with_stable_json(
    tool: str, extra: dict, bundle_root: Path
) -> None:
    """Unknown root keys (mode, output_dir on the wrong tool, arbitrary fields)
    are rejected by the shared deserializer as ``invalid_request``, never silently
    dropped by a lax/coercing framework root model."""
    server = _strict_server(bundle_root=bundle_root)
    args: dict = {"structure": {"content": _si_cif(), "format": "cif"}}
    if tool != "analyze":
        args["hints"] = {"k_grid": [3, 3, 3]}
    if tool == "bundle":
        args["output_dir"] = "run-001"
    args.update(extra)

    result = _call(server, tool, args)

    assert result.isError is True
    body = _body(result)
    assert body["error"]["kind"] == "invalid_request"
    # The bad key is named in the message, not silently discarded.
    bad_key = next(iter(extra))
    assert bad_key in body["error"]["message"]


def test_unknown_root_key_does_not_succeed_or_change_mode(
    bundle_root: Path,
) -> None:
    """``mode`` on ``recommend`` is rejected rather than silently selecting a mode.

    A success here would mean the unknown ``mode`` field was accepted and the
    tool ran; instead it must be a stable ``invalid_request``.
    """
    server = _strict_server(bundle_root=bundle_root)
    result = _call(
        server,
        "recommend",
        {
            "structure": {"content": _si_cif(), "format": "cif"},
            "hints": {"k_grid": [3, 3, 3]},
            "mode": "bundle",
            "output_dir": "/private/bundle",
        },
    )
    assert result.isError is True
    body = _body(result)
    assert body["error"]["kind"] == "invalid_request"
    assert "mode" in body["error"]["message"]
    assert "output_dir" in body["error"]["message"]
    # The private bundle path must not leak into the rejection message.
    assert "/private/bundle" not in _text(result)


# --- no Pydantic coercion ---------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value", "needle"),
    [
        ("k_grid", "3", "k_grid"),
        ("k_grid", 3, "k_grid"),
        ("k_grid", [3.0, 3.0, 3.0], "k_grid"),
        ("k_grid", [True, True, True], "k_grid"),
        ("k_grid", [3, 3], "k_grid"),
        ("k_spacing", "0.2", "k_spacing"),
        ("k_spacing", True, "k_spacing"),
        ("k_spacing", 0, "k_spacing"),
        ("smearing_width_ry", "0.5", "smearing_width_ry"),
        ("spin_polarized", "true", "spin_polarized"),
        ("spin_polarized", 1, "spin_polarized"),
        ("spin_orbit_coupling", "false", "spin_orbit_coupling"),
        ("use_vdw", "true", "use_vdw"),
        ("vdw_method", 123, "vdw_method"),
        ("vdw_method", "grimme", "vdw_method"),
        ("electron_maxstep", "5", "electron_maxstep"),
        ("electron_maxstep", 5.0, "electron_maxstep"),
        ("electron_maxstep", True, "electron_maxstep"),
        ("conv_thr", "1e-6", "conv_thr"),
        ("conv_thr", True, "conv_thr"),
        ("mixing_beta", "0.7", "mixing_beta"),
    ],
)
def test_hint_field_rejects_coercion(
    field: str, value: object, needle: str, bundle_root: Path
) -> None:
    """Booleans, strings, and floats are not coerced into ints/floats by Pydantic.

    Every value flows untouched to the shared deserializer, which uses
    ``isinstance`` checks (rejecting ``bool`` as ``int``, ``str`` as ``number``,
    short tuples, etc.) and returns a stable ``invalid_request`` naming the field.
    """
    server = _strict_server(bundle_root=bundle_root)
    result = _call(
        server,
        "recommend",
        {
            "structure": {"content": _si_cif(), "format": "cif"},
            "hints": {"k_grid": [3, 3, 3], field: value},
        },
    )
    # `k_grid` with a wrong-type value may fail before the k_grid hint is used;
    # either way the result is a stable invalid_request naming the bad field.
    del field, value
    assert result.isError is True
    body = _body(result)
    assert body["error"]["kind"] == "invalid_request"
    assert needle in body["error"]["message"]


@pytest.mark.parametrize(
    ("field", "value", "needle"),
    [
        ("code", "vasp", "intent.code"),
        ("task", "relax", "intent.task"),
        ("functional", 123, "intent.functional"),
        ("pseudo_mode", 123, "intent.pseudo_mode"),
    ],
)
def test_intent_field_rejects_coercion(
    field: str, value: object, needle: str, bundle_root: Path
) -> None:
    """Intent enums and strings are not coerced; the contract Literal/str check
    rejects the bad value with a stable ``invalid_request``."""
    server = _strict_server(bundle_root=bundle_root)
    result = _call(
        server,
        "recommend",
        {
            "structure": {"content": _si_cif(), "format": "cif"},
            "hints": {"k_grid": [3, 3, 3]},
            "intent": {"code": "quantum_espresso", field: value},
        },
    )
    assert result.isError is True
    body = _body(result)
    assert body["error"]["kind"] == "invalid_request"
    assert needle in body["error"]["message"]


@pytest.mark.parametrize(
    ("override", "needle"),
    [
        ({"filename": 123}, "filename"),
        ({"filepath": 123}, "filepath"),
        ({"header_format": 123}, "header_format"),
        ({"z_valence": "4.0"}, "z_valence"),
        ({"z_valence": True}, "z_valence"),
        ({"is_sssp": "true"}, "is_sssp"),
        ({"is_sssp": 1}, "is_sssp"),
        ({"pseudo_info": "x"}, "pseudo_info"),
        ({"sssp_recommended_cutoff": "x"}, "sssp_recommended_cutoff"),
        ({"element": 123}, "element"),
        ({"relativistic": 123}, "relativistic"),
    ],
)
def test_pseudo_metadata_field_rejects_coercion(
    override: dict, needle: str, si_pseudo_metadata: dict, bundle_root: Path
) -> None:
    """Nested pseudopotential fields are not coerced; ``PseudoMetadata.from_dict``
    rejects bad types with a stable ``invalid_request`` naming the field."""
    server = _strict_server(bundle_root=bundle_root)
    payload = dict(si_pseudo_metadata)
    payload.update(override)
    result = _call(
        server,
        "recommend",
        {
            "structure": {"content": _si_cif(), "format": "cif"},
            "hints": {"k_grid": [3, 3, 3]},
            "pseudo_metadata": [payload],
        },
    )
    assert result.isError is True
    body = _body(result)
    assert body["error"]["kind"] == "invalid_request"
    assert needle in body["error"]["message"]


def test_pseudo_metadata_unknown_field_is_rejected(
    si_pseudo_metadata: dict, bundle_root: Path
) -> None:
    """Unknown pseudopotential keys are rejected by ``PseudoMetadata.from_dict``."""
    server = _strict_server(bundle_root=bundle_root)
    payload = dict(si_pseudo_metadata)
    payload["bogus"] = 1
    result = _call(
        server,
        "recommend",
        {
            "structure": {"content": _si_cif(), "format": "cif"},
            "hints": {"k_grid": [3, 3, 3]},
            "pseudo_metadata": [payload],
        },
    )
    assert result.isError is True
    body = _body(result)
    assert body["error"]["kind"] == "invalid_request"
    assert "bogus" in body["error"]["message"]


def test_pseudo_free_form_maps_accept_arbitrary_contents(
    si_pseudo_metadata: dict, bundle_root: Path
) -> None:
    """``pseudo_info`` and ``sssp_recommended_cutoff`` accept arbitrary keys.

    These two fields are the intentional free-form metadata-map exceptions: their
    *typed* ``PseudoMetadata`` siblings reject unknown keys (above) and
    wrong-typed values (see the coercion parametrization), but their free-form
    *contents* are accepted by contract design because the keys are raw UPF/SSSP
    header data outside the Core contract.
    """
    server = _strict_server(bundle_root=bundle_root)
    payload = dict(si_pseudo_metadata)
    payload["pseudo_info"] = {"arbitrary_upf_key": "raw-value", "another": 7}
    payload["sssp_recommended_cutoff"] = {"ecutwfc_ry": 30.0, "custom_cutoff": 99.0}
    result = _call(
        server,
        "recommend",
        {
            "structure": {"content": _si_cif(), "format": "cif"},
            "hints": {"k_grid": [3, 3, 3]},
            "pseudo_metadata": [payload],
        },
    )
    assert result.isError is False
    data = _body(result)
    pseudo = data["selection"]["pseudopotentials"][0]
    # The free-form map is consumed: the recognized SSSP cutoff key surfaces in
    # the selection record. The arbitrary ``custom_cutoff`` / ``pseudo_info``
    # keys are accepted (no invalid_request) but not echoed by selection, which
    # only surfaces recognized cutoff fields — unlike an unknown *typed*
    # ``PseudoMetadata`` key, which is rejected (see the test above).
    assert pseudo["ecutwfc_ry"] == 30.0
    assert "pseudo_info" not in pseudo


# --- explicit null is rejected, not omitted ---------------------------------


@pytest.mark.parametrize("section", ["intent", "hints", "pseudo_metadata"])
def test_explicit_null_section_is_rejected_not_omitted(
    section: str, bundle_root: Path
) -> None:
    """An explicit ``null`` for an optional section is malformed, not omitted.

    The shared deserializer calls ``from_dict(None)`` (or checks the list type),
    which rejects ``None`` with a stable ``invalid_request``. Omitting the section
    instead uses the contract default (see the next test).
    """
    server = _strict_server(bundle_root=bundle_root)
    result = _call(
        server,
        "recommend",
        {
            "structure": {"content": _si_cif(), "format": "cif"},
            "hints": {"k_grid": [3, 3, 3]},
            section: None,
        },
    )
    assert result.isError is True
    body = _body(result)
    assert body["error"]["kind"] == "invalid_request"


def test_explicit_null_structure_is_rejected(bundle_root: Path) -> None:
    """An explicit ``null`` structure is rejected, not treated as omitted."""
    server = _strict_server(bundle_root=bundle_root)
    result = _call(
        server,
        "recommend",
        {"structure": None, "hints": {"k_grid": [3, 3, 3]}},
    )
    assert result.isError is True
    body = _body(result)
    assert body["error"]["kind"] == "invalid_request"


def test_omitted_optional_sections_use_defaults_and_succeed(
    bundle_root: Path,
) -> None:
    """Omitting ``intent``/``hints``/``pseudo_metadata`` uses contract defaults and
    succeeds (the explicit-null cases above must not collapse into this path)."""
    server = _strict_server(bundle_root=bundle_root)
    result = _call(
        server,
        "recommend",
        {
            "structure": {"content": _si_cif(), "format": "cif"},
            "hints": {"k_grid": [3, 3, 3]},
        },
    )
    assert result.isError is False
    data = _body(result)
    assert data["intent"]["code"] == "quantum_espresso"
    assert data["selection"]["k_points"]["grid"] == [3, 3, 3]


def test_analyze_explicit_null_structure_is_rejected(bundle_root: Path) -> None:
    """analyze rejects an explicit ``null`` structure rather than erroring later."""
    server = _strict_server(bundle_root=bundle_root)
    result = _call(server, "analyze", {"structure": None})
    assert result.isError is True
    body = _body(result)
    assert body["error"]["kind"] == "invalid_request"


# --- published inputSchema expresses strict root objects ------------------


@pytest.mark.parametrize("tool", ["recommend", "generate", "bundle", "analyze"])
def test_root_schema_forbids_additional_properties(tool: str) -> None:
    """Every tool's root ``inputSchema`` has ``additionalProperties: false``."""
    schemas = _list_schemas(_strict_server())
    assert schemas[tool]["additionalProperties"] is False


def test_nested_schema_defs_forbid_additional_properties() -> None:
    """The nested schema models also express ``additionalProperties: false``."""
    schemas = _list_schemas(_strict_server())
    defs = schemas["recommend"]["$defs"]
    for name in ("StructureArg", "IntentArg", "HintsArg", "PseudoMetadataArg"):
        assert defs[name]["additionalProperties"] is False, name


def test_bundle_schema_has_output_dir_others_do_not() -> None:
    """``output_dir`` is published only on ``bundle``; no tool publishes ``mode``."""
    schemas = _list_schemas(_strict_server())
    assert "output_dir" in schemas["bundle"]["properties"]
    for tool in ("recommend", "generate", "analyze"):
        assert "output_dir" not in schemas[tool]["properties"]
    for tool in schemas:
        assert "mode" not in schemas[tool]["properties"]
        assert "accuracy_level" not in schemas[tool]["properties"]


def test_schemas_are_json_serializable_objects() -> None:
    """All tool schemas are JSON-serializable strict objects."""
    schemas = _list_schemas(_strict_server())
    for name, schema in schemas.items():
        json.dumps(schema)
        assert schema["type"] == "object", name
        assert schema["additionalProperties"] is False, name


# --- stable error JSON (no framework prose) ---------------------------------


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("recommend", {"hints": {"k_grid": [3, 3, 3]}}),  # missing structure
        ("recommend", {"structure": {"content": "x", "format": "cif"}}),  # bad content
        (
            "recommend",
            {"structure": {"path": "missing.cif"}, "hints": {"k_grid": [3, 3, 3]}},
        ),
        (
            "recommend",
            {
                "structure": {"content": _si_cif(), "format": "cif"},
                "hints": {"k_grid": [0, 0, 0]},
            },
        ),
        (
            "recommend",
            {"structure": {"content": _si_cif(), "format": "cif"}, "mode": "bundle"},
        ),
        (
            "recommend",
            {"structure": {"content": _si_cif(), "format": "cif"}, "intent": None},
        ),
        (
            "recommend",
            {
                "structure": {"content": _si_cif(), "format": "cif"},
                "hints": {"k_grid": "3"},
            },
        ),
        (
            "bundle",
            {"structure": {"content": _si_cif(), "format": "cif"}},
        ),  # missing output_dir
        ("analyze", {"intent": {"code": "quantum_espresso"}}),  # missing structure
    ],
)
def test_every_error_returns_stable_json_not_sdk_prose(
    tool: str, args: dict, bundle_root: Path
) -> None:
    """No client input failure surfaces as SDK ``Error executing tool ...``
    prose. Every failure parses to ``{"error": {"kind": str, "message": str}}``."""
    server = _strict_server(bundle_root=bundle_root)
    result = _call(server, tool, args)
    assert result.isError is True
    text = _text(result)
    # The stable JSON body parses and carries typed kind/message strings.
    body = json.loads(text)
    assert isinstance(body["error"]["kind"], str)
    assert isinstance(body["error"]["message"], str)
    assert body["error"]["kind"] in {
        "invalid_request",
        "not_found",
        "stage_error",
        "internal_error",
    }
    # No SDK-generated prose wraps the body.
    assert not text.startswith("Error executing tool")
    assert "Error executing tool" not in text
    assert (
        "validation error" not in text.lower()
        or "validation" in body["error"]["message"].lower()
    )


# --- private path redaction -------------------------------------------------


def _runtime_that_raises(value_error: ValueError) -> object:
    """Return a heuristic runtime whose ``run`` raises the given ValueError."""
    from goldilocks_core.jobs import CoreRuntime, Pipeline
    from goldilocks_core.kmesh import resolve_kpoints_from_advice

    runtime = CoreRuntime(pipeline=Pipeline(kmesh=resolve_kpoints_from_advice))

    def explode(_request: object) -> object:
        raise value_error

    runtime.run = explode  # type: ignore[method-assign]
    return runtime


def test_stage_value_error_with_model_path_is_redacted(
    bundle_root: Path,
) -> None:
    """A stage ``ValueError`` carrying an internal model path is redacted to
    ``internal_error``; the absolute path never reaches the client."""
    from goldilocks_core.server.mcp import create_server

    runtime = _runtime_that_raises(
        ValueError("failed loading model /private/models/secret.joblib")
    )
    server = create_server(runtime=runtime, bundle_root=bundle_root)
    result = _call(
        server,
        "recommend",
        {
            "structure": {"content": _si_cif(), "format": "cif"},
            "hints": {"k_grid": [3, 3, 3]},
        },
    )
    assert result.isError is True
    body = _body(result)
    assert body["error"]["kind"] == "internal_error"
    text = _text(result)
    assert "/private/models/secret.joblib" not in text
    assert "failed loading model" not in text


def test_stage_value_error_with_config_path_is_redacted(
    bundle_root: Path,
) -> None:
    """A stage ``ValueError`` carrying an internal config path is redacted."""
    from goldilocks_core.server.mcp import create_server

    runtime = _runtime_that_raises(
        ValueError("QRF config mismatch for /etc/goldilocks/qrf.toml")
    )
    server = create_server(runtime=runtime, bundle_root=bundle_root)
    result = _call(
        server,
        "generate",
        {
            "structure": {"content": _si_cif(), "format": "cif"},
            "hints": {"k_grid": [3, 3, 3]},
        },
    )
    assert result.isError is True
    body = _body(result)
    assert body["error"]["kind"] == "internal_error"
    text = _text(result)
    assert "/etc/goldilocks/qrf.toml" not in text


def test_stage_value_error_message_not_echoed_even_without_paths(
    bundle_root: Path,
) -> None:
    """A stage ``ValueError`` is redacted to ``internal_error`` regardless of
    whether its message contains a path; the message is never echoed."""
    from goldilocks_core.server.mcp import create_server

    runtime = _runtime_that_raises(ValueError("internal stage detail: token-XYZ"))
    server = create_server(runtime=runtime, bundle_root=bundle_root)
    result = _call(
        server,
        "recommend",
        {
            "structure": {"content": _si_cif(), "format": "cif"},
            "hints": {"k_grid": [3, 3, 3]},
        },
    )
    assert result.isError is True
    body = _body(result)
    assert body["error"]["kind"] == "internal_error"
    assert "token-XYZ" not in _text(result)


def test_bundle_destination_failure_echoes_only_public_path(
    bundle_root: Path, si_pseudo_metadata: dict
) -> None:
    """The bundle destination ``FileExistsError`` is the one stage failure whose
    message is echoed, and only with the client-relative ``output_dir``."""
    from goldilocks_core.jobs import CoreRuntime, Pipeline
    from goldilocks_core.kmesh import resolve_kpoints_from_advice
    from goldilocks_core.server.mcp import create_server

    (bundle_root / "run-001").mkdir()
    runtime = CoreRuntime(pipeline=Pipeline(kmesh=resolve_kpoints_from_advice))

    def explode(_request: object) -> object:
        raise FileExistsError(17, "File exists", str(bundle_root / "run-001"))

    runtime.run = explode  # type: ignore[method-assign]
    server = create_server(runtime=runtime, bundle_root=bundle_root)
    result = _call(
        server,
        "bundle",
        {
            "structure": {"content": _si_cif(), "format": "cif"},
            "hints": {"k_grid": [3, 3, 3]},
            "output_dir": "run-001",
            "pseudo_metadata": [si_pseudo_metadata],
        },
    )
    assert result.isError is True
    body = _body(result)
    assert body["error"]["kind"] == "stage_error"
    assert "run-001" in body["error"]["message"]
    assert str(bundle_root) not in _text(result)
