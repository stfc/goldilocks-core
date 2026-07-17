from __future__ import annotations

import numpy as np
import pytest

import goldilocks_core.advisors.kdistance_advisor as kdistance_advisor
from goldilocks_core.contracts import StructureFeatureVector
from goldilocks_core.ml.model_registry import load_default_qrf_config
from goldilocks_core.ml.validation import validate_real_qrf_artifacts


def test_real_artifact_validation_requires_explicit_opt_in(monkeypatch) -> None:
    """The network-capable compatibility path is inert in normal test runs."""

    def unexpected_registry_load(path=None):
        raise AssertionError("registry and artifacts must not load without opt-in")

    monkeypatch.setattr(
        "goldilocks_core.ml.validation.load_default_qrf_config",
        unexpected_registry_load,
    )

    with pytest.raises(RuntimeError, match="explicit.*opt-in"):
        validate_real_qrf_artifacts()


def test_real_artifact_validation_runs_qrf_contract_before_mocked_inference(
    monkeypatch,
) -> None:
    """The opt-in path validates the QRF contract without remote artifacts."""
    config = load_default_qrf_config()
    contract_calls = 0
    validate_contract = kdistance_advisor._validate_qrf_contract

    def track_contract(received_config) -> None:
        nonlocal contract_calls
        contract_calls += 1
        assert received_config is config
        validate_contract(received_config)

    def resolve_artifacts(
        received_config,
        checkpoint,
        atom_init,
        *,
        resolved_artifacts,
    ) -> tuple[str, str]:
        assert received_config is config
        assert checkpoint is None
        assert atom_init is None
        resolved_artifacts.update(
            {
                "metallicity_checkpoint": "mock-checkpoint",
                "metallicity_atom_table": "mock-atom-table",
            }
        )
        return "mock-checkpoint", "mock-atom-table"

    class FakeQRF:
        q = [0.05, 0.5, 0.95]

        def predict(self, values):
            return np.array([[0.2], [0.25], [0.3]])

    monkeypatch.setattr(
        "goldilocks_core.ml.validation.load_default_qrf_config",
        lambda path: config,
    )
    monkeypatch.setattr(kdistance_advisor, "_validate_qrf_contract", track_contract)
    monkeypatch.setattr(
        kdistance_advisor, "_resolve_metallicity_artifacts", resolve_artifacts
    )
    monkeypatch.setattr("goldilocks_core.ml.models.load_model", lambda spec: FakeQRF())
    monkeypatch.setattr(
        "goldilocks_core.ml.metallicity.load_metallicity_model", lambda path: object()
    )
    monkeypatch.setattr(
        "goldilocks_core.ml.kdistance_features.extract_qrf_features",
        lambda structure, model, atom_table, settings: StructureFeatureVector(
            values=np.zeros(3), feature_names=["a", "b", "c"]
        ),
    )

    result = validate_real_qrf_artifacts(allow_network=True)

    assert contract_calls == 1
    assert result["config_digest"] == config.digest
    assert result["feature_count"] == 3
    assert result["prediction"] == pytest.approx(
        {
            "median": 0.25,
            "lower": 0.2 - config.calibration.correction,
            "upper": 0.3 + config.calibration.correction,
        }
    )
