"""CLI entry point for k-mesh recommendation."""

from __future__ import annotations

import argparse

from goldilocks_core.advisors import advise_kpoints
from goldilocks_core.contracts import ModelSpec
from goldilocks_core.io.structures import load_structure


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for k-mesh recommendation."""
    parser = argparse.ArgumentParser(
        prog="goldilocks",
        description="Recommend a k-mesh for a structure.",
    )
    parser.add_argument(
        "structure",
        help="Path to the input structure file.",
    )
    parser.add_argument(
        "--model",
        required=True,
        help="The model to use for recommendation.",
    )
    return parser


def main() -> None:
    """Run the k-mesh recommendation CLI."""
    parser = build_parser()
    args = parser.parse_args()

    structure = load_structure(args.structure)
    spec = ModelSpec(
        name="cli-local-model",
        version="unknown",
        model_type="random_forest",
        target="k_index",
        feature_set="cslr",
        source="local",
        location=args.model,
        revision=None,
    )

    advice = advise_kpoints(structure, spec)

    print(f"recommended mesh: {advice.grid}")


if __name__ == "__main__":
    main()
