from __future__ import annotations

import dataclasses

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.advisors.convergence import ConvergenceDecision
from goldilocks_core.advisors.k_path import KPathDecision, PathBranch, PathVertex
from goldilocks_core.advisors.k_sampling import KSamplingDecision
from goldilocks_core.advisors.nbnd import NbndDecision
from goldilocks_core.advisors.occupations import OccupationsDecision
from goldilocks_core.advisors.parallelisation import ParallelisationDecision
from goldilocks_core.advisors.phonon import (
    PhononDecision,
    PhononDosDecision,
    Q2rDecision,
)
from goldilocks_core.advisors.q_sampling import QSamplingDecision
from goldilocks_core.step_settings import (
    DispersionSettings,
    DosSettings,
    MatdynSettings,
    PhSettings,
    PwSettings,
    Q2rSettings,
)

_SETTINGS = [
    PwSettings,
    DosSettings,
    PhSettings,
    Q2rSettings,
    MatdynSettings,
    DispersionSettings,
]


def _pw_settings() -> PwSettings:
    return PwSettings(
        occupations=OccupationsDecision(
            occupations="smearing", smearing_type="cold", degauss=0.01
        ),
        k_sampling=KSamplingDecision(mesh=(4, 4, 4), shift=(0, 0, 0), k_distance=0.15),
        n_irr_k=10,
        nbnd=NbndDecision(nbnd=9),
        convergence=ConvergenceDecision(
            conv_thr=2e-9,
            etot_conv_thr=1e-4,
            mixing_beta=0.4,
            electron_maxstep=80,
            mixing_mode="plain",
            mixing_fixed_ns=None,
        ),
    )


def test_pw_settings_holds_every_per_step_advisors_decision() -> None:
    settings = _pw_settings()

    assert settings.occupations is not None
    assert settings.occupations.occupations == "smearing"
    assert settings.k_sampling is not None
    assert settings.k_sampling.mesh == (4, 4, 4)
    assert settings.n_irr_k == 10
    assert settings.nbnd is not None
    assert settings.nbnd.nbnd == 9
    assert settings.convergence is not None
    assert settings.convergence.conv_thr == 2e-9


def test_pw_settings_has_no_producer_fields_default_to_none() -> None:
    settings = _pw_settings()

    assert settings.parallel is None
    assert settings.relax is None


def test_a_step_sampled_on_a_mesh_carries_no_band_path() -> None:
    """``k_path`` is the bands step's path, written as K_POINTS crystal_b
    (#118); it defaults to None."""
    assert _pw_settings().k_path is None


@pytest.mark.parametrize("settings", _SETTINGS)
@pytest.mark.parametrize("field", ["size", "mem_per_proc"])
def test_no_step_settings_carry_a_memory_estimate(settings: type, field: str) -> None:
    """#148: no writer reads a memory estimate; the job record carries
    pw.x's per-process and total memory instead."""
    assert field not in {item.name for item in dataclasses.fields(settings)}
    with pytest.raises(TypeError, match=field):
        settings(**{field: None})


@pytest.mark.parametrize("settings", _SETTINGS)
def test_no_step_settings_carry_disk_io(settings: type) -> None:
    """#129: disk_io='none' would leave pw.x no status file to check
    (punch.f90:60-63), so no settings can request it."""
    assert "disk_io" not in {field.name for field in dataclasses.fields(settings)}
    with pytest.raises(TypeError, match="disk_io"):
        settings(disk_io="none")


def test_constructing_pw_settings_with_no_arguments_is_allowed() -> None:
    """Nothing is required yet -- every field is reserved shape, not a
    forced fabrication, until its producer exists."""
    settings = PwSettings()

    assert settings.occupations is None
    assert settings.nbnd is None


def test_dos_settings_has_its_own_broadening_field_not_degauss() -> None:
    """The deferred v2 epic 2 physics test: pw.x's occupation-broadening
    degauss and dos.x's DOS-histogram broadening are physically unrelated
    numbers QE happens to spell the same way -- DosSettings existing as
    its own type, with its own field name, is what prevents one value
    from silently doing double duty across the two programs."""
    dos = DosSettings(emin=-5.0, emax=5.0, delta_e=0.01, broadening=0.02, ngauss=0)

    assert dos.broadening == 0.02
    assert not hasattr(dos, "degauss")
    assert not hasattr(dos, "occupations")
    assert not hasattr(dos, "k_sampling")
    assert not hasattr(dos, "nbnd")
    assert not hasattr(dos, "convergence")


def test_pw_settings_has_no_dos_specific_fields() -> None:
    pw = _pw_settings()

    assert not hasattr(pw, "broadening")
    assert not hasattr(pw, "ngauss")
    assert not hasattr(pw, "emin")


def _q2r() -> Q2rDecision:
    return Q2rDecision(asr="simple", loto_2d=False)


def _ph_settings() -> PhSettings:
    """Diamond Si's ph.x step: the 7x7x7 q-mesh and the balanced protocol."""
    return PhSettings(
        q_sampling=QSamplingDecision(
            mesh=(7, 7, 7), q_distance=0.3, n_irr_q=20, work=2401
        ),
        phonon=PhononDecision(tr2_ph=1e-18, alpha_mix=0.4, nmix_ph=8),
        parallel=ParallelisationDecision(npool=4, ndiag=None, kpoint_spin_pairs=72),
    )


def _matdyn_settings() -> MatdynSettings:
    return MatdynSettings(
        q2r=_q2r(),
        phonon_dos=PhononDosDecision(
            mesh=(21, 21, 21), dos_q_distance=0.1, delta_e=1.0
        ),
    )


def _dispersion_settings() -> DispersionSettings:
    """Diamond Si's dispersion along Gamma-X alone, 46 points."""
    cell = Structure(
        Lattice.from_parameters(3.84, 3.84, 3.84, 60, 60, 60),
        ["Si", "Si"],
        [[0.0, 0.0, 0.0], [0.25, 0.25, 0.25]],
    )
    branch = PathBranch(
        (PathVertex("Gamma", (0.0, 0.0, 0.0)), PathVertex("X", (0.5, 0.0, 0.5))),
        (45,),
    )
    return DispersionSettings(
        q2r=_q2r(),
        path=KPathDecision(
            branches=(branch,),
            k_path_distance=0.025,
            n_kpoints=46,
            convention="setyawan_curtarolo",
            lattice_type="FCC",
            space_group="Fd-3m (227)",
            primitive_cells=1,
            cell=cell,
        ),
    )


def test_ph_settings_is_its_own_distinct_type_too() -> None:
    """ph.x's settings are the advisors' decisions, all required. No epsil:
    on a q-mesh ph.x decides it at Gamma itself (#215)."""
    ph = _ph_settings()

    assert ph.q_sampling.mesh == (7, 7, 7)
    assert ph.phonon.tr2_ph == 1e-18
    assert ph.parallel.npool == 4
    assert not hasattr(ph, "epsil")
    assert not hasattr(ph, "occupations")
    assert not hasattr(ph, "broadening")
    with pytest.raises(TypeError, match="q_sampling"):
        PhSettings()  # type: ignore[call-arg]


def test_q2r_x_and_matdyn_x_share_the_sum_rule_and_split_the_dos() -> None:
    """q2r.x and matdyn.x apply the same acoustic sum rule and 2D term;
    only matdyn.x has the DOS mesh."""
    q2r, matdyn = Q2rSettings(q2r=_q2r()), _matdyn_settings()

    assert matdyn.q2r == q2r.q2r
    assert matdyn.phonon_dos.mesh == (21, 21, 21)
    assert not hasattr(q2r, "phonon_dos")


def test_the_dispersion_takes_the_sum_rule_and_a_path_but_no_dos_mesh() -> None:
    """matdyn.x's dispersion run applies q2r.x's acoustic sum rule and 2D term
    along its path; it has no DOS mesh, and both its fields are required
    (#215)."""
    dispersion = _dispersion_settings()

    assert (dispersion.q2r.asr, dispersion.path.n_kpoints) == ("simple", 46)
    assert not hasattr(dispersion, "phonon_dos")
    with pytest.raises(TypeError, match="path"):
        DispersionSettings(q2r=_q2r())  # type: ignore[call-arg]


def test_step_settings_variants_are_distinguishable_by_isinstance() -> None:
    variants: list[object] = [
        _pw_settings(),
        DosSettings(),
        _ph_settings(),
        Q2rSettings(q2r=_q2r()),
        _matdyn_settings(),
        _dispersion_settings(),
    ]

    matched = [
        [settings for settings in _SETTINGS if isinstance(variant, settings)]
        for variant in variants
    ]

    assert matched == [[settings] for settings in _SETTINGS]


def test_the_phonon_first_step_keywords_default_to_none() -> None:
    settings = _pw_settings()

    assert settings.fft_grid is None
    assert settings.dftd3_threebody is None


@pytest.mark.parametrize(
    ("fft_grid", "dftd3_threebody", "keywords"),
    [
        (None, None, {}),
        ((45, 45, 64), None, {"nr1": 45, "nr2": 45, "nr3": 64}),
        (None, False, {"dftd3_threebody": False}),
        (
            (45, 45, 64),
            False,
            {"nr1": 45, "nr2": 45, "nr3": 64, "dftd3_threebody": False},
        ),
    ],
    ids=["neither", "fft_grid", "two_body_d3", "both"],
)
def test_dfpt_system_keywords_write_the_whole_grid_and_the_d3_flag(
    fft_grid: tuple[int, int, int] | None,
    dftd3_threebody: bool | None,
    keywords: dict[str, object],
) -> None:
    """The phonon tasks' first step writes alpha-U's grid ph.x accepts,
    45x45x64, as nr1-nr3, always all three, since pw.x computes its own grid
    when any is 0 (QE 7.3 FFTXlib/src/fft_types.f90:1078), and
    dftd3_threebody when set; nothing when neither is (#215)."""
    settings = dataclasses.replace(
        _pw_settings(), fft_grid=fft_grid, dftd3_threebody=dftd3_threebody
    )

    assert settings.dfpt_system_keywords == keywords
