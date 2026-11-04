"""``goldilocks magnetic-orderings``: list candidate magnetic orderings for
a structure, optionally ranked by mMACE-relaxed energy (v2, #87).

Layer 3 (CLI) of #87's three-layer design (enumerate -> optionally rank
with mMACE -> generate). Deliberately its own command, not a ``run``/
``explain`` flag: this lists candidates for a human/agent to choose among
*before* generating any input file, the same reason
``service.list_magnetic_orderings`` sits outside ``advise()``/``generate()``
entirely. This command only lists and, optionally, ranks; a listed
candidate is generated from the same structure file by its label --
``goldilocks run <structure> --set magnetic_ordering=afm-3`` (its
``--json`` ``overrides``) -- through the same magnetic step as
``magnetic_ordering=afm`` (#170). There is no dedicated ``--generate``
flag here yet since that's a UI/UX design the Workbench frontend drives
(#87 layer 4), not this listing command.
"""

from __future__ import annotations

import argparse
from typing import TextIO

from goldilocks_core.cli._common import resolve_structure
from goldilocks_core.cli._output import write_json
from goldilocks_core.service import list_magnetic_orderings, report_to_json


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "magnetic-orderings",
        help="List candidate magnetic orderings for a structure.",
    )
    parser.add_argument("structure", help="Path to the input structure file.")
    parser.add_argument(
        "--rank-with-mmace",
        action="store_true",
        help="Relax every candidate on the mMACE potential energy surface and "
        "recommend the lowest energy-per-atom one (needs the mMACE backbone "
        "installed with the default assets, or GOLDILOCKS_MACE_BACKBONE; "
        "degrades to an unranked listing, with a warning, without it).",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output.")


def run(args: argparse.Namespace, out: TextIO) -> None:
    structure = resolve_structure(args.structure)
    report = list_magnetic_orderings(structure, rank_with_mmace=args.rank_with_mmace)

    if args.json:
        write_json(out, report_to_json(report))
        return

    header = (
        f"{'label':10s} {'formula':10s} {'natoms':>6s} {'E/atom (eV)':>14s}  status"
    )
    print(header, file=out)
    for candidate in report.candidates:
        energy = (
            f"{candidate.energy_per_atom_ev:14.6f}"
            if candidate.energy_per_atom_ev is not None
            else " " * 14
        )
        marker = " *" if candidate.is_recommended else ""
        status = candidate.status or ("-" if not report.ranked else "")
        print(
            f"{candidate.label:10s} "
            f"{candidate.structure.composition.reduced_formula:10s} "
            f"{candidate.natoms:6d} {energy}  {status}{marker}",
            file=out,
        )
    for warning in report.warnings:
        print(f"warning: {warning.message}", file=out)
