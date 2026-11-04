"""dos: ``dos.x``'s own settings, from the nscf step's occupations.

New in v2 (v2 epic 9, #9) -- first (and, per this epic's own scope,
deliberately only) advisor DOS multi-step scaffolding needs to prove
``DosSettings`` (``step_settings.py``, epic 6) has a real producer, not
full DOS science. QE's own ``INPUT_DOS.html`` (fetched and read
2026-09-14) is explicit that several of these have no fixed default at
all -- this module says so plainly rather than inventing one where QE
itself does not.

**``ngauss``**: QE's own documented default is ``0`` (a plain Gaussian).

**``degauss`` (this module's ``broadening``)**: QE's own doc says an
unset value falls back to whatever the *upstream* scf/nscf calculation
used, or ``DeltaE`` (in Ry) if that in turn is unset. This module reads
the real upstream value directly (the nscf step's own resolved
``OccupationsDecision.degauss``) instead of leaving a gap for QE to fill
implicitly by reading the previous calculation's save file -- consistent
with this codebase writing every value explicitly rather than relying on
implicit QE fallbacks. When the nscf step used a tetrahedron method
(no smearing width exists at all -- the ``tetrahedra_opt`` the dos task's
nscf protocol gives unless the request sets occupations,
``service/_step_protocol.py``'s ``DOS_NSCF_PROTOCOL``, per
aiida-quantumespresso's own ``pdos.yaml`` protocol, confirmed against its
source 2026-09-14), ``broadening`` is correctly left ``None``: QE's
own ``bz_sum`` default already switches to a tetrahedron integration
method whenever no ``degauss`` is given, so leaving it unset here is the
physically correct choice, not a gap.

**``delta_e``**: QE's ``INPUT_DOS.html`` lists no default at all (a
required value). ``0.01`` eV is not invented here -- it is
aiida-quantumespresso's own ``workflows/protocols/pdos.yaml``
``dos.parameters.DOS.deltae`` default (its "balanced" and "stringent"
protocols both use it; only its "fast"/testing protocol relaxes to
``0.1``), confirmed against that file's source 2026-09-14.

**``emin``/``emax``**: left ``None`` unless a human overrides them. QE's
own documented default is "band extrema" -- the full computed energy
range -- which is exactly what omitting the keyword already gives;
guessing a narrower, Fermi-relative window without having actually run
the calculation first would be an invented number this module has no
basis for.

**Request values are validated as dos.x reads them** (#154, QE 7.3
``PP/src/dos.f90``): ``delta_e``/``emin``/``emax`` in eV and
``broadening`` in Ry (dos.x divides the first three by ``rytoev``), the
two widths positive and the window non-empty, and ``ngauss`` one of the
smearings ``w0gauss`` knows: -99 (Fermi-Dirac), -1 (cold) or 0..10
(Methfessel-Paxton order), any other stops dos.x
(``Modules/w0gauss.f90:43-61``).

**A requested ``ngauss`` needs a broadening width.** dos.x reads the
``ngauss`` of its input only together with a ``degauss`` there
(``dos.f90:161-163``). Without one it integrates with tetrahedra after a
tetrahedron nscf step (``:129``) and broadens with a plain Gaussian of
width ``DeltaE`` after fixed occupations (``:172-174``), ignoring the
input's ``ngauss``. So the record is ``Blocked`` when the request sets
``ngauss`` and neither the request nor the nscf step's smearing gives a
width, rather than recording a setting dos.x drops.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from pydantic import Field, field_validator, model_validator

from goldilocks_core.advisors.occupations import OccupationsDecision
from goldilocks_core.inputs.overrides import HumanInput, LlmInput
from goldilocks_core.resolution import (
    Blocked,
    FieldState,
    Provenance,
    Resolved,
    blocked_by,
    field_sources_from,
)

DEFAULT_DELTA_E = 0.01
"""eV. aiida-quantumespresso's own ``pdos.yaml`` "balanced"/"stringent"
protocol default (its "fast" testing protocol alone uses ``0.1``)."""

DEFAULT_NGAUSS = 0
"""QE's own ``INPUT_DOS.html`` documented default: a plain Gaussian."""

_DOS_X_NGAUSS = frozenset({-99, -1, *range(11)})
"""Every ``ngauss`` QE 7.3's ``w0gauss`` accepts (module docstring)."""


@dataclass(frozen=True, slots=True)
class DosDecision:
    emin: float | None
    emax: float | None
    delta_e: float
    broadening: float | None
    ngauss: int


class DosHumanInput(HumanInput):
    emin: float | None = None
    emax: float | None = None
    delta_e: float | None = Field(default=None, gt=0)
    broadening: float | None = Field(default=None, gt=0)
    ngauss: int | None = None

    @field_validator("ngauss")
    @classmethod
    def _ngauss_is_a_dos_x_smearing(cls, ngauss: int | None) -> int | None:
        if ngauss is not None and ngauss not in _DOS_X_NGAUSS:
            raise ValueError(
                "ngauss must be -99 (Fermi-Dirac), -1 (cold) or 0..10 "
                "(Methfessel-Paxton order), the smearings dos.x knows"
            )
        return ngauss

    @model_validator(mode="after")
    def _window_is_not_empty(self) -> DosHumanInput:
        if self.emin is not None and self.emax is not None and self.emin >= self.emax:
            raise ValueError(f"emin ({self.emin}) must be below emax ({self.emax})")
        return self


class DosLlmInput(LlmInput):
    delta_e: float | None = Field(default=None, gt=0)


def dos_settings(
    nscf_occupations: FieldState[OccupationsDecision],
    human: DosHumanInput | None = None,
    llm: DosLlmInput | None = None,
) -> FieldState[DosDecision]:
    """``nscf_occupations`` is the *nscf* step's own resolved
    ``OccupationsDecision`` -- ``dos.x`` reads a previous step's
    wavefunctions and has no occupations decision of its own, but needs
    to know whether that step used smearing (and if so, how much) to
    decide ``broadening``. ``field_sources`` names the tier of each of the
    five settings, so a requested ``ngauss`` reads ``human`` (#154).
    ``Blocked`` for a requested ``ngauss`` without a broadening width,
    which dos.x would ignore (module docstring)."""
    human = human or DosHumanInput()
    llm = llm or DosLlmInput()

    if isinstance(nscf_occupations, Blocked):
        return Blocked(by=nscf_occupations)
    if not nscf_occupations.ok:
        return Blocked(by=blocked_by(nscf_occupations))

    delta_e = next(
        value
        for value in (human.delta_e, llm.delta_e, DEFAULT_DELTA_E)
        if value is not None
    )
    ngauss = human.ngauss if human.ngauss is not None else DEFAULT_NGAUSS

    broadening = human.broadening
    if broadening is None:
        broadening = nscf_occupations.value.degauss
    if human.ngauss is not None and broadening is None:
        return Blocked(
            by=(
                f"ngauss={human.ngauss} would have no effect: dos.x reads ngauss "
                "only with a broadening width, and the nscf step's "
                f"{nscf_occupations.value.occupations} occupations give none; "
                "set broadening as well, or drop ngauss."
            )
        )

    decision = DosDecision(
        emin=human.emin,
        emax=human.emax,
        delta_e=delta_e,
        broadening=broadening,
        ngauss=ngauss,
    )
    field_sources = field_sources_from(
        human, llm, fields=[field.name for field in fields(decision)]
    )
    return Resolved(decision, Provenance.from_field_sources(field_sources))
