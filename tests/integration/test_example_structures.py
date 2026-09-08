from __future__ import annotations

import pytest

from goldilocks_core import (
    CalculationDraft,
    CalculationHints,
    ComputeRequest,
    PathStructureSource,
    PresetSelection,
    compute,
)
from goldilocks_core.contracts import (
    KPointSelection,
    ParameterAdvice,
    StructureAnalysisRecord,
)
from goldilocks_core.examples import available_structures, structure, structures_path


def _recommend(name: str):
    return compute(
        ComputeRequest(
            draft=CalculationDraft(
                structure=PathStructureSource(structure(name)),
                hints=CalculationHints(k_grid=(4, 4, 4)),
                pseudo_metadata=(),
            ),
            selection=PresetSelection("recommend"),
        )
    )


def test_bundled_structures_are_installed_with_the_package() -> None:
    assert structures_path().is_dir()
    assert available_structures() == ("Fe_bcc.cif", "Pt_fcc.cif", "Si.cif")


def test_structure_rejects_an_unknown_name() -> None:
    with pytest.raises(FileNotFoundError) as error:
        structure("Unobtainium.cif")

    assert "Si.cif" in str(error.value)


@pytest.mark.parametrize("name", ["Si.cif", "Fe_bcc.cif", "Pt_fcc.cif"])
def test_every_bundled_structure_runs_through_the_pipeline(name: str) -> None:
    result = _recommend(name)

    assert result.records[StructureAnalysisRecord].reduced_formula
    assert result.records[KPointSelection].grid == (4, 4, 4)


def test_bundled_structures_exercise_distinct_advice_branches() -> None:
    silicon = _recommend("Si.cif")
    iron = _recommend("Fe_bcc.cif")
    platinum = _recommend("Pt_fcc.cif")

    silicon_analysis = silicon.records[StructureAnalysisRecord]
    silicon_advice = silicon.records[ParameterAdvice]
    assert silicon_advice.magnetism.spin_polarized is False
    assert silicon_advice.spin_orbit.consider is False
    assert silicon_analysis.heavy_elements == ()

    iron_analysis = iron.records[StructureAnalysisRecord]
    iron_advice = iron.records[ParameterAdvice]
    assert iron_analysis.electronic_character == "likely_metal"
    assert iron_advice.magnetism.spin_polarized is True
    assert iron_advice.smearing.smearing_type == "cold"

    platinum_analysis = platinum.records[StructureAnalysisRecord]
    platinum_advice = platinum.records[ParameterAdvice]
    assert platinum_analysis.heavy_elements == ("Pt",)
    assert platinum_advice.spin_orbit.consider is True
