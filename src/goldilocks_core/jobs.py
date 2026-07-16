"""Fixed Core job runner shared by Python, CLI, and future HTTP surfaces."""

from __future__ import annotations

import os
import weakref
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Condition, RLock, get_ident
from types import TracebackType

from goldilocks_core.advice import advise_parameters
from goldilocks_core.advisors import default_kmesh_advisor
from goldilocks_core.analysis import analyze_structure
from goldilocks_core.bundle import write_bundle_directory
from goldilocks_core.contracts import (
    AdviseStage,
    AnalyzeStage,
    BundleRecord,
    BundleStage,
    CalculationHints,
    CalculationIntent,
    CoreJobRequest,
    CoreResult,
    GeneratedFile,
    GenerateStage,
    KMeshAdvisor,
    ParameterAdvice,
    PathLike,
    RuntimeResource,
    SelectStage,
    StageRecord,
    StructureInput,
)
from goldilocks_core.generation import generate_inputs
from goldilocks_core.io.structures import load_structure
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata
from goldilocks_core.selection import select_parameters


@dataclass(frozen=True, slots=True)
class Pipeline:
    """Composable stage backends for the Core pipeline.

    Construct with no arguments for the built-in QRF k-point backend with
    heuristic fallback; override any field to swap that stage's backend.
    Backends are plain callables with the stage signature — no base class,
    no registry.

    Attributes:
        analyze: Analyze-stage backend.
        advise: Advise-stage backend.
        kmesh: Kmesh-stage backend that resolves concrete k-points.
        select: Select-stage backend that resolves concrete selections.
        generate: Generate-stage backend that writes target-code text.
        bundle: Bundle-stage backend that writes portable outputs.
        resources: Extra lifecycle resources owned by a runtime using this pipeline.
    """

    analyze: AnalyzeStage = analyze_structure
    advise: AdviseStage = advise_parameters
    kmesh: KMeshAdvisor = field(default_factory=default_kmesh_advisor)
    select: SelectStage = select_parameters
    generate: GenerateStage = generate_inputs
    bundle: BundleStage = write_bundle_directory
    resources: tuple[RuntimeResource, ...] = ()

    def __post_init__(self) -> None:
        """Register lifecycle-aware stage backends as owned resources."""
        stage_backends = (
            self.analyze,
            self.advise,
            self.kmesh,
            self.select,
            self.generate,
            self.bundle,
        )
        resources: list[RuntimeResource] = []
        for resource in self.resources:
            if not any(existing is resource for existing in resources):
                resources.append(resource)
        for backend in stage_backends:
            if isinstance(backend, RuntimeResource) and not any(
                resource is backend for resource in resources
            ):
                resources.append(backend)
        object.__setattr__(self, "resources", tuple(resources))


class CoreRuntime:
    """Own reusable pipeline resource identities for one process lifetime.

    The default composition captures model-related environment variables when
    the runtime is constructed. Registered resources load lazily and are shared
    by every job run through this instance. ``reset()`` discards their cached
    state while retaining captured configuration paths.
    """

    def __init__(
        self,
        pipeline: Pipeline | None = None,
        *,
        registry_path: PathLike | None = None,
        metallicity_checkpoint: PathLike | None = None,
        metallicity_atom_init: PathLike | None = None,
        close_hooks: Iterable[Callable[[], None]] = (),
    ) -> None:
        """Capture composition, model configuration, and shutdown hooks."""
        if pipeline is not None and any(
            value is not None
            for value in (
                registry_path,
                metallicity_checkpoint,
                metallicity_atom_init,
            )
        ):
            raise ValueError(
                "Model configuration overrides cannot be combined with pipeline."
            )

        self._registry_path = _capture_path(registry_path, "GOLDILOCKS_MODEL_REGISTRY")
        self._metallicity_checkpoint = _capture_path(
            metallicity_checkpoint, "GOLDILOCKS_METALLICITY_CHECKPOINT"
        )
        self._metallicity_atom_init = _capture_path(
            metallicity_atom_init, "GOLDILOCKS_METALLICITY_ATOM_INIT"
        )
        self._condition = Condition()
        self._active_calls = 0
        self._active_threads: dict[int, int] = {}
        self._transitioning = False
        self._transition_owner: int | None = None
        self._transition_operation: str | None = None
        self._closed = False
        self._closing = False
        self._close_error: BaseException | None = None
        self._close_hooks = tuple(close_hooks)
        self._pipeline: Pipeline | None = pipeline or self._build_default_pipeline()
        self._resources = self._pipeline.resources
        self._owned_resources: tuple[RuntimeResource, ...] = ()
        self._claim_resource_ownership()

    @property
    def registry_path(self) -> str | None:
        """Return the model-registry path captured by this runtime."""
        return self._registry_path

    @property
    def is_closed(self) -> bool:
        """Return whether deterministic shutdown has completed, including failure."""
        with self._condition:
            return self._closed

    @property
    def is_closing(self) -> bool:
        """Return whether shutdown is awaiting jobs or releasing resources."""
        with self._condition:
            return self._closing

    def run(self, request: CoreJobRequest) -> CoreResult:
        """Run one job while retaining a lease on this runtime's resources."""
        pipeline = self._acquire_pipeline()
        try:
            return _run_pipeline(request, pipeline)
        finally:
            self._release_pipeline()

    def reset(self) -> None:
        """Reset owned resources after active jobs finish.

        Reset retains the pipeline and captured configuration paths. Every
        registered ``RuntimeResource`` discards cached initialization so its
        next use retries lazily. It cannot be called from this runtime's active
        job because waiting for that job would deadlock.
        """
        with self._condition:
            self._reject_active_reentry("reset")
            self._begin_transition("reset")
            if self._closed:
                self._finish_transition()
                raise RuntimeError("CoreRuntime is closed.")
            while self._active_calls:
                self._condition.wait()
            resources = self._resources

        try:
            for resource in resources:
                resource.reset()
        finally:
            with self._condition:
                self._finish_transition()

    def close(self) -> None:
        """Close owned resources after active jobs finish, exactly once.

        ``is_closing`` becomes true as soon as shutdown is requested, so new
        calls fail promptly. Concurrent callers wait until resources and hooks
        complete, then receive the same shutdown failure if one occurred.
        ``is_closed`` becomes true only after that deterministic shutdown.
        """
        with self._condition:
            self._reject_active_reentry("close")
            if self._closing:
                if self._transition_owner == get_ident():
                    raise RuntimeError(
                        "CoreRuntime.close() cannot re-enter a runtime transition."
                    )
                while self._closing:
                    self._condition.wait()
                if self._close_error is not None:
                    raise self._close_error
                return
            if self._closed:
                if self._close_error is not None:
                    raise self._close_error
                return
            if self._transition_owner == get_ident():
                raise RuntimeError(
                    "CoreRuntime.close() cannot re-enter a runtime transition."
                )
            self._closing = True
            self._begin_transition("close")
            while self._active_calls:
                self._condition.wait()
            resources = self._resources
            self._resources = ()
            self._pipeline = None

        errors: list[BaseException] = []
        for resource in reversed(resources):
            try:
                resource.close()
            except BaseException as error:  # pragma: no cover - resource policy
                errors.append(error)
        for hook in reversed(self._close_hooks):
            try:
                hook()
            except BaseException as error:  # pragma: no cover - hook policy
                errors.append(error)

        with self._condition:
            self._close_error = errors[0] if errors else None
            self._closed = True
            self._closing = False
            self._finish_transition()
        self._release_resource_ownership()

        if self._close_error is not None:
            raise self._close_error

    def __enter__(self) -> CoreRuntime:
        """Return this open runtime for context-managed use."""
        with self._condition:
            if self._closed:
                raise RuntimeError("CoreRuntime is closed.")
            if self._closing:
                raise RuntimeError("CoreRuntime is closing.")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close this runtime when leaving a context manager."""
        self.close()

    def _claim_resource_ownership(self) -> None:
        """Claim this runtime's stateful resources by object identity."""
        with _resource_owner_lock:
            for resource in self._resources:
                owner_reference = _resource_owners.get(id(resource))
                if owner_reference is None:
                    continue
                if owner_reference() is not None:
                    raise RuntimeError(
                        "RuntimeResource is already owned by another CoreRuntime."
                    )
                del _resource_owners[id(resource)]

            self._owned_resources = self._resources
            for resource in self._owned_resources:
                resource_id = id(resource)
                _resource_owners[resource_id] = weakref.ref(
                    self,
                    lambda owner_reference, resource_id=resource_id: (
                        _discard_abandoned_resource_owner(resource_id, owner_reference)
                    ),
                )

    def _release_resource_ownership(self) -> None:
        """Release resource identities after deterministic shutdown completes."""
        with _resource_owner_lock:
            for resource in self._owned_resources:
                owner_reference = _resource_owners.get(id(resource))
                if owner_reference is not None and owner_reference() is self:
                    del _resource_owners[id(resource)]
            self._owned_resources = ()

    def _build_default_pipeline(self) -> Pipeline:
        """Build a lazy default pipeline from captured configuration."""
        return Pipeline(
            kmesh=default_kmesh_advisor(
                registry_path=self._registry_path,
                metallicity_checkpoint=self._metallicity_checkpoint,
                metallicity_atom_init=self._metallicity_atom_init,
                use_environment=False,
            )
        )

    def _begin_transition(self, operation: str) -> None:
        """Claim exclusive reset/close ownership under the condition lock."""
        thread_id = get_ident()
        if self._transition_owner == thread_id:
            raise RuntimeError(
                f"CoreRuntime.{operation}() cannot re-enter a runtime transition."
            )
        while self._transitioning:
            self._condition.wait()
        self._transitioning = True
        self._transition_owner = thread_id
        self._transition_operation = operation

    def _finish_transition(self) -> None:
        """Release reset/close ownership under the condition lock."""
        self._transitioning = False
        self._transition_owner = None
        self._transition_operation = None
        self._condition.notify_all()

    def _reject_active_reentry(self, operation: str) -> None:
        """Reject transitions that would wait for the caller's own job lease."""
        if self._active_threads.get(get_ident(), 0):
            raise RuntimeError(
                f"CoreRuntime.{operation}() cannot be called from an active run "
                "on the same runtime."
            )

    def _acquire_pipeline(self) -> Pipeline:
        """Lease the current pipeline against concurrent reset or close."""
        with self._condition:
            if self._closed:
                raise RuntimeError("CoreRuntime is closed.")
            if self._closing:
                raise RuntimeError("CoreRuntime is closing.")
            thread_id = get_ident()
            while self._transitioning:
                if self._transition_owner == thread_id:
                    raise RuntimeError(
                        "CoreRuntime.run() cannot be called while "
                        f"{self._transition_operation}() is in progress."
                    )
                self._condition.wait()
            if self._closed:
                raise RuntimeError("CoreRuntime is closed.")
            if self._pipeline is None:  # pragma: no cover - lifecycle invariant
                raise RuntimeError("CoreRuntime has no active Pipeline.")
            self._active_calls += 1
            self._active_threads[thread_id] = self._active_threads.get(thread_id, 0) + 1
            return self._pipeline

    def _release_pipeline(self) -> None:
        """Release one active-job lease."""
        with self._condition:
            thread_id = get_ident()
            self._active_calls -= 1
            active_here = self._active_threads[thread_id] - 1
            if active_here:
                self._active_threads[thread_id] = active_here
            else:
                del self._active_threads[thread_id]
            if not self._active_calls:
                self._condition.notify_all()


_resource_owner_lock = RLock()
_resource_owners: dict[int, weakref.ReferenceType[CoreRuntime]] = {}


def _discard_abandoned_resource_owner(
    resource_id: int,
    owner_reference: weakref.ReferenceType[CoreRuntime],
) -> None:
    """Remove an owner entry only when its weak owner is finalized."""
    with _resource_owner_lock:
        if _resource_owners.get(resource_id) is owner_reference:
            del _resource_owners[resource_id]


_default_runtime: CoreRuntime | None = None
_default_runtime_lock = RLock()


def _capture_path(explicit: PathLike | None, environment_name: str) -> str | None:
    """Capture an explicit path or one environment value as a string."""
    if explicit is not None:
        return str(explicit)
    return os.environ.get(environment_name)


def get_default_runtime() -> CoreRuntime:
    """Return the resettable process-level runtime used by convenience calls."""
    global _default_runtime
    with _default_runtime_lock:
        if _default_runtime is None or _default_runtime.is_closed:
            _default_runtime = CoreRuntime()
        return _default_runtime


def reset_default_runtime() -> None:
    """Close and discard the process runtime, recapturing config on next use."""
    global _default_runtime
    with _default_runtime_lock:
        runtime = _default_runtime
        _default_runtime = None
        if runtime is not None:
            runtime.close()


def run_core_job(
    request: CoreJobRequest,
    *,
    pipeline: Pipeline | None = None,
    runtime: CoreRuntime | None = None,
) -> CoreResult:
    """Run a Core job request through the configured staged pipeline.

    Args:
        request: Serializable job data: structure input, intent, hints,
            pseudopotential metadata, mode, and optional output directory.
        pipeline: Optional stateless executable stage composition for this call.
        runtime: Optional long-lived resource owner shared across calls. Pass
            either ``pipeline`` or ``runtime``, not both. When both are omitted,
            the resettable process-level default runtime is reused.

    Returns:
        A ``CoreResult`` containing the stage records, scientific records,
        generated files when requested, and bundle record for bundle mode.

    Raises:
        ValueError: If the job mode is unsupported, bundle mode lacks
            ``output_dir``, a stateful pipeline bypasses a runtime owner, or a
            downstream stage rejects its inputs.
    """
    if pipeline is not None and runtime is not None:
        raise ValueError("Pass pipeline or runtime, not both.")
    if pipeline is not None:
        if pipeline.resources:
            raise ValueError(
                "A Pipeline with RuntimeResource values requires CoreRuntime ownership."
            )
        return _run_pipeline(request, pipeline)
    if runtime is not None:
        return runtime.run(request)

    with _default_runtime_lock:
        active_runtime = get_default_runtime()
        active_pipeline = active_runtime._acquire_pipeline()
    try:
        return _run_pipeline(request, active_pipeline)
    finally:
        active_runtime._release_pipeline()


def _run_pipeline(request: CoreJobRequest, active_pipeline: Pipeline) -> CoreResult:
    """Run one request with a resolved executable pipeline."""
    stages: list[StageRecord] = []
    structure = load_structure(request.structure)
    stages.append(StageRecord(name="load"))

    analysis = active_pipeline.analyze(structure)
    stages.append(
        StageRecord(
            name="analyze",
            warnings=(*analysis.disorder_warnings, *analysis.analysis_warnings),
        )
    )

    advice = active_pipeline.advise(analysis, request.intent, request.hints)
    advice_warnings = _advice_warnings(advice)
    stages.append(StageRecord(name="advise", warnings=advice_warnings))

    k_points = active_pipeline.kmesh(structure, request.hints, advice.k_points)
    stages.append(StageRecord(name="kmesh", warnings=k_points.provenance.warnings))

    selection = active_pipeline.select(
        structure,
        advice,
        k_points,
        tuple(request.pseudo_metadata),
    )
    stages.append(StageRecord(name="select", warnings=selection.warnings))

    warnings = _unique_warnings(
        analysis.disorder_warnings,
        analysis.analysis_warnings,
        advice_warnings,
        k_points.provenance.warnings,
        selection.warnings,
    )
    generated_files: tuple[GeneratedFile, ...] = ()
    bundle: BundleRecord | None = None

    if request.mode in {"generate", "bundle"}:
        generated_files = active_pipeline.generate(
            structure,
            request.intent,
            advice,
            selection,
        )
        stages.append(StageRecord(name="generate"))

    if request.mode == "bundle":
        # output_dir is guaranteed non-None for bundle mode by
        # CoreJobRequest.__post_init__.
        in_progress = CoreResult(
            intent=request.intent,
            analysis=analysis,
            advice=advice,
            selection=selection,
            generated_files=generated_files,
            warnings=warnings,
            stages=tuple(stages),
        )
        bundle = active_pipeline.bundle(in_progress, request.output_dir)
        stages.append(StageRecord(name="bundle"))

    return CoreResult(
        intent=request.intent,
        analysis=analysis,
        advice=advice,
        selection=selection,
        generated_files=generated_files,
        warnings=warnings,
        bundle=bundle,
        stages=tuple(stages),
    )


def _advice_warnings(advice: ParameterAdvice) -> tuple[str, ...]:
    """Return actionable warnings from every Advise sub-decision."""
    return _unique_warnings(
        advice.k_points.provenance.warnings,
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


def recommend(
    structure: StructureInput,
    *,
    intent: CalculationIntent | None = None,
    hints: CalculationHints | None = None,
    pseudo_metadata: list[PseudoMetadata] | None = None,
    pipeline: Pipeline | None = None,
    runtime: CoreRuntime | None = None,
) -> CoreResult:
    """Run Load → Analyze → Advise → Kmesh → Select.

    Args:
        structure: Structure object or structure file path.
        intent: Optional calculation intent.
        hints: Optional operator hints.
        pseudo_metadata: Available pseudopotential metadata.
        pipeline: Optional stage backend composition for this call.
        runtime: Optional reusable runtime. Mutually exclusive with pipeline.

    Returns:
        ``CoreResult`` containing analysis, advice, selection, and warnings.
    """
    return run_core_job(
        CoreJobRequest(
            structure=structure,
            intent=intent or CalculationIntent(),
            hints=hints or CalculationHints(),
            mode="recommend",
            pseudo_metadata=tuple(pseudo_metadata or ()),
        ),
        pipeline=pipeline,
        runtime=runtime,
    )


def generate(
    structure: StructureInput,
    *,
    intent: CalculationIntent | None = None,
    hints: CalculationHints | None = None,
    pseudo_metadata: list[PseudoMetadata] | None = None,
    pipeline: Pipeline | None = None,
    runtime: CoreRuntime | None = None,
) -> CoreResult:
    """Run Load → Analyze → Advise → Kmesh → Select → Generate.

    Args:
        structure: Structure object or structure file path.
        intent: Optional calculation intent.
        hints: Optional operator hints.
        pseudo_metadata: Available pseudopotential metadata.
        pipeline: Optional stage backend composition for this call.
        runtime: Optional reusable runtime. Mutually exclusive with pipeline.

    Returns:
        ``CoreResult`` with generated files attached.

    Raises:
        ValueError: If generation is requested with unsupported intent or
            incomplete selections.
    """
    return run_core_job(
        CoreJobRequest(
            structure=structure,
            intent=intent or CalculationIntent(),
            hints=hints or CalculationHints(),
            mode="generate",
            pseudo_metadata=tuple(pseudo_metadata or ()),
        ),
        pipeline=pipeline,
        runtime=runtime,
    )


def write_bundle(
    structure: StructureInput,
    output_dir: str | Path,
    *,
    intent: CalculationIntent | None = None,
    hints: CalculationHints | None = None,
    pseudo_metadata: list[PseudoMetadata] | None = None,
    pipeline: Pipeline | None = None,
    runtime: CoreRuntime | None = None,
) -> CoreResult:
    """Run the full Core pipeline and write a portable bundle directory.

    Args:
        structure: Structure object or structure file path.
        output_dir: New bundle output directory. Existing destinations are
            refused.
        intent: Optional calculation intent.
        hints: Optional operator hints.
        pseudo_metadata: Available pseudopotential metadata.
        pipeline: Optional stage backend composition for this call.
        runtime: Optional reusable runtime. Mutually exclusive with pipeline.

    Returns:
        ``CoreResult`` with generated files, bundle record, stages, and warnings.

    Raises:
        FileExistsError: If the bundle output directory already exists.
        OSError: If bundle staging or publication fails.
        ValueError: If generation or bundle writing rejects its inputs.
    """
    return run_core_job(
        CoreJobRequest(
            structure=structure,
            intent=intent or CalculationIntent(),
            hints=hints or CalculationHints(),
            mode="bundle",
            pseudo_metadata=tuple(pseudo_metadata or ()),
            output_dir=str(output_dir),
        ),
        pipeline=pipeline,
        runtime=runtime,
    )
