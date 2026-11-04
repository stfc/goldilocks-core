"""Shared plumbing for the v2 CLI commands (v2 epic 8, #8).

Split out of ``core.py`` (and ``core.py`` itself split into one file per
command below) for the same reason ``service/`` is a package: this
project's own import-surface ceiling (``scripts/check_complexity.py``)
sets ``cli.core`` a *tighter* limit (8 origins/16 symbols) than the
default, precisely so the CLI stays a thin dispatcher and real logic
lives in dedicated modules -- v1's own ``cli/core.py`` already sat right
at that ceiling before this rewrite touched it.
"""

from __future__ import annotations

import argparse
import json
import shlex
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from pymatgen.core import Structure

from goldilocks_core.checks import Finding
from goldilocks_core.inputs.hpc import HpcProfile, resolve_hpc_profile
from goldilocks_core.inputs.structure import (
    PathStructureSource,
    StructureSourceDocument,
    normalize_structure,
)
from goldilocks_core.resolution import Blocked, FieldState, Resolved, records_document
from goldilocks_core.serialization import to_portable
from goldilocks_core.service import RunOverrides
from goldilocks_core.set_overrides import (
    build_overrides,
    coerce_cli_assignments,
    config_assignments,
    parse_set_flags,
)
from goldilocks_core.types import CalcTask


def add_run_arguments(parser: argparse.ArgumentParser) -> None:
    """The 7 flags ``run``/``explain`` share (design doc S6: "``run``
    only has 7 flags")."""
    parser.add_argument("structure", help="Path to the input structure file.")
    parser.add_argument(
        "--code", default="quantum_espresso", help="Code to generate input for."
    )
    parser.add_argument(
        "--task",
        default="scf_single_point",
        choices=get_args(CalcTask),
        help="Task to run.",
    )
    parser.add_argument(
        "--hpc",
        help="HPC profile name; required unless exactly one profile is installed.",
    )
    parser.add_argument(
        "--set",
        dest="set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help=(
            "Override one setting (repeatable); steps.<step>.KEY=VALUE sets "
            "one step of the task only. See 'goldilocks settings'."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        help=(
            "TOML file of KEY=VALUE overrides, same as --set; a [steps.<step>] "
            "table sets one step of the task."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output.")


def add_fetch_missing_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--fetch-missing",
        action="store_true",
        help="Install a missing pseudopotential table instead of failing (P8: "
        "never a silent download).",
    )


@dataclass(frozen=True, slots=True)
class Request:
    """One ``run``/``explain`` invocation, resolved: the structure read
    from its path and that file's identity (``NormalizedStructure.source``),
    the HPC profile, the overrides as submitted (``assignments``: ``--config``
    then ``--set``, typed) and those overrides routed for ``--task``."""

    structure: Structure
    source: StructureSourceDocument
    hpc: HpcProfile
    assignments: dict[str, object]
    overrides: RunOverrides


def resolve_structure(path: str) -> Structure:
    return normalize_structure(PathStructureSource(path=path)).structure


def resolve_request(args: argparse.Namespace) -> Request:
    """The structure, then ``--hpc``, then the overrides: each raises its
    own operator error, in that order."""
    normalized = normalize_structure(PathStructureSource(path=args.structure))
    hpc = resolve_hpc_profile(args.hpc, field="--hpc")
    assignments = _assignments(args)
    return Request(
        structure=normalized.structure,
        source=normalized.source,
        hpc=hpc,
        assignments=assignments,
        overrides=build_overrides(assignments, task=args.task),
    )


def _assignments(args: argparse.Namespace) -> dict[str, object]:
    """``--config`` then ``--set`` (which wins), typed."""
    assignments: dict[str, object] = {}
    if args.config is not None:
        with args.config.open("rb") as source:
            assignments.update(config_assignments(tomllib.load(source)))
    assignments.update(coerce_cli_assignments(parse_set_flags(args.set)))
    return assignments


def format_field_state(state: FieldState[object]) -> str:
    """Tri-state-aware rendering -- directly fixes this epic's evidence
    #2 (v1's print layer collapsed "not computed", "not applicable",
    and "genuinely off" into one falsy-string fallback like
    ``'unresolved'``/``'none'``/``'any'``). A resolved value prints as
    published (``serialization.to_portable``)."""
    if isinstance(state, Resolved):
        return f"{to_portable(state.value)!r} (source={state.source})"
    if isinstance(state, Blocked):
        return f"blocked by: {state.root_cause()}"
    return f"unavailable: {state.reason}"


def notice_lines(warnings: list[dict[str, object]]) -> list[str]:
    """The ``notice:`` lines of ``explain``'s text report: the warnings no
    record carries, which the records it prints cannot show. Those are the
    request's routing notices (``record`` ``overrides``, #154): a setting
    given without a step that reached several steps."""
    return [
        f"notice: {warning['message']}"
        for warning in warnings
        if warning["record"] == "overrides"
    ]


def records_to_json(records: dict[str, FieldState[object]]) -> dict[str, object]:
    """The ``records`` object of ``explain``/``run --json``:
    ``resolution.records_document``, the projection HTTP, MCP and
    ``goldilocks.json`` use, reached through this module so ``cli._run``
    stays within its import ceiling (``scripts/check_complexity.py``)."""
    return records_document(records)


def finding_lines(findings: Iterable[Finding]) -> list[str]:
    """``explain``'s and ``run``'s text for the gate's findings (#151): a
    ``blocked:`` line per finding, each followed by one indented ``try:``
    line per remedy, giving its ``--set`` flags. ``--set`` cannot clear a
    key, so a key the remedy clears reads ``remove --set <key>``."""
    lines = []
    for finding in findings:
        lines.append(f"blocked: {finding.message}")
        lines += [f"  try: {_remedy_flags(remedy)}" for remedy in finding.remedies]
    return lines


def _remedy_flags(remedy: Mapping[str, object]) -> str:
    sets = [
        "--set " + shlex.quote(f"{key}={_cli_value(value)}")
        for key, value in remedy.items()
        if value is not None
    ]
    cleared = [f"--set {key}" for key, value in remedy.items() if value is None]
    parts = [" ".join(sets)] if sets else []
    if cleared:
        parts.append("remove " + " and ".join(cleared))
    return ", ".join(parts)


def _cli_value(value: object) -> str:
    """``value`` as ``--set`` reads it back: a string as it is, anything
    else as JSON (``true``, ``4``, ``[1, 1, 1]``)."""
    return value if isinstance(value, str) else json.dumps(value)
