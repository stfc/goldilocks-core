from __future__ import annotations

import json

from pymatgen.core import Lattice, Structure

from goldilocks_core import CalculationHints, CoreJobRequest, CoreRuntime
from goldilocks_core.contracts import (
    CoreResult,
    KPointSelection,
    ParameterAdvice,
    Provenance,
    SelectionRecord,
    StructureAnalysisRecord,
)
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata


def make_structure() -> Structure:
    """Build a simple silicon structure."""
    return Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])


def make_metadata() -> PseudoMetadata:
    """Build synthetic pseudopotential metadata with complete cutoffs."""
    return PseudoMetadata(
        filepath="/pseudo/Si.UPF",
        filename="Si.UPF",
        header_format="attr",
        library="SSSP",
        element="Si",
        pseudo_type="NC",
        functional="PBEsol",
        relativistic="scalar",
        sssp_recommended_cutoff={"ecutwfc_ry": 35, "ecutrho_ry": 140},
    )


def make_request(*, mode: str = "recommend") -> CoreJobRequest:
    """Build a request that avoids loading external model artifacts."""
    return CoreJobRequest(
        structure=make_structure(),
        hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
        pseudo_metadata=(make_metadata(),),
        mode=mode,
    )


class TrackingBackend:
    """Record lifecycle and inference calls for runtime tests."""

    def __init__(self, *, raise_on_call: bool = False) -> None:
        self.calls = 0
        self.resets = 0
        self.closes = 0
        self.raise_on_call = raise_on_call

    def __call__(self, structure: Structure) -> KPointSelection:
        self.calls += 1
        if self.raise_on_call:
            raise AssertionError("kmesh backend must not be called")
        return KPointSelection(
            grid=(2, 2, 2),
            shift=(0, 0, 0),
            mesh_type="monkhorst-pack",
            provenance=Provenance(source="model", reason="test backend"),
        )

    def reset(self) -> None:
        self.resets += 1

    def close(self) -> None:
        self.closes += 1


def test_recommend_returns_complete_result_without_generated_files() -> None:
    with CoreRuntime() as runtime:
        result = runtime.recommend(make_request())

    assert isinstance(result, CoreResult)
    assert isinstance(result.analysis, StructureAnalysisRecord)
    assert isinstance(result.advice, ParameterAdvice)
    assert isinstance(result.k_points, KPointSelection)
    assert isinstance(result.selection, SelectionRecord)
    assert result.generated_files == ()


def test_generate_returns_generated_files() -> None:
    with CoreRuntime() as runtime:
        result = runtime.generate(make_request(mode="generate"))

    assert result.generated_files
    assert result.generated_files[0].path == "inputs/qe.in"


def test_generate_with_output_dir_writes_bundle(tmp_path) -> None:
    output_dir = tmp_path / "bundle"

    with CoreRuntime() as runtime:
        result = runtime.generate(
            make_request(mode="generate"), output_dir=str(output_dir)
        )

    assert result.bundle is not None
    assert result.bundle.path == str(output_dir)
    assert (output_dir / "inputs" / "qe.in").is_file()
    manifest = json.loads((output_dir / "manifest.json").read_text())
    assert manifest == result.bundle.manifest


def test_compute_returns_only_requested_record_types() -> None:
    with CoreRuntime() as runtime:
        records = runtime.compute(
            (StructureAnalysisRecord, ParameterAdvice), make_request()
        )

    assert tuple(records) == (StructureAnalysisRecord, ParameterAdvice)
    assert isinstance(records[StructureAnalysisRecord], StructureAnalysisRecord)
    assert isinstance(records[ParameterAdvice], ParameterAdvice)
    assert SelectionRecord not in records
    assert KPointSelection not in records


def test_select_only_compute_does_not_invoke_kmesh(monkeypatch) -> None:
    backend = TrackingBackend(raise_on_call=True)
    monkeypatch.setattr(CoreRuntime, "_build_backend", lambda self: backend)

    with CoreRuntime() as runtime:
        records = runtime.compute((SelectionRecord,), make_request())

    assert isinstance(records[SelectionRecord], SelectionRecord)
    assert backend.calls == 0


def test_reset_close_and_context_manager_delegate_to_backend(monkeypatch) -> None:
    backend = TrackingBackend()
    monkeypatch.setattr(CoreRuntime, "_build_backend", lambda self: backend)

    with CoreRuntime() as runtime:
        runtime.reset()
        assert runtime.is_closed is False

    assert runtime.is_closed is True
    assert backend.resets == 1
    assert backend.closes == 1

    runtime.close()
    assert backend.closes == 1


def test_multiple_jobs_reuse_one_backend(monkeypatch) -> None:
    backend = TrackingBackend()
    builds = 0

    def build(runtime):
        nonlocal builds
        builds += 1
        return backend

    monkeypatch.setattr(CoreRuntime, "_build_backend", build)
    request = CoreJobRequest(
        structure=make_structure(),
        hints=CalculationHints(pseudo_type="NC"),
        pseudo_metadata=(make_metadata(),),
    )

    with CoreRuntime() as runtime:
        first = runtime.recommend(request)
        second = runtime.recommend(request)

    assert first.k_points == second.k_points
    assert builds == 1
    assert backend.calls == 2
