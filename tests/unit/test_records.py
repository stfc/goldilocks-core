from typing import Any

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.analysis import StructureAnalysisRecord
from goldilocks_core.calculation import CalculationHints, CalculationIntent
from goldilocks_core.io.structures import InMemoryStructureSource
from goldilocks_core.request import CalculationDraft, PresetSelection
from goldilocks_core.result import ComputationResult
from goldilocks_core.serialization import to_portable


def _make_analysis() -> dict[str, Any]:
    return {
        "formula": "Si1",
        "reduced_formula": "Si",
        "site_count": 1,
        "elements": ["Si"],
        "contains_transition_metals": False,
        "contains_lanthanides": False,
        "contains_actinides": False,
        "contains_heavy_elements": False,
        "magnetic_elements": [],
        "heavy_elements": [],
    }


def test_core_records_maps_requested_types_and_serializes_record_names() -> None:
    analysis = _make_analysis()
    records = {StructureAnalysisRecord: analysis}

    assert records[StructureAnalysisRecord] is analysis
    assert tuple(records) == (StructureAnalysisRecord,)
    result = ComputationResult(
        draft=CalculationDraft(
            InMemoryStructureSource(
                Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])
            )
        ),
        task="scf_single_point",
        task_revision="1",
        selection=PresetSelection("recommend"),
        records=records,
    )
    assert to_portable(result)["records"] == {
        "analysis": to_portable(analysis),
    }


def test_calculation_intent_validates_pseudo_accuracy() -> None:
    assert CalculationIntent(pseudo_accuracy="precision").pseudo_accuracy == "precision"
    with pytest.raises(ValueError, match="pseudo_accuracy"):
        CalculationIntent(pseudo_accuracy="fast")


def test_hints_serialize_explicit_grid_as_list() -> None:
    data = to_portable(CalculationHints(k_grid=(2, 2, 1)))

    assert data["k_grid"] == [2, 2, 1]


def test_calculation_intent_defaults_to_pbesol() -> None:
    assert CalculationIntent().functional == "PBEsol"
