"""Core runtime and SCF task registration."""

from __future__ import annotations

import os
from dataclasses import replace

from pymatgen.core import Structure

from goldilocks_core.advice.parameters import advise_parameters
from goldilocks_core.advisors import ml_kmesh_advisor
from goldilocks_core.advisors.kdistance_advisor import QrfKDistanceBackend
from goldilocks_core.analysis import analyze_structure
from goldilocks_core.bundle import write_bundle_directory
from goldilocks_core.contracts import (
    BundleRecord,
    CoreJobRequest,
    CoreRecords,
    CoreResult,
    GeneratedFiles,
    KMeshAdvisor,
    KPointSelection,
    ParameterAdvice,
    PathLike,
    SelectionRecord,
    StructureAnalysisRecord,
)
from goldilocks_core.generation.registry import generate_inputs
from goldilocks_core.graph import Preset, RunContext, StageSpec, TaskSpec, execute
from goldilocks_core.io.structures import load_structure
from goldilocks_core.kmesh.resolve import resolve_kpoints
from goldilocks_core.selection import select_parameters

SCF_TASK = TaskSpec(
    task="scf_single_point",
    stages=(
        StageSpec(
            output=Structure,
            inputs=(),
            call=lambda *, ctx: load_structure(ctx.structure_input),
        ),
        StageSpec(
            output=StructureAnalysisRecord,
            inputs=(Structure,),
            call=lambda structure, *, ctx: analyze_structure(structure),
        ),
        StageSpec(
            output=KPointSelection,
            inputs=(Structure,),
            call=lambda structure, *, ctx: resolve_kpoints(
                structure, ctx.hints, ctx.kmesh_backend
            ),
        ),
        StageSpec(
            output=ParameterAdvice,
            inputs=(StructureAnalysisRecord,),
            call=lambda analysis, *, ctx: advise_parameters(
                analysis, ctx.intent, ctx.hints
            ),
        ),
        StageSpec(
            output=SelectionRecord,
            inputs=(Structure, ParameterAdvice),
            call=lambda structure, advice, *, ctx: select_parameters(
                structure, advice, ctx.pseudo_metadata
            ),
        ),
        StageSpec(
            output=GeneratedFiles,
            inputs=(Structure, ParameterAdvice, SelectionRecord, KPointSelection),
            call=lambda structure, advice, selection, k_points, *, ctx: generate_inputs(
                structure, ctx.intent, advice, selection, k_points
            ),
        ),
    ),
    presets=(
        Preset(
            name="recommend",
            outputs=(
                StructureAnalysisRecord,
                ParameterAdvice,
                KPointSelection,
                SelectionRecord,
            ),
        ),
        Preset(
            name="generate",
            outputs=(
                StructureAnalysisRecord,
                ParameterAdvice,
                KPointSelection,
                SelectionRecord,
                GeneratedFiles,
            ),
        ),
    ),
)


class CoreRuntime:
    """Own model lifecycle and execute Core task graphs."""

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
        self._task = SCF_TASK
        self._closed = False

    def _build_backend(self) -> QrfKDistanceBackend:
        """Build the runtime-owned QRF backend."""
        return QrfKDistanceBackend(
            registry_path=self._registry_path,
            metallicity_checkpoint=self._metallicity_checkpoint,
            metallicity_atom_init=self._metallicity_atom_init,
        )

    @property
    def is_closed(self) -> bool:
        """Return whether this runtime has been closed."""
        return self._closed

    def recommend(self, request: CoreJobRequest) -> CoreResult:
        """Execute the SCF recommend preset."""
        preset = self._task.preset("recommend")
        records = self.compute(preset.outputs, request)
        return self._assemble_result(request, records)

    def generate(
        self,
        request: CoreJobRequest,
        *,
        output_dir: str | None = None,
    ) -> CoreResult:
        """Execute the SCF generate preset and optionally publish a bundle."""
        preset = self._task.preset("generate")
        records = self.compute(preset.outputs, request)
        result = self._assemble_result(request, records)
        if output_dir is None:
            return result
        bundle = write_bundle_directory(result, output_dir)
        return replace(result, bundle=bundle)

    def compute(
        self,
        outputs: tuple[type, ...],
        request: CoreJobRequest,
    ) -> CoreRecords:
        """Execute the minimal SCF subgraph for ``outputs``."""
        self._ensure_open()
        self._ensure_scf_request(request)
        return execute(self._task, outputs, self._context(request))

    def reset(self) -> None:
        """Discard cached model state so the next model call reloads it."""
        self._backend.reset()

    def close(self) -> None:
        """Release model resources; repeated calls are harmless."""
        if self._closed:
            return
        self._backend.close()
        self._closed = True

    def __enter__(self) -> CoreRuntime:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _context(self, request: CoreJobRequest) -> RunContext:
        """Build a fresh graph context from a request and owned services."""
        backend: KMeshAdvisor = self._backend
        if request.kmesh_model is not None:
            backend = ml_kmesh_advisor(request.kmesh_model)
        return RunContext(
            structure_input=request.structure,
            intent=request.intent,
            hints=request.hints,
            pseudo_metadata=request.pseudo_metadata,
            kmesh_backend=backend,
        )

    def _assemble_result(
        self,
        request: CoreJobRequest,
        records: CoreRecords,
        *,
        bundle: BundleRecord | None = None,
    ) -> CoreResult:
        """Assemble a preset result from type-keyed graph records."""
        analysis = records[StructureAnalysisRecord]
        advice = records[ParameterAdvice]
        k_points = records[KPointSelection]
        selection = records[SelectionRecord]
        warnings = _unique_warnings(
            analysis.disorder_warnings,
            analysis.analysis_warnings,
            _advice_warnings(advice),
            k_points.provenance.warnings,
            selection.warnings,
        )
        return CoreResult(
            intent=request.intent,
            analysis=analysis,
            advice=advice,
            k_points=k_points,
            selection=selection,
            generated_files=records.get(GeneratedFiles, ()),
            warnings=warnings,
            bundle=bundle,
        )

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("CoreRuntime is closed.")

    def _ensure_scf_request(self, request: CoreJobRequest) -> None:
        if request.intent.task != self._task.task:
            raise ValueError(
                f"No Core task registered for task={request.intent.task!r}. "
                f"Available: {self._task.task}"
            )


def _advice_warnings(advice: ParameterAdvice) -> tuple[str, ...]:
    """Return warnings from every advice decision."""
    return _unique_warnings(
        advice.smearing.provenance.warnings,
        advice.magnetism.provenance.warnings,
        advice.spin_orbit.provenance.warnings,
        advice.pseudopotentials.provenance.warnings,
        advice.convergence.provenance.warnings,
        advice.vdw.provenance.warnings,
    )


def _unique_warnings(*groups: tuple[str, ...]) -> tuple[str, ...]:
    """Return warnings in first-seen order without duplicates."""
    return tuple(dict.fromkeys(warning for group in groups for warning in group))
