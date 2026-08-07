"""Core runtime: owner of model lifecycle and composed Core entrypoints.

Every transport (CLI, HTTP, MCP, library) delegates to one of the
convenience entrypoints on :class:`CoreRuntime`. Model resources load lazily
on first use and are reused across jobs run through the same instance.
``reset`` discards cached model state (next job reloads); ``close`` releases
it. No module-global default runtime exists.
"""

from __future__ import annotations

import os

from pymatgen.core import Structure

from goldilocks_core.advice import advise_parameters
from goldilocks_core.advisors import ml_kmesh_advisor
from goldilocks_core.advisors.kdistance_advisor import QrfKDistanceBackend
from goldilocks_core.analysis import StructureAnalysisRecord, analyze_structure
from goldilocks_core.bundle import write_bundle_directory
from goldilocks_core.contracts import (
    BundleRecord,
    CoreJobRequest,
    CoreResult,
    KMeshAdvisor,
    KPointSelection,
    ModelSpec,
    ParameterAdvice,
    PathLike,
    SelectionRecord,
)
from goldilocks_core.generation import generate_inputs
from goldilocks_core.io.structures import load_structure
from goldilocks_core.kmesh import resolve_kpoints
from goldilocks_core.selection import select_parameters

__all__ = ["CoreRuntime"]


class CoreRuntime:
    """Owner of model lifecycle and the composed Core entrypoints.

    Every transport (CLI, HTTP, MCP, library) delegates to one of the
    convenience entrypoints below. Model resources load lazily on first
    use and are reused across jobs run through this instance.
    ``reset`` discards cached model state (next job reloads); ``close``
    releases it. No module-global default runtime exists.
    """

    def __init__(
        self,
        *,
        registry_path: PathLike | None = None,
        metallicity_checkpoint: PathLike | None = None,
        metallicity_atom_init: PathLike | None = None,
    ) -> None:
        self._registry_path = registry_path or os.environ.get(
            "GOLDILOCKS_MODEL_REGISTRY"
        )
        self._metallicity_checkpoint = metallicity_checkpoint or os.environ.get(
            "GOLDILOCKS_METALLICITY_CHECKPOINT"
        )
        self._metallicity_atom_init = metallicity_atom_init or os.environ.get(
            "GOLDILOCKS_METALLICITY_ATOM_INIT"
        )
        self._backend = self._build_backend()
        self._closed = False

    def _build_backend(self) -> QrfKDistanceBackend:
        """Construct the default QRF k-distance backend with captured config."""
        return QrfKDistanceBackend(
            registry_path=self._registry_path,
            metallicity_checkpoint=self._metallicity_checkpoint,
            metallicity_atom_init=self._metallicity_atom_init,
        )

    @property
    def is_closed(self) -> bool:
        """Whether this runtime has been closed."""
        return self._closed

    def recommend(self, request: CoreJobRequest) -> CoreResult:
        """Run Load → Analyse → Advise → Kmesh → Select and return records."""
        self._ensure_open()
        _, analysis, advice, _, selection, warnings = self._run_scf_stages(request)
        return CoreResult(
            intent=request.intent,
            analysis=analysis,
            advice=advice,
            selection=selection,
            generated_files=(),
            warnings=warnings,
            bundle=None,
        )

    def generate(
        self,
        request: CoreJobRequest,
        *,
        output_dir: str | None = None,
    ) -> CoreResult:
        """Run the full SCF path through Generate, optionally writing a bundle."""
        self._ensure_open()
        structure, analysis, advice, _, selection, warnings = self._run_scf_stages(
            request
        )
        generated_files = generate_inputs(structure, request.intent, advice, selection)
        bundle: BundleRecord | None = None
        if output_dir is not None:
            in_progress = CoreResult(
                intent=request.intent,
                analysis=analysis,
                advice=advice,
                selection=selection,
                generated_files=generated_files,
                warnings=warnings,
            )
            bundle = write_bundle_directory(in_progress, output_dir)
        return CoreResult(
            intent=request.intent,
            analysis=analysis,
            advice=advice,
            selection=selection,
            generated_files=generated_files,
            warnings=warnings,
            bundle=bundle,
        )

    def reset(self) -> None:
        """Discard cached model state; the next job reloads."""
        self._backend.reset()

    def close(self) -> None:
        """Release model resources; idempotent."""
        if self._closed:
            return
        self._backend.close()
        self._closed = True

    def __enter__(self) -> CoreRuntime:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _ensure_open(self) -> None:
        """Raise if the runtime has been closed."""
        if self._closed:
            raise RuntimeError("CoreRuntime is closed.")

    def _run_scf_stages(
        self, request: CoreJobRequest
    ) -> tuple[
        Structure,
        StructureAnalysisRecord,
        ParameterAdvice,
        KPointSelection,
        SelectionRecord,
        tuple[str, ...],
    ]:
        """Run the shared SCF sub-graph: Load → Analyse → Advise → Kmesh → Select."""
        structure = load_structure(request.structure)
        analysis = analyze_structure(structure)
        advice = advise_parameters(analysis, request.intent, request.hints)
        k_points = resolve_kpoints(
            structure, request.hints, self._kmesh_backend(request.kmesh_model)
        )
        selection = select_parameters(
            structure, advice, k_points, tuple(request.pseudo_metadata)
        )
        warnings = _unique_warnings(
            analysis.disorder_warnings,
            analysis.analysis_warnings,
            _advice_warnings(advice),
            k_points.provenance.warnings,
            selection.warnings,
        )
        return structure, analysis, advice, k_points, selection, warnings

    def _kmesh_backend(self, kmesh_model: ModelSpec | None) -> KMeshAdvisor:
        """Return the k-point backend: local model when given, else QRF."""
        if kmesh_model is not None:
            return ml_kmesh_advisor(kmesh_model)
        return self._backend


def _advice_warnings(advice: ParameterAdvice) -> tuple[str, ...]:
    """Return actionable warnings from every Advise sub-decision."""
    return _unique_warnings(
        advice.smearing.provenance.warnings,
        advice.magnetism.provenance.warnings,
        advice.spin_orbit.provenance.warnings,
        advice.pseudopotentials.provenance.warnings,
        advice.convergence.provenance.warnings,
        advice.vdw.provenance.warnings,
    )


def _unique_warnings(*groups: tuple[str, ...]) -> tuple[str, ...]:
    """Return warnings in first-seen order without duplicate messages."""
    return tuple(dict.fromkeys(warning for group in groups for warning in group))
