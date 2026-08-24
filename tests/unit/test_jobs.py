import hashlib
from dataclasses import replace

import numpy as np
import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core import (
    CalculationDraft,
    CalculationHints,
    CalculationIntent,
    ComputeRequest,
    InMemoryStructureSource,
    PresetSelection,
    RecordSelection,
    Runtime,
    UnknownTask,
    compute,
)
from goldilocks_core.advice.kdistance import QrfBackend
from goldilocks_core.contracts import (
    GeneratedFiles,
    ParameterAdvice,
    PseudoCutoffs,
    PseudoMetadata,
    StructureAnalysisRecord,
    StructureFeatureVector,
)
from goldilocks_core.ml.model_registry import load_default_qrf_config


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
        pseudo_info={
            "licence": "CC-BY-4.0",
            "licence_text": "Synthetic fixture licence\n",
            "citation": "Synthetic fixture pseudopotential.",
        },
    )


def make_request(selection=None, **changes) -> ComputeRequest:
    draft_values = {
        "structure": InMemoryStructureSource(make_structure()),
        "hints": CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
        "pseudo_metadata": (make_metadata(),),
    }
    draft_values.update(changes)
    return ComputeRequest(
        draft=CalculationDraft(**draft_values),
        selection=selection or PresetSelection("recommend"),
    )


def test_compute_recommendation_returns_selected_records() -> None:
    result = compute(make_request())

    assert result.records[StructureAnalysisRecord].reduced_formula == "Si"
    assert result.records[ParameterAdvice].pseudopotential_requirements.functional == (
        "PBEsol"
    )
    assert GeneratedFiles not in result.records


def test_compute_returns_only_explicitly_selected_records() -> None:
    request = make_request(
        RecordSelection((StructureAnalysisRecord, ParameterAdvice)),
    )

    result = compute(request)

    assert request.to_dict()["selection"] == {
        "records": ["analysis", "advice"],
    }
    assert tuple(result.records) == (StructureAnalysisRecord, ParameterAdvice)


def test_compute_reuses_caller_owned_runtime() -> None:
    request = make_request(
        RecordSelection((StructureAnalysisRecord, ParameterAdvice)),
    )

    with Runtime() as runtime:
        first = compute(request, runtime=runtime)
        second = compute(request, runtime=runtime)
        assert runtime.is_closed is False

    assert first.to_dict() == second.to_dict()
    assert runtime.is_closed is True


def test_compute_uses_shared_default_qrf_backend(monkeypatch, tmp_path) -> None:
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
    monkeypatch.setattr(
        "goldilocks_core.ml.qrf.metallicity.classify_metallicity",
        lambda structure, model, atom_init, **settings: ("insulator", 0.9),
    )
    monkeypatch.setattr(
        "goldilocks_core.ml.qrf.features.extract_qrf_features",
        lambda structure, model, atom_init, settings: StructureFeatureVector(
            values=np.zeros(483),
            feature_names=[f"feature_{index}" for index in range(483)],
        ),
    )

    with Runtime(
        metallicity_checkpoint=checkpoint,
        metallicity_atom_init=atom_table,
        metallicity_model=config.metallicity_model,
        kmesh_service=QrfBackend(
            config=config,
            metallicity_checkpoint=str(checkpoint),
            metallicity_atom_init=str(atom_table),
        ),
    ) as runtime:
        result = compute(
            make_request(hints=CalculationHints(pseudo_type="NC")),
            runtime=runtime,
        )

    assert result.records[StructureAnalysisRecord].electronic_character == "insulator"


def test_compute_rejects_unknown_task() -> None:
    request = make_request(intent=CalculationIntent(task="magnetic_nscf"))

    with pytest.raises(
        UnknownTask,
        match="No Core task registered for task='magnetic_nscf'",
    ):
        compute(request)


def test_compute_generation_preset_produces_generated_inputs(tmp_path) -> None:
    pseudo_path = tmp_path / "Si.UPF"
    content = b"<UPF version='2.0.1'>Si fixture</UPF>\n"
    pseudo_path.write_bytes(content)
    metadata = replace(
        make_metadata(),
        filepath=str(pseudo_path),
        content_sha256=hashlib.sha256(content).hexdigest(),
        content_size_bytes=len(content),
    )
    result = compute(
        make_request(
            PresetSelection("generate"),
            pseudo_metadata=(metadata,),
        )
    )

    assert result.records[GeneratedFiles][0].path == "inputs/qe.in"
    assert "2  2  1  0  0  0" in result.records[GeneratedFiles][0].content
