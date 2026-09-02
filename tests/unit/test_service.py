from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from threading import Event, Lock

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core import (
    CalculationDraft,
    CalculationHints,
    ComputationResult,
    ComputeRequest,
    InMemoryStructureSource,
    PresetSelection,
    Runtime,
    Service,
)
from goldilocks_core.kmesh.resolve import KPointSelection
from goldilocks_core.provenance import Provenance
from goldilocks_core.pseudo.metadata import PseudoCutoffs, PseudoMetadata
from goldilocks_core.runtime.dispatch import Dispatcher


def make_structure() -> Structure:
    return Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])


def make_metadata() -> PseudoMetadata:
    return PseudoMetadata(
        filepath="/pseudo/Si.UPF",
        filename="Si.UPF",
        header_format="attr",
        provider="sssp",
        accuracy="efficiency",
        element="Si",
        pseudo_type="NC",
        functional="PBEsol",
        relativistic="scalar",
        cutoffs=PseudoCutoffs(ecutwfc_ry=35, ecutrho_ry=140),
        source_identifier="synthetic/Si.UPF",
    )


def make_request() -> ComputeRequest:
    return ComputeRequest(
        draft=CalculationDraft(
            structure=InMemoryStructureSource(make_structure()),
            hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
            pseudo_metadata=(make_metadata(),),
        ),
        selection=PresetSelection("recommend"),
    )


def test_default_service_owns_and_closes_runtime() -> None:
    service = Service()
    assert not service.is_closed
    assert not service.runtime.is_closed

    service.close()
    assert service.is_closed
    assert service.runtime.is_closed

    service.close()


def test_caller_owned_runtime_is_not_closed_by_service() -> None:
    with Runtime() as runtime:
        service = Service(runtime)
        assert not service.is_closed
        assert not runtime.is_closed

        service.close()
        assert service.is_closed
        assert not runtime.is_closed


def test_compute_after_close_raises() -> None:
    service = Service()
    service.close()
    with pytest.raises(RuntimeError, match="Service is closed."):
        service.compute(make_request())


def test_capabilities_after_close_raises() -> None:
    service = Service()
    service.close()
    with pytest.raises(RuntimeError, match="Service is closed."):
        service.capabilities()


def test_capabilities_unifies_task_code_and_model_discovery() -> None:
    with Service() as service:
        capabilities = service.capabilities()

    assert len(capabilities["tasks"]) == 1
    assert capabilities["tasks"][0]["id"] == "scf_single_point"
    assert capabilities["tasks"][0]["name"] == "Single-point SCF"
    assert "quantum_espresso" in capabilities["target_codes"]
    assert {model["target"] for model in capabilities["models"]} == {
        "k_distance",
        "metallicity",
    }


def test_memory_output_is_an_explicit_stable_compute_option() -> None:
    with Service() as service:
        result = service.compute(make_request(), output=None)

    assert isinstance(result, ComputationResult)


def test_service_runs_concurrent_computations() -> None:
    class BlockingBackend:
        def __init__(self) -> None:
            self.calls = 0
            self.entered = Event()
            self.second_entered = Event()
            self.release = Event()
            self.lock = Lock()

        def __call__(self, structure: Structure) -> KPointSelection:
            del structure
            with self.lock:
                self.calls += 1
                call_number = self.calls
            if call_number == 1:
                self.entered.set()
                assert self.release.wait(timeout=2)
            else:
                self.second_entered.set()
            return KPointSelection(
                grid=(2, 2, 2),
                shift=(0, 0, 0),
                mesh_type="monkhorst-pack",
                provenance=Provenance(source="model", reason="test"),
            )

        def close(self) -> None:
            pass

    backend = BlockingBackend()
    request = ComputeRequest(
        draft=CalculationDraft(
            structure=InMemoryStructureSource(make_structure()),
            hints=CalculationHints(pseudo_type="NC"),
            pseudo_metadata=(make_metadata(),),
        ),
        selection=PresetSelection("recommend"),
    )

    with Runtime(kmesh_service=backend) as runtime, Service(runtime) as service:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(service.compute, request)
            assert backend.entered.wait(timeout=2)
            second = pool.submit(service.compute, request)
            try:
                assert backend.second_entered.wait(timeout=2)
            finally:
                backend.release.set()
            first.result(timeout=2)
            second.result(timeout=2)

    assert backend.calls == 2


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

    with Service() as service, ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.compute, make_request())
        assert registration_started.wait(timeout=2)

        def run_second() -> ComputationResult:
            second_started.set()
            return service.compute(make_request())

        second = pool.submit(run_second)
        assert second_started.wait(timeout=2)
        try:
            with pytest.raises(FutureTimeoutError):
                second.result(timeout=0.1)
        finally:
            release_registration.set()
        assert isinstance(first.result(timeout=2), ComputationResult)
        assert isinstance(second.result(timeout=2), ComputationResult)


def test_capabilities_and_inspection_do_not_wait_for_computation() -> None:
    class BlockingBackend:
        def __init__(self) -> None:
            self.entered = Event()
            self.release = Event()

        def __call__(self, structure: Structure) -> KPointSelection:
            del structure
            self.entered.set()
            assert self.release.wait(timeout=2)
            return KPointSelection(
                grid=(2, 2, 2),
                shift=(0, 0, 0),
                mesh_type="monkhorst-pack",
                provenance=Provenance(source="model", reason="test"),
            )

        def close(self) -> None:
            pass

    backend = BlockingBackend()
    request = ComputeRequest(
        draft=CalculationDraft(
            structure=InMemoryStructureSource(make_structure()),
            hints=CalculationHints(pseudo_type="NC"),
            pseudo_metadata=(make_metadata(),),
        ),
        selection=PresetSelection("recommend"),
    )

    with Runtime(kmesh_service=backend) as runtime, Service(runtime) as service:
        with ThreadPoolExecutor(max_workers=3) as pool:
            computation = pool.submit(service.compute, request)
            assert backend.entered.wait(timeout=2)
            capabilities = pool.submit(service.capabilities)
            inspection = pool.submit(
                service.inspect_structure,
                InMemoryStructureSource(make_structure()),
            )
            try:
                assert capabilities.result(timeout=0.5)["tasks"]
                assert inspection.result(timeout=0.5).structure.reduced_formula == "Si"
            finally:
                backend.release.set()
            computation.result(timeout=2)


def test_one_service_reuses_its_runtime_across_computations() -> None:
    request = make_request()
    with Service() as service:
        first = service.compute(request)
        second = service.compute(request)

    assert isinstance(first, ComputationResult)
    assert first.records[KPointSelection] == second.records[KPointSelection]
