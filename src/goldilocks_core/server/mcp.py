"""MCP stdio transport over the v2 ``service``/``capabilities``/
``set_overrides`` stack (v2 epic 8, #8).

Every tool calls ``server/_handlers.py``'s free functions -- the exact
same path ``server/http.py`` calls -- so validation/dispatch can never
drift between the two transports (this epic's own "one shared
request-validation path" scope item).

Four tools, not v1's three: ``capabilities``, ``inspect_structure``,
``explain`` (new: the tri-state "diagnosis always available" half of
the promise, with no v1 precedent at the transport layer), and ``run``
(replaces v1's ``compute``). ``run`` never returns raw bundle bytes --
only the file list, every decision, and ``warnings`` -- matching MCP's
own JSON/text idiom; fetching actual file contents has no MCP-shaped
answer yet (out of scope, tracked with web/agent integration, not this
epic's ``/run archive`` HTTP route).

Fixes issue #8's own evidence #3: v1 hardcoded ``version="0.1.0"``,
disagreeing with ``capabilities.py``'s real
``importlib.metadata.version("goldilocks-core")``. Now the same call.
"""

from __future__ import annotations

import asyncio
from importlib.metadata import version as package_version
from typing import Any

from goldilocks_core.capabilities import capabilities as build_capabilities
from goldilocks_core.failures import ExpectedFailure
from goldilocks_core.server import _handlers
from goldilocks_core.server.documents import (
    ComputeRequestDocument,
    InlineStructureDocument,
    MagneticOrderingsRequestDocument,
)

try:
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError as error:
    raise ImportError(
        "The MCP transport requires goldilocks-core[mcp]. "
        "Install it with `uv sync --extra mcp`."
    ) from error

__all__ = ["create_server", "serve"]


class _StrictMCPServer(MCPServer):
    """``additionalProperties: false`` on every tool's schema, and every
    call re-checked against that same schema -- reused unchanged from
    v1 (issue #8's own "v1 code leaned on as-is" section): the one hard
    gate at the LLM/core boundary."""

    async def list_tools(self) -> list[Any]:
        tools = await super().list_tools()
        for tool in tools:
            tool.input_schema["additionalProperties"] = False
        return tools

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Any | None = None,
    ) -> Any:
        tools = await self.list_tools()
        tool = next((candidate for candidate in tools if candidate.name == name), None)
        if tool is not None:
            allowed = set(tool.input_schema.get("properties", {}))
            unknown = sorted(set(arguments) - allowed)
            if unknown:
                raise ToolError(f"Unknown {name} arguments: {', '.join(unknown)}")
        return await super().call_tool(name, arguments, context)


def create_server(*, name: str = "goldilocks-core") -> MCPServer:
    server = _StrictMCPServer(
        name=name,
        version=package_version("goldilocks-core"),
        instructions=(
            "Inspect structures and generate Goldilocks Core DFT inputs. "
            "structure_content must be file text (e.g. CIF), never a path."
        ),
    )

    @server.tool(
        description="Describe available codes, tasks, settings, facts, and assets."
    )
    async def capabilities() -> dict[str, Any]:
        return await asyncio.to_thread(build_capabilities)

    @server.tool(description="Normalize and inspect an inline structure.")
    async def inspect_structure(document: InlineStructureDocument) -> dict[str, Any]:
        return await _call(_handlers.inspect, document)

    @server.tool(
        description=(
            "List candidate magnetic orderings for a structure (plain "
            "ferromagnetic, plus every antiferromagnetic candidate "
            "enumlib finds). rank_with_mmace=True additionally relaxes each "
            "candidate on the mMACE potential energy surface and marks the "
            "lowest energy-per-atom one as recommended; degrades to an "
            "unranked listing, with a warning, if that is not configured on "
            "the server. Lists candidates only -- does not generate any "
            "input file: generate one by calling run or explain on the same "
            "structure with the candidate's overrides "
            "({'magnetic_ordering': '<label>'})."
        )
    )
    async def magnetic_orderings(
        document: MagneticOrderingsRequestDocument,
    ) -> dict[str, Any]:
        return await _call(_handlers.magnetic_orderings, document)

    @server.tool(
        description=(
            "Run analysis, advisors and run's checks, without generating any "
            "files. Returns every decision (with its source), a warnings "
            "array the caller must relay verbatim (each warning names the "
            "decision it came from in 'record'), a blocking array of the "
            "findings run would refuse to generate an input for (empty when "
            "those checks pass: each has a code, the settings it concerns in "
            "'fields', a message to relay, and 'remedies', override patches "
            "that each resolve it, where null clears that override), and a "
            "layout naming each "
            "decision's tier (analysis: the structure alone; system: shared "
            "by every step) or step. task='dos' explains all three "
            "of the density-of-states task's steps (scf, nscf, dos.x); "
            "its nscf-step decisions are returned under nscf_-prefixed keys. "
            "task='band' explains scf, the pw.x bands step along the written "
            "cell's high-symmetry path ('k_path'), and bands.x; its other "
            "bands-step decisions are returned under bands_-prefixed keys. "
            "task='relax'/'vc-relax' explains one pw.x step with ionic (and, "
            "for vc-relax, cell) relaxation parameters resolved under the "
            "'relax' key. task='phonon'/'relax-phonon'/'vc-relax-phonon' "
            "explains a first pw.x step (scf, relax or vc-relax, with its "
            "'fft_grid' decision and, for a relaxation, 'relax'), d3hess.x for "
            "DFT-D3, ph.x on a q-point mesh ('q_sampling' and 'phonon'), q2r.x "
            "('q2r'), matdyn.x for the phonon DOS ('phonon_dos') and matdyn.x "
            "along the band task's path ('k_path'). An overrides key reaches "
            "every step of the task it applies to; 'steps.<step>.<key>' "
            "(steps: scf; relax; vc-relax; scf, nscf, dos; scf, bands, "
            "bands_x; scf, ph, q2r, phonon_dos, dispersion; relax, ph, q2r, "
            "phonon_dos, dispersion; vc-relax, ph, q2r, phonon_dos, "
            "dispersion) sets one step only, and a key no step of the task "
            "reads is an error."
        )
    )
    async def explain(document: ComputeRequestDocument) -> dict[str, Any]:
        return await _call(_handlers.explain, document)

    @server.tool(
        description=(
            "Generate a runnable input. Returns the published file list, "
            "every decision with explain's layout, and a warnings array the "
            "caller must relay verbatim -- fails with explain's findings, "
            "each followed by its remedy overrides, if run's checks refuse "
            "the request. task='dos' generates all three steps "
            "(scf, nscf, dos.x) sharing one submission script, not just a "
            "single scf. task='band' generates scf.in, bands.in and a bands.x "
            "input (one per spin channel of a collinear run), sharing one "
            "submission script. task='relax'/'vc-relax' generates one pw.x "
            "input with calculation='relax'/'vc-relax' set accordingly. "
            "task='phonon'/'relax-phonon'/'vc-relax-phonon' generates scf.in, "
            "relax.in or vc-relax.in, d3hess.in for DFT-D3, ph.in, q2r.in, "
            "phonon_dos.in and dispersion.in, sharing one submission script "
            "whose job timer stops pw.x or ph.x cleanly near the walltime and "
            "whose GOLDILOCKS_FROM_STEP variable resumes it from a later step. "
            "Overrides are routed to the task's steps as in explain."
        )
    )
    async def run(document: ComputeRequestDocument) -> dict[str, Any]:
        summary, _bundle_input = await _call(_handlers.run, document)
        return summary

    return server


async def _call(handler: Any, document: Any) -> Any:
    try:
        return await asyncio.to_thread(handler, document)
    except ExpectedFailure as error:
        raise ToolError(str(error)) from error


def serve() -> None:
    create_server().run("stdio")
