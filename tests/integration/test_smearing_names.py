"""Every smearing kind Goldilocks offers is one pw.x knows (#200).

QE 7.3 ``PW/src/set_occupations.f90:48-62`` accepts four smearing
functions under fixed names and stops on any other name with "smearing
<name> unknown". ``advise``/``check``/``generate`` run end to end on a
synthetic SSSP-shaped table, so this runs in CI.
"""

from __future__ import annotations

import re

import pytest
from pymatgen.core import Lattice, Structure
from support import sssp_fixture_table_spec

from goldilocks_core.assets.pseudopotentials.importers import sssp_preparer
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.capabilities import capabilities
from goldilocks_core.inputs.hpc import load_hpc_profile
from goldilocks_core.service import RunOverrides, advise, check, generate
from goldilocks_core.set_overrides import build_overrides, build_overrides_from_cli

pytestmark = pytest.mark.integration

_PW_X_SMEARING_NAMES = frozenset(
    {
        *("gaussian", "gauss", "Gaussian", "Gauss"),
        *("methfessel-paxton", "m-p", "mp", "Methfessel-Paxton", "M-P", "MP"),
        *("marzari-vanderbilt", "cold", "m-v", "mv", "Marzari-Vanderbilt"),
        *("M-V", "MV"),
        *("fermi-dirac", "f-d", "fd", "Fermi-Dirac", "F-D", "FD"),
    }
)
"""The names QE 7.3 set_occupations.f90:48-59 accepts for ``smearing``."""

_SMEARING_LINE = re.compile(r"^\s*smearing\s*=\s*'([^']*)'\s*$", re.MULTILINE)


def _aluminium() -> Structure:
    """fcc Al, conventional cell (4 atoms, a = 4.05 A)."""
    return Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(4.05), ["Al"], [[0.0, 0.0, 0.0]]
    )


@pytest.fixture
def store(tmp_path, monkeypatch) -> AssetStore:
    spec, registry_table = sssp_fixture_table_spec(tmp_path / "sources", {"Al": 3.0})
    monkeypatch.setattr(
        "goldilocks_core.service._pseudo.load_tables",
        lambda *_args, **_kwargs: {registry_table.id: registry_table},
    )
    store = AssetStore(tmp_path / "store")
    store.install(spec, sssp_preparer(registry_table))
    return store


def _rendered_smearing(store: AssetStore, overrides: RunOverrides) -> str:
    """The ``smearing`` value scf.in carries for fcc Al under ``overrides``."""
    advice = advise(
        _aluminium(), hpc=load_hpc_profile("scarf"), overrides=overrides, store=store
    )
    report = check(advice)
    assert report.ok, report.blocking
    (scf,) = generate(advice, report)
    (name,) = _SMEARING_LINE.findall(scf.files["scf.in"])
    return name


def test_a_fermi_dirac_request_renders_quantum_espresso_s_short_name(store) -> None:
    """`--set smearing_type=fd` was refused; Fermi-Dirac had no spelling."""
    overrides = build_overrides_from_cli(["smearing_type=fd"], task="scf_single_point")

    assert _rendered_smearing(store, overrides) == "fd"


def test_every_advertised_smearing_type_renders_a_name_pw_x_accepts(store) -> None:
    """'fixed' was advertised, passed check() and rendered smearing = 'fixed'."""
    (setting,) = (s for s in capabilities()["settings"] if s["key"] == "smearing_type")

    assert setting["enum"]
    for kind in setting["enum"]:
        name = _rendered_smearing(
            store, build_overrides({"smearing_type": kind}, task="scf_single_point")
        )
        assert name == kind
        assert name in _PW_X_SMEARING_NAMES, kind
