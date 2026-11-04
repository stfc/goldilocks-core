"""``advise_band()``/``check_band()``/``generate_band()``: the ``band``
task (#118), scf, then ``pw.x`` with ``calculation='bands'`` along the
written cell's band path, then ``bands.x``.

**One ``Advice`` per ``pw.x`` step.** ``advise_band`` asks
``advise_steps`` for the scf and the bands step at once, as
``service/_dos.py`` does for its scf and nscf: analysis, the system advice
and the written cell are decided once, and one job is sized over both
steps, each with its own ``max_seconds`` share of the walltime. The bands
step's ``Advice`` runs the band path of that cell with the scf step's
occupations (``_step_kpath.py``). ``bands.x`` has no advisor and no
settings: ``generate_band`` writes one ``bands.x`` step per spin channel
(``generation/quantum_espresso/bands.py``), which runs in the rest of the
walltime.

**Each step gets its own overrides** (#154). ``set_overrides`` routes a
band task's request to its scf and bands steps: the k-mesh, occupations and
SCF-loop keys reach the scf step only, ``k_path_distance`` the bands step
only, and ``nbnd``, ``extra_bands``, ``conv_thr``, ``npool`` and ``ndiag``,
given without a step, both, with the notice ``BandAdvice.warnings()``
publishes. No setting reaches ``bands_x``.

**The protocols.** The scf step gets ``BAND_SCF_PROTOCOL``, which withholds
the ``tot_magnetization = 0`` a compensated ordering would pin, since
bands.x stops on the two Fermi energies any moment writes; the gate refuses
a requested moment on a collinear run (``checks.py``, rule 7). The bands
step gets ``BANDS_PROTOCOL``, three times the occupied bands
(``_step_protocol.py``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pymatgen.core import Structure

from goldilocks_core.assets.store import AssetStore
from goldilocks_core.bundle import BundleInput, StructureIdentity
from goldilocks_core.checks import CheckReport
from goldilocks_core.generation.quantum_espresso.bands import write_qe_bands_x
from goldilocks_core.inputs.hpc import HpcProfile
from goldilocks_core.resolution import FieldState, Warning
from goldilocks_core.service._advice import Advice, RecordTiers, RunOverrides
from goldilocks_core.service._bundle import (
    assemble_bundle_input,
    render_submission,
    request_identity,
)
from goldilocks_core.service._generate import AdviceIncomplete, generate
from goldilocks_core.service._pipeline import advise_steps, check
from goldilocks_core.service._step_protocol import BAND_SCF_PROTOCOL, BANDS_PROTOCOL
from goldilocks_core.steps import SharedContext, Step, default_shared_context


@dataclass(frozen=True, slots=True)
class BandAdvice:
    """The scf and the bands step's ``Advice``, which share the analysis,
    the system advice and the task's one job. ``routing`` is the request's
    routing notices (``RunOverrides.warnings``)."""

    scf: Advice
    bands: Advice
    routing: tuple[Warning, ...]

    def field_states(self) -> tuple[FieldState[object], ...]:
        return self.scf.field_states() + self.bands.field_states()

    def tiers(self) -> RecordTiers:
        """``scf``'s records unprefixed, the task's one ``job`` with them,
        then the bands step's own: its path as ``k_path``, a name no scf
        record has, and the others under a ``bands_`` prefix, since the scf
        step has records of their names: ``bands_occupations``, ``k_path``,
        ``bands_nbnd``, ``bands_convergence`` and ``bands_parallelisation``."""
        bands = {
            name if name == "k_path" else f"bands_{name}": state
            for name, state in self.bands.step.records().items()
            if name != "job"
        }
        return self.scf.tiers("scf").with_records("bands", bands)

    def records(self) -> dict[str, FieldState[object]]:
        return self.tiers().records()

    def warnings(self) -> list[dict[str, object]]:
        """Every record's warnings, then the routing notices, tagged with
        the record ``overrides``."""
        return self.tiers().warnings() + [
            {**notice.model_dump(), "record": "overrides"} for notice in self.routing
        ]


def advise_band(
    structure: Structure,
    *,
    code: str = "quantum_espresso",
    hpc: HpcProfile,
    overrides: RunOverrides | None = None,
    store: AssetStore | None = None,
    fetch_missing: bool = False,
) -> BandAdvice:
    """Diagnosis for the band task's two pw.x steps, under the same contract
    as ``advise()``: an undecided field degrades, a fault raises. Each step
    gets its own overrides and its protocol (module docstring)."""
    overrides = overrides or RunOverrides()
    steps = overrides.for_steps(("scf", "bands", "bands_x"))
    advice = advise_steps(
        structure,
        code=code,
        hpc=hpc,
        overrides=overrides,
        steps={"scf": steps["scf"], "bands": steps["bands"]},
        protocols={"scf": BAND_SCF_PROTOCOL, "bands": BANDS_PROTOCOL},
        store=store,
        fetch_missing=fetch_missing,
    )
    return BandAdvice(
        scf=advice["scf"], bands=advice["bands"], routing=overrides.warnings
    )


def check_band(advice: BandAdvice) -> CheckReport:
    """``advise_band()``/``generate_band()``'s boundary: both steps'
    findings in one report, which keeps a root cause they share once. The
    bands step is checked with ``purpose="bands"``, the purpose of
    ``checks.py``'s band-task rules."""
    scf_report = check(advice.scf, purpose="scf")
    bands_report = check(advice.bands, purpose="bands")
    return CheckReport(blocking=scf_report.blocking + bands_report.blocking)


def generate_band(
    advice: BandAdvice, report: CheckReport, *, ctx: SharedContext | None = None
) -> tuple[Step, ...]:
    """Delivery: the scf, the bands and the ``bands.x`` steps on one
    ``SharedContext``, so the bands run reads the scf's save and bands.x
    the bands run's. Raises ``AdviceIncomplete`` when ``report`` is not
    ``ok``; ``report`` holds both steps' findings (``check_band``), so each
    inner ``generate()`` call is passed an ``ok`` report. ``bands.x`` runs
    once per spin channel of the written spin mode."""
    if not report.ok:
        raise AdviceIncomplete(report)
    shared_ctx = ctx or default_shared_context()
    ok_report = CheckReport()
    scf_steps = generate(advice.scf, ok_report, ctx=shared_ctx)
    bands_steps = generate(advice.bands, ok_report, ctx=shared_ctx, purpose="bands")
    spin_mode = advice.scf.system.magnetic.value.spin_mode
    return scf_steps + bands_steps + tuple(write_qe_bands_x(spin_mode, shared_ctx))


def render_submission_band(
    advice: BandAdvice,
    hpc: HpcProfile,
    code: str,
    steps: tuple[Step, ...],
) -> str:
    """One script for every step of a band task, from the task's one job,
    which ``scf`` and ``bands`` share (#169)."""
    return render_submission(advice.scf, hpc, code, steps)


def to_bundle_input_band(
    advice: BandAdvice,
    steps: tuple[Step, ...],
    submission_script: str,
    ctx: SharedContext,
    *,
    code: str,
    hpc: HpcProfile,
    assignments: Mapping[str, object],
    source: StructureIdentity,
) -> BundleInput:
    """``service/_bundle.py``'s ``to_bundle_input``, for a ``band`` task.
    The pseudopotential files and their licence come from ``advice.scf``,
    whose system advice ``advice.bands`` shares."""
    return assemble_bundle_input(
        advice.scf.system.pseudo,
        steps,
        submission_script,
        ctx,
        advice.records(),
        advice.warnings(),
        request_identity(
            "band", code=code, hpc=hpc, assignments=assignments, source=source
        ),
        hpc=hpc,
        job=advice.scf.step.resources.job.value,
    )
