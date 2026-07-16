from __future__ import annotations

import gc
import weakref
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from time import sleep

import numpy as np
import pytest
from pymatgen.core import Lattice, Structure

import goldilocks_core.jobs as jobs
from goldilocks_core import (
    CoreJobRequest,
    CoreRuntime,
    Pipeline,
    recommend,
    reset_default_runtime,
    run_core_job,
)
from goldilocks_core.advisors.kindex_advisor import ml_kmesh_advisor
from goldilocks_core.contracts import (
    KPointSelection,
    ModelSpec,
    Provenance,
    StructureFeatureVector,
)


class FakeQRF:
    """Minimal QRF model returning fixed lower, median, and upper values."""

    q = [0.05, 0.5, 0.95]

    def predict(self, features):
        return np.array([[0.2], [0.25], [0.3]])


class TrackingResource:
    """Record lifecycle calls and optionally block or fail during close."""

    def __init__(
        self,
        *,
        close_started: Event | None = None,
        release_close: Event | None = None,
        close_error: BaseException | None = None,
    ) -> None:
        self.close_started = close_started
        self.release_close = release_close
        self.close_error = close_error
        self.reset_calls = 0
        self.close_calls = 0

    def reset(self) -> None:
        """Record one reset."""
        self.reset_calls += 1

    def close(self) -> None:
        """Record one close after any requested test synchronization."""
        self.close_calls += 1
        if self.close_started is not None:
            self.close_started.set()
        if self.release_close is not None:
            assert self.release_close.wait(timeout=5)
        if self.close_error is not None:
            raise self.close_error


def make_structure() -> Structure:
    """Build a small structure for runtime integration tests."""
    return Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])


def make_request() -> CoreJobRequest:
    """Build a model-backed recommendation request."""
    return CoreJobRequest(structure=make_structure())


def patch_inference_artifacts(monkeypatch, tmp_path, qrf_loader, metal_loader) -> None:
    """Install portable local supporting artifacts and fake model operations."""
    checkpoint = tmp_path / "metal.ckpt"
    atom_table = tmp_path / "atom.json"
    checkpoint.write_bytes(b"checkpoint")
    atom_table.write_bytes(b"atom table")
    monkeypatch.setenv("GOLDILOCKS_METALLICITY_CHECKPOINT", str(checkpoint))
    monkeypatch.setenv("GOLDILOCKS_METALLICITY_ATOM_INIT", str(atom_table))
    monkeypatch.setattr("goldilocks_core.ml.models.load_model", qrf_loader)
    monkeypatch.setattr(
        "goldilocks_core.ml.metallicity.load_metallicity_model", metal_loader
    )
    monkeypatch.setattr(
        "goldilocks_core.ml.kdistance_features.extract_qrf_features",
        lambda structure, model, atom_init, settings: StructureFeatureVector(
            values=np.zeros(483),
            feature_names=[f"feature_{index}" for index in range(483)],
        ),
    )


def test_runtime_loads_each_artifact_once_across_jobs_and_concurrent_calls(
    monkeypatch, tmp_path
) -> None:
    """One runtime shares successful lazy initialization across all callers."""
    counts = {"qrf": 0, "metal": 0}
    counts_lock = Lock()

    def load_qrf(spec):
        with counts_lock:
            counts["qrf"] += 1
        sleep(0.05)
        return FakeQRF()

    def load_metal(path):
        with counts_lock:
            counts["metal"] += 1
        return object()

    patch_inference_artifacts(monkeypatch, tmp_path, load_qrf, load_metal)
    runtime = CoreRuntime()

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(runtime.run, [make_request() for _ in range(4)]))
    runtime.run(make_request())

    assert counts == {"qrf": 1, "metal": 1}
    assert all(
        result.selection.k_points.provenance.source == "model" for result in results
    )


def test_runtime_reset_retries_a_cached_initialization_failure(
    monkeypatch, tmp_path
) -> None:
    """Reset rebuilds the default advisor so a transient load can succeed."""
    attempts = 0

    def load_qrf(spec):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("temporary artifact outage")
        return FakeQRF()

    patch_inference_artifacts(monkeypatch, tmp_path, load_qrf, lambda path: object())
    runtime = CoreRuntime()

    first = runtime.run(make_request())
    second = runtime.run(make_request())
    runtime.reset()
    retried = runtime.run(make_request())

    assert attempts == 2
    assert first.selection.k_points.provenance.source == "fallback"
    assert second.selection.k_points.provenance.source == "fallback"
    assert retried.selection.k_points.provenance.source == "model"


def test_runtime_reset_waits_for_concurrent_first_use(monkeypatch, tmp_path) -> None:
    """Reset cannot discard an advisor while its first load is in flight."""
    load_started = Event()
    release_load = Event()
    attempts = 0

    def load_qrf(spec):
        nonlocal attempts
        attempts += 1
        load_started.set()
        assert release_load.wait(timeout=5)
        return FakeQRF()

    patch_inference_artifacts(monkeypatch, tmp_path, load_qrf, lambda path: object())
    runtime = CoreRuntime()

    with ThreadPoolExecutor(max_workers=2) as executor:
        run_future = executor.submit(runtime.run, make_request())
        assert load_started.wait(timeout=5)
        reset_future = executor.submit(runtime.reset)
        sleep(0.05)
        assert not reset_future.done()
        release_load.set()
        assert run_future.result().selection.k_points.provenance.source == "model"
        reset_future.result()

    assert runtime.run(make_request()).selection.k_points.provenance.source == "model"
    assert attempts == 2


def test_runtime_captures_environment_until_replaced(monkeypatch, tmp_path) -> None:
    """Environment changes affect replacement runtimes, never a live runtime."""
    first_registry = tmp_path / "first.toml"
    second_registry = tmp_path / "second.toml"
    seen_paths: list[str | None] = []

    def fail_config(path=None, *, use_environment=True):
        seen_paths.append(None if path is None else str(path))
        raise OSError("registry unavailable")

    monkeypatch.setenv("GOLDILOCKS_MODEL_REGISTRY", str(first_registry))
    monkeypatch.setattr(
        "goldilocks_core.advisors.kdistance_advisor.load_default_qrf_config",
        fail_config,
    )
    runtime = CoreRuntime()
    monkeypatch.setenv("GOLDILOCKS_MODEL_REGISTRY", str(second_registry))

    runtime.run(make_request())
    runtime.reset()
    runtime.run(make_request())
    replacement = CoreRuntime()
    replacement.run(make_request())

    assert runtime.registry_path == str(first_registry)
    assert replacement.registry_path == str(second_registry)
    assert seen_paths == [
        str(first_registry),
        str(first_registry),
        str(second_registry),
    ]


def test_process_convenience_reuses_and_can_replace_default_runtime(
    monkeypatch, tmp_path
) -> None:
    """Zero-config calls share one resettable process runtime."""
    loads = 0

    def load_qrf(spec):
        nonlocal loads
        loads += 1
        return FakeQRF()

    patch_inference_artifacts(monkeypatch, tmp_path, load_qrf, lambda path: object())

    recommend(make_structure())
    run_core_job(make_request())
    assert loads == 1

    reset_default_runtime()
    recommend(make_structure())
    assert loads == 2


def test_runtime_preserves_explicit_pipeline_composition() -> None:
    """A caller-composed Pipeline remains the executable composition."""
    calls = 0

    def custom_kmesh(structure, hints, advice):
        nonlocal calls
        calls += 1
        return KPointSelection(
            grid=(9, 8, 7),
            shift=(0, 0, 0),
            mesh_type=advice.mesh_type,
            provenance=Provenance(source="model", reason="custom composition"),
        )

    pipeline = Pipeline(kmesh=custom_kmesh)
    runtime = CoreRuntime(pipeline=pipeline)

    first = recommend(make_structure(), runtime=runtime)
    second = run_core_job(make_request(), pipeline=pipeline)

    assert first.selection.k_points.grid == (9, 8, 7)
    assert second.selection.k_points.grid == (9, 8, 7)
    assert calls == 2
    runtime.reset()
    with pytest.raises(ValueError, match="pipeline or runtime"):
        run_core_job(make_request(), pipeline=pipeline, runtime=runtime)


def test_stateful_pipeline_rejects_a_second_runtime_owner() -> None:
    """One resource identity cannot be owned by two runtimes at once."""
    resource = TrackingResource()
    pipeline = Pipeline(kmesh=_fixed_kmesh, resources=(resource,))
    runtime = CoreRuntime(pipeline=pipeline)

    with pytest.raises(RuntimeError, match="already owned"):
        CoreRuntime(pipeline=pipeline)

    runtime.close()


def test_direct_pipeline_execution_rejects_stateful_resources() -> None:
    """The one-call path cannot execute resources without a runtime owner."""
    resource = TrackingResource()
    pipeline = Pipeline(kmesh=_fixed_kmesh, resources=(resource,))

    with pytest.raises(ValueError, match="requires CoreRuntime ownership"):
        run_core_job(make_request(), pipeline=pipeline)

    assert resource.reset_calls == 0
    assert resource.close_calls == 0


def test_runtime_reset_retains_resource_ownership_until_close() -> None:
    """Reset keeps ownership, while completed close permits reacquisition."""
    resource = TrackingResource()
    pipeline = Pipeline(kmesh=_fixed_kmesh, resources=(resource,))
    runtime = CoreRuntime(pipeline=pipeline)

    runtime.reset()
    with pytest.raises(RuntimeError, match="already owned"):
        CoreRuntime(pipeline=pipeline)

    runtime.close()
    replacement = CoreRuntime(pipeline=pipeline)
    replacement.close()

    assert resource.reset_calls == 1
    assert resource.close_calls == 2


def test_abandoned_runtime_is_collected_and_its_resource_can_be_reacquired() -> None:
    """Weak ownership entries never keep an unclosed runtime alive."""
    resource = TrackingResource()
    pipeline = Pipeline(kmesh=_fixed_kmesh, resources=(resource,))
    runtime = CoreRuntime(pipeline=pipeline)
    runtime_reference = weakref.ref(runtime)

    del runtime
    gc.collect()

    assert runtime_reference() is None
    replacement = CoreRuntime(pipeline=pipeline)
    replacement.close()


def test_stale_resource_identity_entry_cannot_block_reacquisition() -> None:
    """A dead owner keyed by a reused object id is discarded before claiming."""
    stale_resource = TrackingResource()
    stale_runtime = CoreRuntime(
        pipeline=Pipeline(kmesh=_fixed_kmesh, resources=(stale_resource,))
    )
    stale_reference = weakref.ref(stale_runtime)
    del stale_runtime
    gc.collect()
    assert stale_reference() is None

    resource = TrackingResource()
    pipeline = Pipeline(kmesh=_fixed_kmesh, resources=(resource,))
    with jobs._resource_owner_lock:
        jobs._resource_owners[id(resource)] = stale_reference

    runtime = CoreRuntime(pipeline=pipeline)
    with pytest.raises(RuntimeError, match="already owned"):
        CoreRuntime(pipeline=pipeline)
    runtime.close()

    with jobs._resource_owner_lock:
        assert id(resource) not in jobs._resource_owners


def test_runtime_close_releases_default_model_references(monkeypatch, tmp_path) -> None:
    """Closing a runtime drops its references to lazily loaded resources."""
    model_references: list[weakref.ReferenceType[FakeQRF]] = []

    def load_qrf(spec):
        model = FakeQRF()
        model_references.append(weakref.ref(model))
        return model

    patch_inference_artifacts(monkeypatch, tmp_path, load_qrf, lambda path: object())
    runtime = CoreRuntime()
    runtime.run(make_request())

    runtime.close()
    gc.collect()

    assert model_references[0]() is None


def test_runtime_close_is_idempotent_and_context_managed() -> None:
    """Context exit runs future resource hooks once and rejects later jobs."""
    closed: list[str] = []
    pipeline = Pipeline(kmesh=_fixed_kmesh)

    with CoreRuntime(
        pipeline=pipeline,
        close_hooks=(lambda: closed.append("first"), lambda: closed.append("second")),
    ) as runtime:
        assert runtime.run(make_request()).selection.k_points.grid == (2, 2, 2)

    runtime.close()

    assert closed == ["second", "first"]
    assert runtime.is_closed
    with pytest.raises(RuntimeError, match="closed"):
        runtime.run(make_request())


def make_model_spec() -> ModelSpec:
    """Build one portable custom model specification."""
    return ModelSpec(
        name="runtime-model",
        version="v1",
        model_type="random_forest",
        target="k_index",
        feature_set="cslr",
        source="local",
        location="unused.joblib",
    )


def patch_ml_selection(monkeypatch) -> None:
    """Avoid feature extraction while testing custom model lifecycle behavior."""
    monkeypatch.setattr(
        "goldilocks_core.advisors.kindex_advisor._advise_kpoints",
        lambda structure, model, spec: KPointSelection(
            grid=(2, 2, 2),
            shift=(0, 0, 0),
            mesh_type="monkhorst-pack",
            provenance=Provenance(source="model", reason="lifecycle fixture"),
        ),
    )


def test_custom_model_resource_loads_once_across_runtime_jobs(monkeypatch) -> None:
    """A custom ML Pipeline backend is registered as a runtime resource."""
    loads = 0

    def load_model(spec):
        nonlocal loads
        loads += 1
        return object()

    patch_ml_selection(monkeypatch)
    monkeypatch.setattr(
        "goldilocks_core.advisors.kindex_advisor.load_model", load_model
    )
    runtime = CoreRuntime(pipeline=Pipeline(kmesh=ml_kmesh_advisor(make_model_spec())))

    runtime.run(make_request())
    runtime.run(make_request())

    assert loads == 1


def test_custom_model_resource_caches_failure_until_runtime_reset(monkeypatch) -> None:
    """Reset clears a custom model backend's cached initialization failure."""
    attempts = 0

    def load_model(spec):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("temporary model outage")
        return object()

    patch_ml_selection(monkeypatch)
    monkeypatch.setattr(
        "goldilocks_core.advisors.kindex_advisor.load_model", load_model
    )
    runtime = CoreRuntime(pipeline=Pipeline(kmesh=ml_kmesh_advisor(make_model_spec())))

    with pytest.raises(OSError, match="temporary model outage"):
        runtime.run(make_request())
    with pytest.raises(OSError, match="temporary model outage"):
        runtime.run(make_request())
    runtime.reset()
    runtime.run(make_request())

    assert attempts == 2


def test_custom_model_resource_first_load_is_thread_safe(monkeypatch) -> None:
    """Concurrent jobs deserialize one custom model exactly once."""
    loads = 0
    load_lock = Lock()

    def load_model(spec):
        nonlocal loads
        with load_lock:
            loads += 1
        sleep(0.05)
        return object()

    patch_ml_selection(monkeypatch)
    monkeypatch.setattr(
        "goldilocks_core.advisors.kindex_advisor.load_model", load_model
    )
    runtime = CoreRuntime(pipeline=Pipeline(kmesh=ml_kmesh_advisor(make_model_spec())))

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(runtime.run, [make_request() for _ in range(4)]))

    assert loads == 1


def test_custom_model_resource_reset_and_close_release_model_references(
    monkeypatch,
) -> None:
    """Reset and close release custom model references before lazy reuse."""
    references: list[weakref.ReferenceType[FakeQRF]] = []

    def load_model(spec):
        model = FakeQRF()
        references.append(weakref.ref(model))
        return model

    patch_ml_selection(monkeypatch)
    monkeypatch.setattr(
        "goldilocks_core.advisors.kindex_advisor.load_model", load_model
    )
    runtime = CoreRuntime(pipeline=Pipeline(kmesh=ml_kmesh_advisor(make_model_spec())))

    runtime.run(make_request())
    runtime.reset()
    gc.collect()
    assert references[0]() is None

    runtime.run(make_request())
    runtime.close()
    gc.collect()
    assert references[1]() is None


@pytest.mark.parametrize("operation_name", ["reset", "close"])
def test_runtime_rejects_transition_from_its_active_run(operation_name: str) -> None:
    """A backend cannot self-deadlock by transitioning its active runtime."""
    runtime: CoreRuntime

    def reentrant_kmesh(structure, hints, advice):
        operation = getattr(runtime, operation_name)
        with pytest.raises(RuntimeError, match="active run"):
            operation()
        return _fixed_kmesh(structure, hints, advice)

    runtime = CoreRuntime(pipeline=Pipeline(kmesh=reentrant_kmesh))
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(runtime.run, make_request()).result(timeout=1)

    assert result.selection.k_points.grid == (2, 2, 2)
    assert not runtime.is_closed


def test_concurrent_close_waits_for_resources_and_hooks() -> None:
    """Close callers wait for one complete shutdown while runs fail promptly."""
    resource_started = Event()
    release_resource = Event()
    hook_started = Event()
    release_hook = Event()
    resource = TrackingResource(
        close_started=resource_started,
        release_close=release_resource,
    )
    pipeline = Pipeline(kmesh=_fixed_kmesh, resources=(resource,))

    def close_hook() -> None:
        hook_started.set()
        assert release_hook.wait(timeout=5)

    runtime = CoreRuntime(pipeline=pipeline, close_hooks=(close_hook,))

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_close = executor.submit(runtime.close)
        assert resource_started.wait(timeout=5)
        assert runtime.is_closing
        assert not runtime.is_closed

        second_close = executor.submit(runtime.close)
        sleep(0.05)
        assert not second_close.done()
        with pytest.raises(RuntimeError, match="closing"):
            runtime.run(make_request())

        release_resource.set()
        assert hook_started.wait(timeout=5)
        with pytest.raises(RuntimeError, match="already owned"):
            CoreRuntime(pipeline=pipeline)
        assert not second_close.done()

        release_hook.set()
        first_close.result(timeout=5)
        second_close.result(timeout=5)

    assert resource.close_calls == 1
    assert runtime.is_closed
    assert not runtime.is_closing
    replacement = CoreRuntime(pipeline=pipeline)
    replacement.close()


def test_close_propagates_shutdown_failure_to_all_callers() -> None:
    """All close callers observe the recorded shutdown failure after cleanup."""
    hook_started = Event()
    release_hook = Event()
    resource = TrackingResource(close_error=OSError("resource shutdown failed"))

    def close_hook() -> None:
        hook_started.set()
        assert release_hook.wait(timeout=5)

    runtime = CoreRuntime(
        pipeline=Pipeline(kmesh=_fixed_kmesh, resources=(resource,)),
        close_hooks=(close_hook,),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_close = executor.submit(runtime.close)
        assert hook_started.wait(timeout=5)
        second_close = executor.submit(runtime.close)
        sleep(0.05)
        assert not second_close.done()

        release_hook.set()
        with pytest.raises(OSError, match="resource shutdown failed"):
            first_close.result(timeout=5)
        with pytest.raises(OSError, match="resource shutdown failed"):
            second_close.result(timeout=5)

    assert runtime.is_closed
    assert not runtime.is_closing
    with pytest.raises(OSError, match="resource shutdown failed"):
        runtime.close()


def test_close_waits_for_an_in_flight_run_and_rejects_new_runs() -> None:
    """Close does not interrupt leased work but rejects calls started afterward."""
    run_started = Event()
    release_run = Event()

    def blocking_kmesh(structure, hints, advice):
        run_started.set()
        assert release_run.wait(timeout=5)
        return _fixed_kmesh(structure, hints, advice)

    runtime = CoreRuntime(pipeline=Pipeline(kmesh=blocking_kmesh))

    with ThreadPoolExecutor(max_workers=2) as executor:
        active_run = executor.submit(runtime.run, make_request())
        assert run_started.wait(timeout=5)
        close = executor.submit(runtime.close)
        sleep(0.05)
        assert runtime.is_closing
        assert not close.done()
        with pytest.raises(RuntimeError, match="closing"):
            runtime.run(make_request())

        release_run.set()
        assert active_run.result(timeout=5).selection.k_points.grid == (2, 2, 2)
        close.result(timeout=5)

    assert runtime.is_closed


def test_close_hook_worker_run_fails_without_waiting_for_close() -> None:
    """A close hook can join a worker because the runtime closes first."""
    errors: list[BaseException] = []
    runtime: CoreRuntime

    with ThreadPoolExecutor(max_workers=2) as executor:

        def close_hook() -> None:
            worker = executor.submit(runtime.run, make_request())
            try:
                worker.result(timeout=1)
            except BaseException as error:
                errors.append(error)

        runtime = CoreRuntime(
            pipeline=Pipeline(kmesh=_fixed_kmesh),
            close_hooks=(close_hook,),
        )
        executor.submit(runtime.close).result(timeout=1)

    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    assert "closing" in str(errors[0])


def _fixed_kmesh(structure, hints, advice) -> KPointSelection:
    """Return a fixed valid selection without loading model resources."""
    return KPointSelection(
        grid=(2, 2, 2),
        shift=(0, 0, 0),
        mesh_type=advice.mesh_type,
        provenance=Provenance(source="default", reason="runtime fixture"),
    )
