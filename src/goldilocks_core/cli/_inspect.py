"""``goldilocks inspect``: structure info only, no analysis/advisors
(v2 epic 8, #8).
"""

from __future__ import annotations

import argparse
from typing import TextIO

from goldilocks_core.cli._output import write_json
from goldilocks_core.inputs.structure import PathStructureSource, normalize_structure


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("inspect", help="Inspect a structure file.")
    parser.add_argument("structure", help="Path to the input structure file.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")


def run(args: argparse.Namespace, out: TextIO) -> None:
    inspection = normalize_structure(
        PathStructureSource(path=args.structure)
    ).inspection
    if args.json:
        write_json(out, inspection)
        return
    structure_doc = inspection["structure"]
    elements = sorted(
        {
            species["symbol"]
            for site in structure_doc["sites"]
            for species in site["species"]
        }
    )
    print(f"formula: {structure_doc['reduced_formula']}", file=out)
    print(f"elements: {', '.join(elements)}", file=out)
    print(f"sites: {structure_doc['site_count']}", file=out)
    labels = dict.fromkeys(site["label"] for site in structure_doc["sites"])
    print(f"site labels: {', '.join(labels)}", file=out)
    print(f"volume (A^3): {structure_doc['lattice']['volume_angstrom3']:.4f}", file=out)
