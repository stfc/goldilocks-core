"""Tests for the server-owned deployment configuration seam."""

import json

import pytest

from goldilocks_core.pseudo.pp_metadata import PseudoMetadata
from goldilocks_core.server.config import (
    COMPUTE_LIMIT_ENV,
    COMPUTE_WAIT_ENV,
    DEFAULT_COMPUTE_LIMIT,
    DEFAULT_COMPUTE_WAIT_SECONDS,
    PSEUDO_METADATA_ENV,
    DeploymentConfig,
)
from goldilocks_core.server.http import create_app

TestClient = pytest.importorskip("fastapi.testclient").TestClient

SYNTHETIC_SI = {
    "filename": "Si.UPF",
    "header_format": "attr",
    "library": "SSSP",
    "source_set": "efficiency",
    "element": "Si",
    "pseudo_type": "NC",
    "functional": "PBEsol",
    "relativistic": "scalar",
    "z_valence": 4.0,
    "is_sssp": True,
    "sssp_recommended_cutoff": {"ecutwfc_ry": 30.0, "ecutrho_ry": 120.0},
}


def test_default_config_is_conservative_and_empty() -> None:
    """Unset environment yields conservative documented defaults."""
    config = DeploymentConfig.from_environ({})

    assert config.compute_limit == DEFAULT_COMPUTE_LIMIT
    assert config.compute_wait_seconds == DEFAULT_COMPUTE_WAIT_SECONDS
    assert config.pseudo_metadata == ()


def test_from_environ_reads_capacity(monkeypatch) -> None:
    """Operator capacity values flow from the environment."""
    config = DeploymentConfig.from_environ(
        {COMPUTE_LIMIT_ENV: "4", COMPUTE_WAIT_ENV: "2.5"}
    )

    assert config.compute_limit == 4
    assert config.compute_wait_seconds == 2.5


def test_from_environ_rejects_invalid_capacity() -> None:
    """Invalid capacity values fail loudly rather than being silently ignored."""
    with pytest.raises(ValueError):
        DeploymentConfig.from_environ({COMPUTE_LIMIT_ENV: "0"})
    with pytest.raises(ValueError):
        DeploymentConfig.from_environ({COMPUTE_LIMIT_ENV: "abc"})
    with pytest.raises(ValueError):
        DeploymentConfig.from_environ({COMPUTE_WAIT_ENV: "-1"})


def test_pseudo_metadata_loads_from_json_manifest(tmp_path) -> None:
    """Administrator pseudo metadata loads from a mounted JSON manifest."""
    path = tmp_path / "pseudo.json"
    path.write_text(json.dumps([SYNTHETIC_SI]), encoding="utf-8")

    config = DeploymentConfig.from_environ({PSEUDO_METADATA_ENV: str(path)})

    assert len(config.pseudo_metadata) == 1
    meta = config.pseudo_metadata[0]
    assert isinstance(meta, PseudoMetadata)
    assert meta.element == "Si"
    assert meta.filename == "Si.UPF"


def test_malformed_pseudo_manifest_fails_with_clear_error(tmp_path) -> None:
    """A non-JSON manifest fails with a locating message, not a cryptic parse error."""
    path = tmp_path / "pseudo.json"
    path.write_text("{ this is not json", encoding="utf-8")

    with pytest.raises(ValueError) as error:
        DeploymentConfig.from_environ({PSEUDO_METADATA_ENV: str(path)})

    message = str(error.value)
    assert "not valid JSON" in message
    assert str(path) in message
    assert "line" in message


def test_non_object_pseudo_entry_fails_with_clear_error(tmp_path) -> None:
    """A non-object manifest entry names the offending entry."""
    path = tmp_path / "pseudo.json"
    path.write_text("[42]", encoding="utf-8")

    with pytest.raises(ValueError, match="entry 0 must be a JSON object"):
        DeploymentConfig.from_environ({PSEUDO_METADATA_ENV: str(path)})


def test_injected_pseudo_metadata_drives_selection(
    test_runtime, sample_structure_text
) -> None:
    """Config pseudo metadata is injected when the request supplies none."""
    config = DeploymentConfig(
        compute_limit=2,
        compute_wait_seconds=5.0,
        pseudo_metadata=(PseudoMetadata(**SYNTHETIC_SI),),
    )
    body = {
        "structure": {"content": sample_structure_text, "format": "cif"},
        "hints": {"k_grid": [3, 3, 3]},
    }

    with TestClient(create_app(test_runtime, config=config)) as client:
        response = client.post("/recommend", json=body)

    assert response.status_code == 200
    selection = response.json()["selection"]["pseudopotentials"]
    assert selection and selection[0]["element"] == "Si"
    assert selection[0]["filename"] == "Si.UPF"
    assert selection[0]["ecutwfc_ry"] == 30.0
    assert "filepath" not in response.text


def test_browser_supplied_pseudo_metadata_is_not_overridden(
    test_runtime, request_body
) -> None:
    """A request carrying its own metadata keeps it over the config default."""
    config = DeploymentConfig(
        pseudo_metadata=(PseudoMetadata(filename="Config.UPF", header_format="attr"),),
    )

    with TestClient(create_app(test_runtime, config=config)) as client:
        response = client.post("/recommend", json=request_body)

    assert response.status_code == 200
    selection = response.json()["selection"]["pseudopotentials"]
    assert selection and selection[0]["filename"] == "Si.UPF"
