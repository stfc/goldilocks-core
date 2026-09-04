import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core import (
    CalculationHints,
    CalculationIntent,
    PresetRequest,
    QueryRequest,
    Runtime,
    query_records,
    run_core_job,
)
from goldilocks_core.advice.kdistance import QrfBackend
from goldilocks_core.contracts import (
    ParameterAdvice,
    PseudoCutoffs,
    PseudoMetadata,
    Records,
    Result,
    StructureAnalysisRecord,
    StructureFeatureVector,
)
from goldilocks_core.ml.model_registry import load_default_qrf_config


def make_structure() -> Structure:
    return Structure(
        lattice=Lattice.cubic(4.0),
        species=["Si"],
        coords=[[0.0, 0.0, 0.0]],
    )


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
        cutoffs=PseudoCutoffs(
            ecutwfc_ry=35,
            ecutrho_ry=140,
        ),
        source_identifier="synthetic/Si.UPF",
    )


def test_run_core_job_recommend_matches_public_recommendation_shape() -> None:
    result = run_core_job(
        PresetRequest(
            structure=make_structure(),
            hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
            pseudo_metadata=(make_metadata(),),
        )
    )

    assert isinstance(result, Result)
    assert result.k_points.grid == (2, 2, 1)
    assert result.selection.pseudopotentials[0].filename == "Si.UPF"
    assert result.generated_files == ()
    assert result.bundle is None


def test_query_records_returns_only_requested_records() -> None:
    request = QueryRequest(
        structure=make_structure(),
        hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
        outputs=(StructureAnalysisRecord, ParameterAdvice),
    )

    records = query_records(request)

    assert request.to_dict()["outputs"] == [
        "analysis",
        "advice",
    ]
    assert isinstance(records, Records)
    assert tuple(records) == (StructureAnalysisRecord, ParameterAdvice)
    assert isinstance(records[StructureAnalysisRecord], StructureAnalysisRecord)
    assert isinstance(records[ParameterAdvice], ParameterAdvice)


def test_query_records_reuses_caller_owned_runtime() -> None:
    request = QueryRequest(
        structure=make_structure(),
        outputs=(StructureAnalysisRecord, ParameterAdvice),
    )

    with Runtime() as runtime:
        first = query_records(request, runtime=runtime)
        second = query_records(request, runtime=runtime)
        assert runtime.is_closed is False

    assert isinstance(first, Records)
    assert first.to_dict() == second.to_dict()
    assert runtime.is_closed is True


def test_run_core_job_aggregates_kmesh_warnings() -> None:
    result = run_core_job(
        PresetRequest(
            structure=make_structure(),
            hints=CalculationHints(
                k_grid=(2, 2, 1),
                k_spacing=0.2,
                pseudo_type="NC",
            ),
            pseudo_metadata=(make_metadata(),),
        )
    )

    warning = "Both k_grid and k_spacing were provided; explicit grid wins."
    assert warning in result.warnings


def test_run_core_job_no_longer_hedges_once_a_model_answers_metallicity() -> None:
    # Before #174, Runtime() with no configured model fell back to the
    # composition heuristic, which cannot tell "insulator" from "unknown" for
    # Si and left a "verify manually" warning. The default electronic
    # character model (test-stubbed here; the real goldilocks-ml classifier
    # agrees) commits to insulator instead, so there is nothing left to warn
    # about -- see test_advice.py for the heuristic's own "unknown" case.
    result = run_core_job(
        PresetRequest(
            structure=make_structure(),
            hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
            pseudo_metadata=(make_metadata(),),
        )
    )

    assert result.analysis.electronic_character == "insulator"
    assert result.analysis.electronic_character_source == "model"
    assert result.advice.smearing.smearing_type == "fixed"
    assert not any("verify" in warning.lower() for warning in result.warnings)


def test_run_core_job_uses_shared_default_qrf_backend(monkeypatch, tmp_path) -> None:

    class FakeQRF:
        q = [0.05, 0.5, 0.95]

        def predict(self, features):
            return [[0.2], [0.25], [0.3]]

    checkpoint = tmp_path / "checkpoint.ckpt"
    atom_table = tmp_path / "atom-init.json"
    checkpoint.write_bytes(b"checkpoint")
    atom_table.write_bytes(b"atom table")
    model_file = tmp_path / "model.joblib"
    model_file.write_bytes(b"model")
    config = load_default_qrf_config()
    config = replace(
        config,
        model=replace(config.model, source="local", location=str(model_file)),
        model_asset=None,
    )
    monkeypatch.setattr("goldilocks_core.ml.models.load_model", lambda spec: FakeQRF())
    monkeypatch.setattr(
        "goldilocks_core.ml.qrf.metallicity.load_metallicity_model",
        lambda path: object(),
    )

    class FakeStructureModel:
        def predict(self, structure):
            from goldilocks_ml.inference import ModelPrediction

            return ModelPrediction(
                parameter="metallicity",
                quantity="is_metal",
                value=False,
                target_contract="goldilocks.is_metal.dft_band_gap_zero.v1",
                model_id="stub",
                details={"score": 0.1},
            )

    monkeypatch.setattr(
        "goldilocks_ml.inference.load_model",
        lambda model_dir: FakeStructureModel(),
    )
    monkeypatch.setattr(
        "goldilocks_core.ml.qrf.features.extract_qrf_features",
        lambda structure, model, atom_init, settings: StructureFeatureVector(
            values=np.zeros(483),
            feature_names=[f"feature_{index}" for index in range(483)],
        ),
    )

    with Runtime(
        metallicity_model_dir="metal-model/",
        kmesh_service=QrfBackend(
            config=config,
            metallicity_checkpoint=str(checkpoint),
            metallicity_atom_init=str(atom_table),
        ),
    ) as runtime:
        result = run_core_job(
            PresetRequest(
                structure=make_structure(),
                hints=CalculationHints(pseudo_type="NC"),
                pseudo_metadata=(make_metadata(),),
            ),
            runtime=runtime,
        )

    assert result.k_points.provenance.source == "model"
    assert result.k_points.provenance.confidence == 0.9


def test_run_core_job_rejects_unknown_task() -> None:
    with pytest.raises(
        ValueError, match="No Core task registered for task='magnetic_nscf'"
    ):
        run_core_job(
            PresetRequest(
                structure=make_structure(),
                intent=CalculationIntent(task="magnetic_nscf"),
                hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
                pseudo_metadata=(make_metadata(),),
            )
        )


def test_run_core_job_reuses_caller_owned_runtime() -> None:
    request = PresetRequest(
        structure=make_structure(),
        hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
        pseudo_metadata=(make_metadata(),),
    )

    with Runtime() as runtime:
        first = run_core_job(request, runtime=runtime)
        second = run_core_job(request, runtime=runtime)
        assert runtime.is_closed is False

    assert first.k_points == second.k_points
    assert runtime.is_closed is True


def test_run_core_job_generate_adds_generated_files() -> None:
    result = run_core_job(
        PresetRequest(
            structure=make_structure(),
            hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
            pseudo_metadata=(make_metadata(),),
            mode="generate",
        )
    )

    assert result.generated_files[0].path == "inputs/qe.in"
    assert "2  2  1  0  0  0" in result.generated_files[0].content


def test_run_core_job_generate_with_caller_owned_runtime() -> None:
    request = PresetRequest(
        structure=make_structure(),
        hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
        pseudo_metadata=(make_metadata(),),
        mode="generate",
    )

    with Runtime() as runtime:
        result = run_core_job(request, runtime=runtime)
        assert runtime.is_closed is False

    assert result.generated_files[0].path == "inputs/qe.in"


def test_run_core_job_generate_with_output_dir_writes_bundle(tmp_path: Path) -> None:
    output_dir = tmp_path / "bundle"
    result = run_core_job(
        PresetRequest(
            structure=make_structure(),
            hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
            pseudo_metadata=(make_metadata(),),
            mode="generate",
            output_dir=str(output_dir),
        )
    )

    assert result.bundle is not None
    assert result.bundle.path == str(output_dir)
    assert (output_dir / "inputs" / "qe.in").exists()
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["k_points"]["grid"] == [2, 2, 1]
    assert result.bundle.manifest == manifest
