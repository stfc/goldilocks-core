from __future__ import annotations

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core import (
    CalculationHints,
    PresetRequest,
    Result,
    Runtime,
    Service,
)
from goldilocks_core.contracts import PseudoCutoffs, PseudoMetadata


def make_structure() -> Structure:
    """Build a simple silicon structure."""
    return Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])


def make_metadata() -> PseudoMetadata:
    """Build synthetic pseudopotential metadata with cutoffs."""
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
        cutoffs=PseudoCutoffs(
            ecutwfc_ry=35,
            ecutrho_ry=140,
        ),
        source_identifier="synthetic/Si.UPF",
    )


def make_request() -> PresetRequest:
    """Build a recommend request that avoids loading external model artifacts."""
    return PresetRequest(
        structure=make_structure(),
        hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
        pseudo_metadata=(make_metadata(),),
    )


def test_default_service_owns_and_closes_runtime() -> None:
    """A default service owns its runtime and closes it on close."""
    service = Service()
    assert not service.is_closed
    assert not service.runtime.is_closed

    service.close()
    assert service.is_closed
    assert service.runtime.is_closed

    service.close()  # idempotent


def test_caller_owned_runtime_is_not_closed_by_service() -> None:
    """Closing a caller-owned service leaves the caller's runtime open."""
    with Runtime() as runtime:
        service = Service(runtime)
        assert not service.is_closed
        assert not runtime.is_closed

        service.close()
        assert service.is_closed
        assert not runtime.is_closed


def test_dispatch_after_close_raises() -> None:
    """A closed service rejects dispatch before touching the graph."""
    service = Service()
    service.close()
    with pytest.raises(RuntimeError, match="Service is closed."):
        service.recommend(make_request())


def test_discovery_after_close_raises() -> None:
    """A closed service rejects discovery."""
    service = Service()
    service.close()
    with pytest.raises(RuntimeError, match="Service is closed."):
        service.describe_tasks()


def test_describe_tasks_returns_the_scf_task() -> None:
    """The shipped service exposes one registered task with a stable id."""
    service = Service()
    try:
        tasks = service.describe_tasks()
        assert len(tasks) == 1
        assert tasks[0].id == "scf_single_point"
        assert tasks[0].name == "Single-point SCF"
    finally:
        service.close()


def test_describe_codes_and_models() -> None:
    """Discovery surfaces the registered code and both model specs."""
    service = Service()
    try:
        assert "quantum_espresso" in service.describe_codes()
        models = service.describe_models()
        assert len(models) == 2
        targets = {model["target"] for model in models}
        assert targets == {"k_distance", "metallicity"}
    finally:
        service.close()


def test_one_service_reused_across_dispatches() -> None:
    """One process-owned service handles repeated dispatches consistently."""
    request = make_request()
    with Service() as service:
        first = service.recommend(request)
        second = service.recommend(request)

    assert isinstance(first, Result)
    assert first.k_points == second.k_points
