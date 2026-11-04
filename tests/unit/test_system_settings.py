from __future__ import annotations

import pytest

from goldilocks_core.advisors.boundary import BoundaryFacts
from goldilocks_core.advisors.cutoffs import CutoffsDecision
from goldilocks_core.advisors.electron_count import ElectronCountDecision
from goldilocks_core.advisors.hubbard_u import HubbardUDecision
from goldilocks_core.advisors.magnetic_config import (
    MagneticConfigFacts,
    OrderingRecord,
)
from goldilocks_core.advisors.vdw_method import VdwFacts
from goldilocks_core.system_settings import SystemSettings


def _system_settings(structure, pseudo_metadata_factory) -> SystemSettings:
    return SystemSettings(
        functional="PBEsol",
        cutoffs=CutoffsDecision(ecutwfc_ry=30.0, ecutrho_ry=120.0),
        electron_count=ElectronCountDecision(nelec=4.0, tot_charge=0.0),
        pseudopotentials=(pseudo_metadata_factory("Si"),),
        magnetic=MagneticConfigFacts(
            cell=structure,
            ordering=OrderingRecord(requested=None, applied=None),
            spin_polarized=False,
            magnetic_elements=(),
            starting_magnetization=None,
            compensated=False,
            tot_magnetization=None,
            spin_orbit_enabled=False,
            angle1=None,
            angle2=None,
        ),
        vdw=VdwFacts(use_vdw=False, method=None),
        hubbard=HubbardUDecision(),
        boundary=BoundaryFacts(isolation="periodic"),
    )


def test_system_settings_bundles_every_epic_5_advisor_output(
    silicon_structure, pseudo_metadata_factory
) -> None:
    settings = _system_settings(silicon_structure, pseudo_metadata_factory)

    assert settings.functional == "PBEsol"
    assert settings.cutoffs.ecutwfc_ry == 30.0
    assert settings.electron_count.nelec == 4.0
    assert settings.pseudopotentials[0].element == "Si"
    assert settings.magnetic.spin_polarized is False
    assert settings.vdw.use_vdw is False
    assert settings.hubbard.u_values == ()
    assert settings.boundary.isolation == "periodic"


def test_system_settings_is_frozen(silicon_structure, pseudo_metadata_factory) -> None:
    settings = _system_settings(silicon_structure, pseudo_metadata_factory)

    with pytest.raises(AttributeError):
        settings.functional = "PBE"  # type: ignore[misc]
