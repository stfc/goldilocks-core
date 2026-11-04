"""Tests for goldilocks_core.serialization.to_portable: the one projection
of a record value for publication (#152)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import numpy as np
from pymatgen.core import Lattice, Structure

from goldilocks_core.assets.pseudopotentials.upf import PseudoMetadata
from goldilocks_core.resolution import Warning
from goldilocks_core.serialization import Portable, to_portable


def _silicon_metadata() -> PseudoMetadata:
    return PseudoMetadata(
        filepath="/home/someone/.local/share/goldilocks/assets/pseudos/Si.upf",
        filename="Si.upf",
        header_format="upf2",
        element="Si",
        z_valence=4.0,
        pseudo_info={"citation": "a citation", "licence_text": "a licence"},
    )


def _rock_salt() -> Structure:
    return Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(5.64), ["Na", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    )


@dataclass(frozen=True, slots=True)
class _Cell:
    structure: Structure
    host_path: Annotated[str, Portable()]
    notices: tuple[Warning, ...] = ()


def test_drops_portable_fields_of_dataclasses_nested_in_tuples_and_dicts() -> None:
    """A dataclass anywhere in a record loses the fields its type marks
    ``Portable()`` (host paths, licence text), without a projection
    registered for that type."""
    projected = to_portable(
        {
            "pseudopotentials": (_silicon_metadata(),),
            "by_element": {
                "Si": _Cell(structure=_rock_salt(), host_path="/scratch/run")
            },
        }
    )

    (metadata,) = projected["pseudopotentials"]
    assert "filepath" not in metadata
    assert "pseudo_info" not in metadata
    assert (metadata["filename"], metadata["z_valence"]) == ("Si.upf", 4.0)
    assert "host_path" not in projected["by_element"]["Si"]


def test_projects_a_structure_inside_a_record_to_its_formula_and_atom_count() -> None:
    """D4: any pymatgen Structure in a published record, at any depth, is
    its formula and atom count (the rendered cell of ``records.magnetic``,
    #128), never the full structure document."""
    projected = to_portable((_Cell(structure=_rock_salt(), host_path="/tmp"),))

    assert projected == [{"structure": {"formula": "Na4 Cl4", "nat": 8}, "notices": []}]


def test_projects_pydantic_models_numpy_values_and_paths_to_json() -> None:
    notice = Warning(
        code="job.walltime_defaulted",
        level="warning",
        category="job",
        message="walltime not specified.",
    )

    projected = to_portable(
        {
            "notices": (notice,),
            "rotation": np.eye(2),
            "count": np.int64(3),
            "pseudo_dir": Path("pseudo"),
        }
    )

    assert projected == {
        "notices": [
            {
                "code": "job.walltime_defaulted",
                "level": "warning",
                "category": "job",
                "message": "walltime not specified.",
            }
        ],
        "rotation": [[1.0, 0.0], [0.0, 1.0]],
        "count": 3,
        "pseudo_dir": "pseudo",
    }
    assert json.loads(json.dumps(projected, allow_nan=False)) == projected
