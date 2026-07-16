from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

import numpy as np
import pytest

from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    ConvergenceAdvice,
    CoreResult,
    GeneratedFile,
    KMeshEntry,
    KPointAdvice,
    KPointSelection,
    MagnetismAdvice,
    ParameterAdvice,
    Provenance,
    PseudopotentialAdvice,
    PseudopotentialSelection,
    SelectionRecord,
    SmearingAdvice,
    SpinOrbitAdvice,
    StructureAnalysisRecord,
    StructureFeatureVector,
    VdwAdvice,
    to_jsonable,
)


def _provenance() -> Provenance:
    return Provenance(source="default", reason="test")


def _kmesh_entry(mesh: object) -> KMeshEntry:
    return KMeshEntry(
        k_index=1,
        mesh=mesh,
        k_distance_interval=(0.1, 0.2),
        k_line_density_interval=None,
        k_pra=1.0,
        n_reduced_kpoints=1,
    )


def _kpoint_advice_with_grid(grid: object) -> KPointAdvice:
    return KPointAdvice(
        spacing=None,
        explicit_grid=grid,
        mesh_type="monkhorst-pack",
        provenance=_provenance(),
    )


def _kpoint_selection(*, grid: object = (2, 2, 2), shift: object = (0, 0, 0)):
    return KPointSelection(
        grid=grid,
        shift=shift,
        mesh_type="monkhorst-pack",
        provenance=_provenance(),
    )


def _pseudopotential_selection(**overrides) -> PseudopotentialSelection:
    values = {
        "element": "Si",
        "filename": "Si.UPF",
        "filepath": "/pseudo/Si.UPF",
        "ecutwfc_ry": 30.0,
        "ecutrho_ry": 120.0,
        "provenance": _provenance(),
    }
    values.update(overrides)
    return PseudopotentialSelection(**values)


def _core_result(generated_files: tuple[GeneratedFile, ...]) -> CoreResult:
    provenance = _provenance()
    analysis = StructureAnalysisRecord(
        formula="Si1",
        reduced_formula="Si",
        site_count=1,
        elements=("Si",),
        contains_transition_metals=False,
        contains_lanthanides=False,
        contains_actinides=False,
        contains_heavy_elements=False,
        magnetic_elements=(),
        heavy_elements=(),
    )
    advice = ParameterAdvice(
        k_points=KPointAdvice(
            spacing=0.2,
            explicit_grid=None,
            mesh_type="monkhorst-pack",
            provenance=provenance,
        ),
        smearing=SmearingAdvice(
            smearing_type="fixed",
            width_ry=None,
            provenance=provenance,
        ),
        magnetism=MagnetismAdvice(
            spin_polarized=False,
            magnetic_elements=(),
            provenance=provenance,
        ),
        spin_orbit=SpinOrbitAdvice(
            enabled=False,
            consider=False,
            heavy_elements=(),
            provenance=provenance,
        ),
        pseudopotentials=PseudopotentialAdvice(
            functional="PBE",
            pseudo_mode="efficiency",
            pseudo_type=None,
            relativistic_mode="scalar",
            provenance=provenance,
        ),
        convergence=ConvergenceAdvice(conv_thr=1e-6, provenance=provenance),
        vdw=VdwAdvice(use_vdw=False, method=None, provenance=provenance),
    )
    selection = SelectionRecord(
        k_points=_kpoint_selection(),
        pseudopotentials=(),
    )
    return CoreResult(
        intent=CalculationIntent(),
        analysis=analysis,
        advice=advice,
        selection=selection,
        generated_files=generated_files,
    )


@pytest.mark.parametrize("value", [0.0, -0.1, np.nan, np.inf, -np.inf])
@pytest.mark.parametrize(
    ("record_factory", "field_name"),
    [
        pytest.param(
            lambda value: CalculationHints(k_spacing=value),
            "CalculationHints.k_spacing",
            id="hint",
        ),
        pytest.param(
            lambda value: KPointAdvice(
                spacing=value,
                explicit_grid=None,
                mesh_type="monkhorst-pack",
                provenance=_provenance(),
            ),
            "KPointAdvice.spacing",
            id="advice",
        ),
    ],
)
def test_k_spacing_must_be_finite_and_positive(
    value: float,
    record_factory: Callable[[float], object],
    field_name: str,
) -> None:
    with pytest.raises(ValueError, match=field_name):
        record_factory(value)


@pytest.mark.parametrize(
    "grid",
    [
        (1, 1),
        (1, 1, 1, 1),
        (0, 1, 1),
        (-1, 1, 1),
        (1.5, 1, 1),
        (True, 1, 1),
    ],
)
@pytest.mark.parametrize(
    ("record_factory", "field_name"),
    [
        pytest.param(
            lambda grid: CalculationHints(k_grid=grid),
            "CalculationHints.k_grid",
            id="hint",
        ),
        pytest.param(
            _kpoint_advice_with_grid,
            "KPointAdvice.explicit_grid",
            id="advice",
        ),
        pytest.param(
            lambda grid: _kpoint_selection(grid=grid),
            "KPointSelection.grid",
            id="selection",
        ),
        pytest.param(_kmesh_entry, "KMeshEntry.mesh", id="entry"),
    ],
)
def test_kpoint_grids_require_three_positive_integers(
    grid: object,
    record_factory: Callable[[object], object],
    field_name: str,
) -> None:
    with pytest.raises(ValueError, match=field_name):
        record_factory(grid)


@pytest.mark.parametrize(
    "shift",
    [(0, 0), (0, 0, 0, 0), (-1, 0, 0), (2, 0, 0), (0.5, 0, 0), (True, 0, 0)],
)
def test_kpoint_shifts_require_three_zero_or_one_flags(shift: object) -> None:
    with pytest.raises(ValueError, match="KPointSelection.shift"):
        _kpoint_selection(shift=shift)


def test_kpoint_lists_are_normalized_to_immutable_tuples() -> None:
    """Accept list inputs without retaining aliases to mutable grid state."""
    hint_grid = [2, 2, 2]
    advice_grid = [3, 3, 3]
    entry_mesh = [4, 4, 4]
    selection_grid = [5, 5, 5]
    selection_shift = [0, 0, 0]

    hints = CalculationHints(k_grid=hint_grid)
    advice = _kpoint_advice_with_grid(advice_grid)
    entry = _kmesh_entry(entry_mesh)
    selection = _kpoint_selection(grid=selection_grid, shift=selection_shift)

    hint_grid[0] = 0
    advice_grid[0] = 0
    entry_mesh[0] = 0
    selection_grid[0] = 0
    selection_shift[0] = 2

    assert hints.k_grid == (2, 2, 2)
    assert advice.explicit_grid == (3, 3, 3)
    assert entry.mesh == (4, 4, 4)
    assert selection.grid == (5, 5, 5)
    assert selection.shift == (0, 0, 0)
    with pytest.raises(TypeError):
        selection.grid[0] = 1


@pytest.mark.parametrize(
    "field_name",
    ["spin_polarized", "spin_orbit_coupling", "use_vdw"],
)
def test_calculation_hint_controls_require_actual_booleans(field_name: str) -> None:
    """Reject truthy values before they can become advice controls."""
    with pytest.raises(ValueError, match=f"CalculationHints.{field_name}"):
        CalculationHints(**{field_name: 1})


@pytest.mark.parametrize(
    ("record_factory", "field_name"),
    [
        pytest.param(
            lambda value: MagnetismAdvice(
                spin_polarized=value,
                magnetic_elements=(),
                provenance=_provenance(),
            ),
            "MagnetismAdvice.spin_polarized",
            id="magnetism",
        ),
        pytest.param(
            lambda value: SpinOrbitAdvice(
                enabled=value,
                consider=False,
                heavy_elements=(),
                provenance=_provenance(),
            ),
            "SpinOrbitAdvice.enabled",
            id="spin-orbit-enabled",
        ),
        pytest.param(
            lambda value: SpinOrbitAdvice(
                enabled=False,
                consider=value,
                heavy_elements=(),
                provenance=_provenance(),
            ),
            "SpinOrbitAdvice.consider",
            id="spin-orbit-consider",
        ),
        pytest.param(
            lambda value: VdwAdvice(
                use_vdw=value,
                method=None,
                provenance=_provenance(),
            ),
            "VdwAdvice.use_vdw",
            id="vdw",
        ),
    ],
)
def test_advice_controls_require_actual_booleans(
    record_factory: Callable[[object], object],
    field_name: str,
) -> None:
    """Reject truthy values from custom Advice backends."""
    with pytest.raises(ValueError, match=field_name):
        record_factory(1)


@pytest.mark.parametrize("confidence", [-0.1, 1.1, np.nan, np.inf, -np.inf, True])
def test_provenance_confidence_must_be_finite_and_bounded(confidence: object) -> None:
    with pytest.raises(ValueError, match="Provenance.confidence"):
        Provenance(source="model", reason="test", confidence=confidence)


@pytest.mark.parametrize("confidence", [0.0, 0.5, 1.0])
def test_provenance_confidence_accepts_closed_interval(confidence: float) -> None:
    assert (
        Provenance(source="model", reason="test", confidence=confidence).confidence
        == confidence
    )


def test_provenance_details_are_normalized_to_json_values() -> None:
    provenance = Provenance(
        source="model",
        reason="test",
        details={"versions": ("1", "2"), "value": np.float64(0.5)},
    )

    assert provenance.details == {"versions": ["1", "2"], "value": 0.5}


def test_provenance_details_reject_non_finite_numbers() -> None:
    with pytest.raises(ValueError, match="JSON numbers must be finite"):
        Provenance(source="model", reason="test", details={"value": np.inf})


@pytest.mark.parametrize(
    ("smearing_type", "width"),
    [
        (None, 0.01),
        ("fixed", 0.01),
        ("cold", None),
        ("cold", 0.0),
        ("cold", -0.01),
        ("cold", np.nan),
        ("cold", np.inf),
        ("", None),
    ],
)
@pytest.mark.parametrize(
    ("record_factory", "field_name"),
    [
        pytest.param(
            lambda smearing_type, width: CalculationHints(
                smearing_type=smearing_type,
                smearing_width_ry=width,
            ),
            "CalculationHints",
            id="hint",
        ),
        pytest.param(
            lambda smearing_type, width: SmearingAdvice(
                smearing_type=smearing_type,
                width_ry=width,
                provenance=_provenance(),
            ),
            "SmearingAdvice",
            id="advice",
        ),
    ],
)
def test_smearing_type_and_width_must_be_coherent(
    smearing_type: str | None,
    width: float | None,
    record_factory: Callable[[str | None, float | None], object],
    field_name: str,
) -> None:
    with pytest.raises(ValueError, match=field_name):
        record_factory(smearing_type, width)


@pytest.mark.parametrize(
    ("smearing_type", "width"),
    [(None, None), ("fixed", None), ("cold", 0.01)],
)
def test_smearing_accepts_fixed_or_positive_width_settings(
    smearing_type: str | None,
    width: float | None,
) -> None:
    SmearingAdvice(
        smearing_type=smearing_type,
        width_ry=width,
        provenance=_provenance(),
    )


@pytest.mark.parametrize(
    ("use_vdw", "method", "message"),
    [
        (True, None, "VdwAdvice.method is required"),
        (False, "d3", "VdwAdvice.method must be None"),
        (True, "unknown", "VdwAdvice.method must be one of"),
        ("yes", "d3", "VdwAdvice.use_vdw must be a boolean"),
    ],
)
def test_vdw_use_and_method_must_be_coherent(
    use_vdw: object,
    method: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        VdwAdvice(use_vdw=use_vdw, method=method, provenance=_provenance())


def test_vdw_hint_method_is_incompatible_with_explicitly_disabled_vdw() -> None:
    """Reject a method that an explicit off hint would otherwise ignore."""
    with pytest.raises(ValueError, match="vdw_method must be None"):
        CalculationHints(use_vdw=False, vdw_method="d3")


@pytest.mark.parametrize("field_name", ["ecutwfc_ry", "ecutrho_ry"])
@pytest.mark.parametrize("value", [0.0, -1.0, np.nan, np.inf, -np.inf])
def test_pseudopotential_cutoffs_must_be_finite_and_positive(
    field_name: str,
    value: float,
) -> None:
    with pytest.raises(ValueError, match=f"PseudopotentialSelection.{field_name}"):
        _pseudopotential_selection(**{field_name: value})


@pytest.mark.parametrize(
    ("overrides", "field_name"),
    [
        ({"conv_thr": np.nan}, "ConvergenceAdvice.conv_thr"),
        ({"conv_thr": 0.0}, "ConvergenceAdvice.conv_thr"),
        ({"mixing_beta": np.inf}, "ConvergenceAdvice.mixing_beta"),
        ({"mixing_beta": -0.1}, "ConvergenceAdvice.mixing_beta"),
        ({"electron_maxstep": 0}, "ConvergenceAdvice.electron_maxstep"),
        ({"electron_maxstep": 1.5}, "ConvergenceAdvice.electron_maxstep"),
    ],
)
def test_convergence_controls_validate_at_advice_construction(
    overrides: dict[str, object],
    field_name: str,
) -> None:
    values = {"conv_thr": 1e-6, "provenance": _provenance()}
    values.update(overrides)
    with pytest.raises(ValueError, match=field_name):
        ConvergenceAdvice(**values)


@pytest.mark.parametrize(
    "path",
    ["", "   ", ".", "/tmp/qe.in", "../qe.in", "inputs/../qe.in", "C:\\qe.in"],
)
def test_generated_paths_must_be_nonempty_relative_and_nontraversing(
    path: str,
) -> None:
    with pytest.raises(ValueError, match="GeneratedFile.path"):
        GeneratedFile(path=path, content="input")


@pytest.mark.parametrize(
    ("first", "second"),
    [("inputs/qe.in", "inputs/qe.in"), ("inputs/qe.in", "inputs/./qe.in")],
)
def test_core_result_rejects_duplicate_generated_paths(
    first: str,
    second: str,
) -> None:
    files = (
        GeneratedFile(path=first, content="first"),
        GeneratedFile(path=second, content="second"),
    )
    with pytest.raises(ValueError, match="duplicate path"):
        _core_result(files)


@pytest.mark.parametrize("value", [np.nan, np.inf, -np.inf])
def test_feature_vector_values_must_be_finite(value: float) -> None:
    with pytest.raises(ValueError, match="StructureFeatureVector.values"):
        StructureFeatureVector(
            values=np.array([1.0, value]),
            feature_names=["a", "b"],
        )


def test_feature_vector_values_and_names_must_have_matching_lengths() -> None:
    with pytest.raises(ValueError, match="same length"):
        StructureFeatureVector(
            values=np.array([1.0, 2.0]),
            feature_names=["a"],
        )


def test_feature_vector_values_must_be_one_dimensional() -> None:
    with pytest.raises(ValueError, match="one-dimensional"):
        StructureFeatureVector(
            values=np.array([[1.0, 2.0]]),
            feature_names=["a", "b"],
        )


class _Format(Enum):
    JSON = "json"


@dataclass(slots=True)
class _SerializableRecord:
    path: Path
    format: _Format
    values: np.ndarray


def test_to_jsonable_keeps_supported_values_working() -> None:
    record = _SerializableRecord(
        path=Path("inputs/qe.in"),
        format=_Format.JSON,
        values=np.array([1.0, 2.0]),
    )

    assert to_jsonable({1: record}) == {
        "1": {
            "path": "inputs/qe.in",
            "format": "json",
            "values": [1.0, 2.0],
        }
    }
    assert to_jsonable(np.longdouble("1.25")) == 1.25


@pytest.mark.parametrize("value", [object(), {"unsupported"}, 1 + 2j])
def test_to_jsonable_rejects_unsupported_values(value: object) -> None:
    with pytest.raises(TypeError, match="Unsupported value"):
        to_jsonable(value)


@pytest.mark.parametrize(
    "value",
    [np.nan, np.inf, -np.inf, [1.0, np.nan], np.array([1.0, np.inf])],
)
def test_to_jsonable_rejects_nonfinite_numbers(value: object) -> None:
    with pytest.raises(ValueError, match="must be finite"):
        to_jsonable(value)


def test_to_jsonable_rejects_unsupported_dictionary_keys() -> None:
    with pytest.raises(TypeError, match="Unsupported dictionary key"):
        to_jsonable({object(): "value"})


def test_to_jsonable_rejects_dictionary_key_stringification_collisions() -> None:
    """Reject mappings that would silently overwrite a JSON object value."""
    with pytest.raises(ValueError, match="stringify to the same key"):
        to_jsonable({1: "integer", "1": "string"})
