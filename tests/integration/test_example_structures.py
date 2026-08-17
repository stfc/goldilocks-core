from __future__ import annotations

import pytest

from goldilocks_core import CalculationHints, PresetRequest, run_core_job
from goldilocks_core.examples import available_structures, structure, structures_path


def test_bundled_structures_are_installed_with_the_package() -> None:
    assert structures_path().is_dir()
    assert available_structures() == ("Fe_bcc.cif", "Pt_fcc.cif", "Si.cif")


def test_structure_rejects_an_unknown_name() -> None:
    with pytest.raises(FileNotFoundError) as error:
        structure("Unobtainium.cif")

    assert "Si.cif" in str(error.value)


@pytest.mark.parametrize("name", ["Si.cif", "Fe_bcc.cif", "Pt_fcc.cif"])
def test_every_bundled_structure_runs_through_the_pipeline(name: str) -> None:
    result = run_core_job(
        PresetRequest(
            structure=structure(name),
            hints=CalculationHints(k_grid=(4, 4, 4)),
            pseudo_metadata=(),
        )
    )

    assert result.analysis.reduced_formula
    assert result.k_points.grid == (4, 4, 4)


def test_bundled_structures_exercise_distinct_advice_branches() -> None:
    hints = CalculationHints(k_grid=(4, 4, 4))
    silicon = run_core_job(
        PresetRequest(structure=structure("Si.cif"), hints=hints, pseudo_metadata=())
    )
    iron = run_core_job(
        PresetRequest(
            structure=structure("Fe_bcc.cif"), hints=hints, pseudo_metadata=()
        )
    )
    platinum = run_core_job(
        PresetRequest(
            structure=structure("Pt_fcc.cif"), hints=hints, pseudo_metadata=()
        )
    )

    # Silicon: the non-magnetic, light-element, no-SOC baseline.
    assert silicon.advice.magnetism.spin_polarized is False
    assert silicon.advice.spin_orbit.consider is False
    assert silicon.analysis.heavy_elements == ()

    # Iron: magnetic metal, so spin polarisation and metallic smearing.
    assert iron.analysis.electronic_character == "likely_metal"
    assert iron.advice.magnetism.spin_polarized is True
    assert iron.advice.smearing.smearing_type == "cold"

    # Platinum: the only heavy element, and the only one reaching SOC advice.
    assert platinum.analysis.heavy_elements == ("Pt",)
    assert platinum.advice.spin_orbit.consider is True
