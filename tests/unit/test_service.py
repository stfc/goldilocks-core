from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from threading import Barrier, Event
from typing import Any

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core import (
    CalculationDraft,
    CalculationHints,
    ComputeRequest,
    InMemoryStructureSource,
    PresetSelection,
    Runtime,
    Service,
)
from goldilocks_core.kmesh.resolve import KPointSelection
from goldilocks_core.provenance import Provenance
from goldilocks_core.pseudo.metadata import PseudoMetadata
from goldilocks_core.runtime.dispatch import Dispatcher


def make_request(*, k_grid=(2, 2, 1)) -> ComputeRequest:
    return ComputeRequest(
        draft=CalculationDraft(
            structure=InMemoryStructureSource(
                Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])
            ),
            hints=CalculationHints(k_grid=k_grid, pseudo_type="NC"),
            pseudo_metadata=(
                PseudoMetadata(
                    filepath="/pseudo/Si.UPF",
                    filename="Si.UPF",
                    header_format="attr",
                    provider="sssp",
                    accuracy="efficiency",
                    element="Si",
                    pseudo_type="NC",
                    functional="PBEsol",
                    relativistic="scalar",
                    cutoffs={"ecutwfc_ry": 35, "ecutrho_ry": 140},
                    source_identifier="synthetic/Si.UPF",
                ),
            ),
        ),
        selection=PresetSelection("recommend"),
    )


@pytest.mark.parametrize("owned", (True, False))
def test_service_lifecycle_preserves_runtime_ownership(owned) -> None:
    service = Service(None if owned else Runtime())
    runtime = service.runtime
    request = make_request()
    with service:
        assert service.compute(request).records[KPointSelection]["grid"] == [2, 2, 1]
    service.close()
    assert service.is_closed
    assert runtime.is_closed is owned
    for operation in (
        lambda: service.compute(request),
        service.capabilities,
        lambda: service.inspect_structure(request.draft.structure),
    ):
        with pytest.raises(RuntimeError):
            operation()
    if not owned:
        with Service(runtime) as replacement:
            assert replacement.compute(request).records[KPointSelection]["grid"] == [
                2,
                2,
                1,
            ]
    runtime.close()


def test_computations_and_discovery_are_not_serialized() -> None:
    entered = Barrier(3)
    release = Event()

    class BlockingBackend:
        def __call__(self, structure: Structure) -> dict[str, Any]:
            entered.wait(timeout=2)
            assert release.wait(timeout=2)
            return {
                "grid": [2, 2, 2],
                "shift": [0, 0, 0],
                "mesh_type": "monkhorst-pack",
                "provenance": Provenance(source="model", reason="test"),
            }

        def close(self) -> None:
            pass

    request = make_request(k_grid=None)
    with (
        Runtime(kmesh_service=BlockingBackend()) as runtime,
        Service(runtime) as service,
        ThreadPoolExecutor(max_workers=3) as pool,
    ):
        computations = [pool.submit(service.compute, request) for _ in range(2)]
        try:
            entered.wait(timeout=2)
            capabilities = pool.submit(service.capabilities)
            assert (
                capabilities.result(timeout=0.5)["tasks"][0]["id"] == "scf_single_point"
            )
            inspection = pool.submit(service.inspect_structure, request.draft.structure)
            assert (
                inspection.result(timeout=0.5)["structure"]["reduced_formula"] == "Si"
            )
        finally:
            release.set()
        for computation in computations:
            assert computation.result(timeout=2).records[KPointSelection]["grid"] == [
                2,
                2,
                2,
            ]


def test_concurrent_first_computations_wait_for_default_task_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registration_started = Event()
    release_registration = Event()
    second_started = Event()
    original_register = Dispatcher.register

    def blocking_register(dispatcher: Dispatcher, handler) -> None:
        registration_started.set()
        assert release_registration.wait(timeout=2)
        original_register(dispatcher, handler)

    monkeypatch.setattr(Dispatcher, "register", blocking_register)
    request = make_request()
    with Service() as service, ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.compute, request)
        try:
            assert registration_started.wait(timeout=2)

            def run_second():
                second_started.set()
                return service.compute(request)

            second = pool.submit(run_second)
            assert second_started.wait(timeout=2)
            with pytest.raises(FutureTimeoutError):
                second.result(timeout=0.1)
        finally:
            release_registration.set()
        for computation in (first, second):
            assert computation.result(timeout=2).records[KPointSelection]["grid"] == [
                2,
                2,
                1,
            ]
