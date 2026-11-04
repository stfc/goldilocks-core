"""Wire-level request/response contracts shared by HTTP and MCP (v2
epic 8, #8).

**`structure_content`, never `structure_path`.** The agent-design doc's
own corrected rule (goldilocks-agent-design.md S9.1, "but 'pass path'
has two boundaries") -- confirmed with the user for this epic: the
browser-to-agent-server boundary passes a path, but the agent-to-core
boundary passes content, matching core's own pitfall list item D3
("remote interfaces do not accept local paths"). ``InlineStructureDocument``
below is the same shape v1's ``server/documents.py`` already enforced
(``InlineStructureSource``, path-shaped input explicitly rejected) --
this rule did not change in v2, only the CLI (which *does* read local
paths, being a local process, not a remote transport) needed the
opposite rule spelled out.

**Not a reflective ``_serialized_model``-style projection of internal
dataclasses**, unlike v1's ``server/documents.py``. That reflection
mechanism existed to mirror v1's `contracts.py`-centralized shapes
automatically; v2 deliberately has no such central hub
(``resolution.py``'s own docstring) and per-domain contracts are
already pydantic (``inputs/overrides.py``'s ``HumanInput`` family,
``resolution.ResolvedField``) -- so responses here just reuse those
directly (``ResolvedField.from_state``) rather than re-deriving a
parallel schema from scratch.

**`overrides: dict[str, Any]`, not a typed model.** The same reasoning
``set_overrides.py`` documents: every settable key is reflected from
``capabilities.bindings()`` at request-validation time, not hand-listed
in a schema -- a request body's ``overrides`` object is exactly the
flat ``{key: value}`` shape ``set_overrides.build_overrides`` already
accepts, JSON-typed instead of CLI-string-typed (no ``coerce_cli_value``
step needed transport-side).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from goldilocks_core.types import CalcTask

_STRICT = ConfigDict(extra="forbid")


class InlineStructureDocument(BaseModel):
    """Every scientific endpoint's structure input. Rejects anything
    path-shaped outright, rather than relying on callers never sending
    one -- the same guarantee v1's ``InlineStructureDocument`` gave via
    its own ``_inline_structure`` validator."""

    model_config = _STRICT

    structure_content: str
    structure_name: str = "structure"
    structure_format: Literal["cif", "poscar"] | None = None

    @field_validator("structure_content")
    @classmethod
    def _reject_path_shaped_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("structure_content must not be empty")
        if "\n" not in stripped and len(stripped) < 256:
            # A bare one-line, no-newline value is far more likely to be
            # a filesystem path a caller passed by mistake than real CIF/
            # POSCAR text, which always spans multiple lines.
            raise ValueError(
                "structure_content must be file text (e.g. a CIF), not a "
                "path -- remote transports do not accept local paths"
            )
        return value


class ComputeRequestDocument(InlineStructureDocument):
    """Shared by ``/explain`` and ``/run`` (and MCP's ``explain``/``run``
    tools) -- one request shape, per this epic's own "one shared
    request-validation path" scope item.

    ``task: CalcTask`` (v2 epic 9, #9, #28), not a bare ``str``: an
    unknown task must be a pydantic validation error at the transport
    boundary, the same "clear operator error, not a silent fallback"
    contract an unknown ``--set`` key or hpc profile already gets --
    before this, the field parsed but was never read anywhere, so any
    value (typo or not) silently ran the scf-only pipeline."""

    code: str = "quantum_espresso"
    task: CalcTask = "scf_single_point"
    hpc: str | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)
    fetch_missing: bool = False


class RunRequestDocument(ComputeRequestDocument):
    respond_with: Literal["json", "archive"] = "json"


class MagneticOrderingsRequestDocument(InlineStructureDocument):
    """Shared by ``/magnetic-orderings`` and MCP's ``magnetic_orderings``
    tool (#87). Its own document, not ``ComputeRequestDocument``: this
    lists candidates independently of any code/task/hpc/overrides choice,
    the same reason ``service.list_magnetic_orderings`` sits outside
    ``advise()``/``generate()`` entirely."""

    rank_with_mmace: bool = False
