"""Tests for goldilocks_core.server.mcp (v2 epic 8, #8).

Deliberately thin on business-logic scenarios (test_handlers.py already
covers those) -- this file is about what's MCP-specific: the strict
tool schema, the real package version (issue #8's own evidence #3),
and ToolError propagation.

No ``pytest-asyncio`` in this project's dependencies -- every test
below runs its coroutine through a plain ``asyncio.run()`` instead of a
native ``async def`` test function.
"""

from __future__ import annotations

import asyncio
import math
from importlib.metadata import version as package_version
from typing import Any

import pytest

pytest.importorskip("mcp")

from mcp.server.mcpserver.exceptions import ToolError
from support import strict_json

from goldilocks_core.server.mcp import create_server

_SILICON_GAMMA_INTERVAL = [round(2 * math.pi / 5.431, 8), None]
"""Rung 1 of the bundled Si.cif's ladder (cubic, a = 5.431 A): every
k-distance above |b| = 2 pi / a, with no upper bound."""


def _gamma_only_call(server: Any, tool: str, silicon_cif: str) -> Any:
    return asyncio.run(
        server.call_tool(
            tool,
            {
                "document": {
                    "structure_content": silicon_cif,
                    "hpc": "scarf",
                    "overrides": {"k_grid": [1, 1, 1]},
                }
            },
        )
    )


class TestServerIdentity:
    def test_version_matches_the_installed_package_not_a_hardcoded_string(self) -> None:
        """Issue #8's own evidence #3: v1 hardcoded version="0.1.0",
        disagreeing with capabilities.py's real
        importlib.metadata.version call. (This package's own current
        version happens to also read "0.1.0" -- the point is that this
        now comes from the same live call capabilities.py uses, not a
        second, independently-hardcoded literal that could drift.)"""
        from goldilocks_core.capabilities import capabilities

        server = create_server()

        assert server.version == package_version("goldilocks-core")
        assert server.version == capabilities()["core_version"]


class TestToolCatalogue:
    def test_exposes_exactly_five_tools(self) -> None:
        server = create_server()

        tools = asyncio.run(server.list_tools())

        assert {tool.name for tool in tools} == {
            "capabilities",
            "inspect_structure",
            "magnetic_orderings",
            "explain",
            "run",
        }

    def test_every_tool_forbids_additional_properties(self) -> None:
        server = create_server()

        tools = asyncio.run(server.list_tools())

        for tool in tools:
            assert tool.input_schema["additionalProperties"] is False, tool.name


class TestToolCalls:
    def test_capabilities_tool_returns_the_real_contract(self) -> None:
        from goldilocks_core.capabilities import capabilities

        server = create_server()

        result = asyncio.run(server.call_tool("capabilities", {}))

        assert result.is_error is False
        assert result.structured_content == capabilities()

    def test_inspect_structure_tool(self, silicon_cif: str) -> None:
        server = create_server()

        result = asyncio.run(
            server.call_tool(
                "inspect_structure", {"document": {"structure_content": silicon_cif}}
            )
        )

        assert result.is_error is False
        assert result.structured_content["structure"]["reduced_formula"] == "Si"

    def test_magnetic_orderings_tool_lists_the_fm_candidate_unranked(
        self, silicon_cif: str
    ) -> None:
        server = create_server()

        result = asyncio.run(
            server.call_tool(
                "magnetic_orderings", {"document": {"structure_content": silicon_cif}}
            )
        )

        assert result.is_error is False
        assert result.structured_content["ranked"] is False
        assert result.structured_content["candidates"][0]["label"] == "fm"

    def test_run_tool_end_to_end(self, real_assets, silicon_cif: str) -> None:
        server = create_server()

        result = asyncio.run(
            server.call_tool(
                "run", {"document": {"structure_content": silicon_cif, "hpc": "scarf"}}
            )
        )

        assert result.is_error is False
        assert "scf.in" in result.structured_content["files"]

    def test_run_tool_dos_task_generates_all_three_steps(
        self, real_assets, silicon_cif: str
    ) -> None:
        """v2 epic 9 (#9, #28): the MCP `run` tool used to silently
        ignore `task`, always running the scf-only pipeline -- this
        confirms it actually routes to advise_dos/generate_dos through
        the real MCP transport (the same shared _handlers.run HTTP
        calls, so this is really pinning that the document.task field
        reaches it, not re-testing the routing logic itself)."""
        server = create_server()

        result = asyncio.run(
            server.call_tool(
                "run",
                {
                    "document": {
                        "structure_content": silicon_cif,
                        "hpc": "scarf",
                        "task": "dos",
                    }
                },
            )
        )

        assert result.is_error is False
        files = result.structured_content["files"]
        assert "scf.in" in files
        assert "nscf.in" in files
        assert "dos.in" in files

    def test_run_tool_band_task_generates_every_step(
        self, silicon_fixture_table, silicon_cif: str
    ) -> None:
        """#118: task='band' reaches the shared handler through the real MCP
        transport, which publishes the bands step's path as k_path and its
        other decisions under bands_ names."""
        server = create_server()

        result = asyncio.run(
            server.call_tool(
                "run",
                {
                    "document": {
                        "structure_content": silicon_cif,
                        "hpc": "scarf",
                        "task": "band",
                    }
                },
            )
        )

        assert result.is_error is False
        files = result.structured_content["files"]
        for name in ("scf.in", "bands.in", "bands_x.in", "submit.sh"):
            assert name in files, name
        assert {"k_path", "bands_nbnd"} <= set(result.structured_content["records"])

    @pytest.mark.parametrize(
        ("task", "first_step"),
        [("phonon", "scf"), ("relax-phonon", "relax"), ("vc-relax-phonon", "vc-relax")],
    )
    def test_explain_and_run_tools_route_each_phonon_task(
        self, silicon_fixture_table, silicon_cif: str, task: str, first_step: str
    ) -> None:
        """#215: each phonon task reaches the shared handlers through the real
        MCP transport: explain finds nothing to refuse in Si set to a
        non-metal, which a phonon task needs on smearing without a model to
        decide it, and run generates the first pw.x step, ph.x, q2r.x and
        both matdyn.x inputs, with the decisions laid out under the ph, q2r,
        phonon_dos and dispersion steps as explain lays them out."""
        server = create_server()
        document = {
            "structure_content": silicon_cif,
            "hpc": "scarf",
            "task": task,
            "overrides": {"is_metal": "non_metal"},
        }

        explained = asyncio.run(server.call_tool("explain", {"document": document}))
        result = asyncio.run(server.call_tool("run", {"document": document}))

        assert (explained.is_error, result.is_error) == (False, False)
        assert explained.structured_content["blocking"] == []
        files = result.structured_content["files"]
        for name in (
            f"{first_step}.in",
            "ph.in",
            "q2r.in",
            "phonon_dos.in",
            "dispersion.in",
        ):
            assert name in files, name
        layout = result.structured_content["layout"]
        assert layout == explained.structured_content["layout"]
        assert [step["name"] for step in layout["steps"]] == [
            first_step,
            "ph",
            "q2r",
            "phonon_dos",
            "dispersion",
        ]

    def test_run_tool_relax_task_generates_relax_in(
        self, real_assets, silicon_cif: str
    ) -> None:
        """v2 epic 10 (#10): confirms task='relax' actually routes
        through the real MCP transport, same shape as the dos check
        above."""
        server = create_server()

        result = asyncio.run(
            server.call_tool(
                "run",
                {
                    "document": {
                        "structure_content": silicon_cif,
                        "hpc": "scarf",
                        "task": "relax",
                    }
                },
            )
        )

        assert result.is_error is False
        assert "relax.in" in result.structured_content["files"]

    def test_explain_tool_answers_a_gamma_only_mesh_with_strict_json(
        self, silicon_cif: str
    ) -> None:
        """The tool's text content carried Infinity for rung 1's open
        k-distance bound, while its structured content read null (#137)."""
        result = _gamma_only_call(create_server(), "explain", silicon_cif)

        assert result.is_error is False
        records = strict_json(result.content[0].text)["records"]
        interval = records["k_sampling"]["value"]["k_distance_interval"]
        assert interval == _SILICON_GAMMA_INTERVAL
        structured = result.structured_content["records"]["k_sampling"]["value"]
        assert structured["k_distance_interval"] == _SILICON_GAMMA_INTERVAL

    def test_run_tool_answers_a_gamma_only_mesh_with_strict_json(
        self, silicon_fixture_table, silicon_cif: str
    ) -> None:
        result = _gamma_only_call(create_server(), "run", silicon_cif)

        assert result.is_error is False
        records = strict_json(result.content[0].text)["records"]
        interval = records["k_sampling"]["value"]["k_distance_interval"]
        assert interval == _SILICON_GAMMA_INTERVAL

    def test_explain_tool_returns_the_reasons_the_run_tool_refuses_with(
        self, silicon_cif: str
    ) -> None:
        """#165: no real assets, so the isolated asset root's uninstalled
        default table blocks both tools."""
        server = create_server()
        arguments = {"document": {"structure_content": silicon_cif, "hpc": "scarf"}}

        explained = asyncio.run(server.call_tool("explain", arguments))

        assert explained.is_error is False
        blocking = explained.structured_content["blocking"]
        assert len(blocking) == 1
        assert blocking[0]["code"] == "advice.blocked"
        assert "is not installed" in blocking[0]["message"]
        with pytest.raises(ToolError) as excinfo:
            asyncio.run(server.call_tool("run", arguments))
        assert str(excinfo.value).endswith(
            "cannot generate a runnable input: " + blocking[0]["message"]
        )

    def test_unknown_top_level_argument_raises_tool_error(
        self, silicon_cif: str
    ) -> None:
        server = create_server()

        with pytest.raises(ToolError, match="Unknown run arguments"):
            asyncio.run(
                server.call_tool(
                    "run", {"document": {"structure_content": silicon_cif}, "bogus": 1}
                )
            )

    def test_unknown_setting_raises_tool_error(
        self, real_assets, silicon_cif: str
    ) -> None:
        server = create_server()

        with pytest.raises(ToolError, match="did you mean: ecutwfc_ry"):
            asyncio.run(
                server.call_tool(
                    "run",
                    {
                        "document": {
                            "structure_content": silicon_cif,
                            "hpc": "scarf",
                            "overrides": {"ecutwf_ry": 30},
                        }
                    },
                )
            )

    def test_path_shaped_structure_content_raises_tool_error(self) -> None:
        server = create_server()

        with pytest.raises(ToolError, match="not a path"):
            asyncio.run(
                server.call_tool(
                    "inspect_structure",
                    {"document": {"structure_content": "/etc/passwd"}},
                )
            )


class TestPerStepOverrides:
    """#154 over MCP: `steps.nscf.k_grid` raised "unknown setting", dos.x
    keys were unknown, and press on an scf was dropped silently."""

    def _call(
        self, tool: str, silicon_cif: str, task: str, overrides: dict[str, Any]
    ) -> Any:
        document = {
            "structure_content": silicon_cif,
            "hpc": "scarf",
            "task": task,
            "overrides": overrides,
        }
        return asyncio.run(create_server().call_tool(tool, {"document": document}))

    def test_steps_nscf_k_grid_changes_only_the_nscf_mesh(
        self, silicon_cif: str
    ) -> None:
        default = self._call("explain", silicon_cif, "dos", {})
        result = self._call(
            "explain", silicon_cif, "dos", {"steps.nscf.k_grid": [30, 30, 30]}
        )

        assert result.is_error is False
        records = result.structured_content["records"]
        assert records["nscf_k_sampling"]["value"]["mesh"] == [30, 30, 30]
        assert (
            records["k_sampling"] == default.structured_content["records"]["k_sampling"]
        )

    def test_a_shift_keeps_the_protocol_nscf_mesh(self, silicon_cif: str) -> None:
        default = self._call("explain", silicon_cif, "dos", {})
        result = self._call("explain", silicon_cif, "dos", {"shift": [1, 1, 1]})

        nscf = result.structured_content["records"]["nscf_k_sampling"]["value"]
        protocol = default.structured_content["records"]["nscf_k_sampling"]["value"]
        assert (nscf["k_distance"], nscf["mesh"]) == (0.1, protocol["mesh"])

    def test_a_dos_x_setting_reaches_the_dos_record(
        self, silicon_fixture_table, silicon_cif: str
    ) -> None:
        result = self._call("run", silicon_cif, "dos", {"delta_e": 0.05})

        assert result.is_error is False
        dos = result.structured_content["records"]["dos"]
        assert (dos["value"]["delta_e"], dos["source"]) == (0.05, "human")

    @pytest.mark.parametrize("tool", ["explain", "run"])
    def test_press_on_an_scf_raises_tool_error(
        self, silicon_cif: str, tool: str
    ) -> None:
        with pytest.raises(ToolError) as excinfo:
            self._call(tool, silicon_cif, "scf_single_point", {"press": 10})

        assert str(excinfo.value).endswith(
            "'press' does not apply to task 'scf_single_point'; "
            "it applies to tasks vc-relax, vc-relax-phonon"
        )
