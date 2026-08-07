from __future__ import annotations

import json

import numpy as np
import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core import (
    CalculationHints,
    CoreJobRequest,
    CoreRuntime,
    run_core_job,
)
from goldilocks_core.contracts import StructureFeatureVector
from goldilocks_core.pseudo.pp_metadata import PseudoMetadata
from goldilocks_core.runtime import CoreRuntime as _CoreRuntime


class FakeQRF:
    """Minimal QRF model returning fixed quantiles."""

    def __init__(self) -> None:
        self.quantiles = np.array([[0.2], [0.25], [0.3]])

    def predict(self, features: np.ndarray) -> np.ndarray:
        return self.quantiles


def make_structure() -> Structure:
    """Build a simple silicon structure."""
    return Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])


def make_metadata() -> PseudoMetadata:
    """Build synthetic pseudopotential metadata with cutoffs."""
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


def make_request(*, mode: str = "recommend", k_grid=None, output_dir=None):
    """Build a CoreJobRequest for the silicon test structure."""
    hints_kwargs = {"pseudo_type": "NC"}
    if k_grid is not None:
        hints_kwargs["k_grid"] = k_grid
    return CoreJobRequest(
        structure=make_structure(),
        hints=CalculationHints(**hints_kwargs),
        pseudo_metadata=(make_metadata(),),
        mode=mode,
        output_dir=output_dir,
    )


def patch_qrf_inference(monkeypatch, tmp_path, *, count_loads=False):
    """Monkeypatch model loading and feature extraction for offline tests.

    Returns a mutable ``loads`` list so callers can assert on load counts.
    """
    loads = [0]

    def load_model(spec):
        if count_loads:
            loads[0] += 1
        return FakeQRF()

    checkpoint = tmp_path / "checkpoint.ckpt"
    atom_table = tmp_path / "atom-init.json"
    checkpoint.write_bytes(b"checkpoint")
    atom_table.write_bytes(b"atom table")
    monkeypatch.setenv("GOLDILOCKS_METALLICITY_CHECKPOINT", str(checkpoint))
    monkeypatch.setenv("GOLDILOCKS_METALLICITY_ATOM_INIT", str(atom_table))
    monkeypatch.setattr("goldilocks_core.ml.models.load_model", load_model)
    monkeypatch.setattr(
        "goldilocks_core.ml.qrf.metallicity.load_metallicity_model",
        lambda path: object(),
    )
    monkeypatch.setattr(
        "goldilocks_core.ml.qrf.features.extract_qrf_features",
        lambda structure, model, atom_init, settings: StructureFeatureVector(
            values=np.zeros(483),
            feature_names=[f"feature_{index}" for index in range(483)],
        ),
    )
    return loads


def test_runtime_loads_model_once_across_two_recommend_calls(
    monkeypatch, tmp_path
) -> None:
    """The runtime reuses loaded model resources across jobs on the same instance."""
    loads = patch_qrf_inference(monkeypatch, tmp_path, count_loads=True)
    req = make_request()

    rt = CoreRuntime()
    rt.recommend(req)
    rt.recommend(req)

    assert loads[0] == 1
    rt.close()


def test_runtime_reset_discards_model_state_so_next_call_reloads(
    monkeypatch, tmp_path
) -> None:
    """reset() discards loaded resources; the next call reloads them."""
    loads = patch_qrf_inference(monkeypatch, tmp_path, count_loads=True)
    req = make_request()

    rt = CoreRuntime()
    rt.recommend(req)
    assert loads[0] == 1

    rt.reset()
    rt.recommend(req)
    assert loads[0] == 2
    rt.close()


def test_runtime_close_releases_resources_and_is_idempotent(
    monkeypatch, tmp_path
) -> None:
    """close() releases model references; is_closed is True; second close is a no-op."""
    patch_qrf_inference(monkeypatch, tmp_path)
    req = make_request()

    rt = CoreRuntime()
    rt.recommend(req)
    assert rt._backend._resources is not None

    rt.close()
    assert rt.is_closed
    assert rt._backend._resources is None

    # Second close must not raise.
    rt.close()
    assert rt.is_closed


def test_runtime_context_manager_closes_after_block(monkeypatch, tmp_path) -> None:
    """Using CoreRuntime as a context manager closes it on exit."""
    patch_qrf_inference(monkeypatch, tmp_path)
    req = make_request()

    with CoreRuntime() as rt:
        result = rt.recommend(req)
        assert result.selection is not None

    assert rt.is_closed


def test_runtime_recommend_produces_no_files_or_bundle(monkeypatch, tmp_path) -> None:
    """recommend() returns generated_files=() and bundle=None."""
    patch_qrf_inference(monkeypatch, tmp_path)
    req = make_request()

    with CoreRuntime() as rt:
        result = rt.recommend(req)

    assert result.generated_files == ()
    assert result.bundle is None


def test_runtime_generate_produces_files_without_bundle(monkeypatch, tmp_path) -> None:
    """generate() without output_dir returns in-memory files and no bundle."""
    patch_qrf_inference(monkeypatch, tmp_path)
    req = make_request(mode="generate")

    with CoreRuntime() as rt:
        result = rt.generate(req)

    assert len(result.generated_files) > 0
    assert result.generated_files[0].path == "inputs/qe.in"
    assert result.bundle is None


def test_runtime_generate_with_output_dir_writes_bundle(monkeypatch, tmp_path) -> None:
    """generate(output_dir=...) publishes a BundleRecord and writes the directory."""
    patch_qrf_inference(monkeypatch, tmp_path)
    req = make_request(mode="generate")
    output_dir = tmp_path / "bundle"

    with CoreRuntime() as rt:
        result = rt.generate(req, output_dir=str(output_dir))

    assert result.bundle is not None
    assert result.bundle.path == str(output_dir)
    assert (output_dir / "inputs" / "qe.in").exists()
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 1


def test_run_core_job_fresh_runtime_does_not_leak_module_global(
    monkeypatch, tmp_path
) -> None:
    """run_core_job with runtime=None creates and closes a fresh runtime per call."""
    patch_qrf_inference(monkeypatch, tmp_path)
    req = make_request(k_grid=(2, 2, 1))

    result = run_core_job(req)
    assert result.selection is not None

    # No CoreRuntime instance should linger as a module global.
    import goldilocks_core.runtime as runtime_module

    assert not any(
        isinstance(value, _CoreRuntime) for value in vars(runtime_module).values()
    )


def test_run_core_job_reuses_passed_runtime(monkeypatch, tmp_path) -> None:
    """run_core_job with an explicit runtime reuses its model state."""
    loads = patch_qrf_inference(monkeypatch, tmp_path, count_loads=True)
    req = make_request()

    rt = CoreRuntime()
    run_core_job(req, runtime=rt)
    run_core_job(req, runtime=rt)

    assert loads[0] == 1
    assert not rt.is_closed
    rt.close()


def test_recommend_on_closed_runtime_raises(monkeypatch, tmp_path) -> None:
    """Calling recommend after close raises RuntimeError."""
    patch_qrf_inference(monkeypatch, tmp_path)
    req = make_request()

    rt = CoreRuntime()
    rt.close()

    with pytest.raises(RuntimeError, match="CoreRuntime is closed."):
        rt.recommend(req)


def test_explicit_k_grid_hint_does_not_load_model(monkeypatch, tmp_path) -> None:
    """Explicit k_grid hints short-circuit before the model backend is loaded."""
    loads = patch_qrf_inference(monkeypatch, tmp_path, count_loads=True)
    req = make_request(k_grid=(2, 2, 1))

    with CoreRuntime() as rt:
        result = rt.recommend(req)

    assert result.selection.k_points.grid == (2, 2, 1)
    assert result.selection.k_points.provenance.source == "user_hint"
    assert loads[0] == 0
