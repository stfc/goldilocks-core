from dataclasses import replace
from pathlib import Path

import joblib
import pytest

from goldilocks_core.assets.records import AssetFile, AssetSpec
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.ml.model_registry import load_default_qrf_config
from goldilocks_core.ml.models import ModelSpec, load_model
from goldilocks_core.ml.qrf.inference import load_qrf_resources


def local_model(path: Path) -> ModelSpec:
    return ModelSpec(
        name="fixture",
        version="1",
        model_type="random_forest",
        target="k_distance",
        feature_set="fixture",
        source="local",
        location=str(path),
    )


def test_load_model_reads_explicit_local_file(tmp_path: Path) -> None:
    model_path = tmp_path / "model.joblib"
    joblib.dump({"kind": "dummy-rf"}, model_path)

    assert load_model(local_model(model_path)) == {"kind": "dummy-rf"}


def test_load_model_rejects_remote_source_without_network(monkeypatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: pytest.fail("network access attempted"),
    )
    spec = replace(
        local_model(Path("unused")),
        source="huggingface",
        location="organization/repository::model.pkl",
    )

    with pytest.raises(ValueError, match="do not fetch remote files"):
        load_model(spec)


def test_load_model_raises_for_missing_local_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Model file not found"):
        load_model(local_model(tmp_path / "missing.joblib"))


def test_qrf_resources_resolve_installed_assets_offline(
    monkeypatch, tmp_path: Path
) -> None:
    qrf_source = tmp_path / "QRF95.pkl"
    joblib.dump({"kind": "qrf"}, qrf_source)
    checkpoint = tmp_path / "is_metal.ckpt"
    checkpoint.write_bytes(b"checkpoint")
    atom_init = tmp_path / "atom_init.json"
    atom_init.write_text("{}")
    store = AssetStore(tmp_path / "assets")
    qrf_asset = AssetSpec(
        "models/qrf-kpoints",
        "QRF95",
        (AssetFile("model", "QRF95.pkl", qrf_source.as_uri()),),
    )
    metallicity_asset = AssetSpec(
        "models/metallicity-cgcnn",
        "1",
        (
            AssetFile("checkpoint", "is_metal.ckpt", checkpoint.as_uri()),
            AssetFile("atom_init", "atom_init.json", atom_init.as_uri()),
        ),
    )
    store.install(qrf_asset)
    store.install(metallicity_asset)
    config = replace(
        load_default_qrf_config(),
        model_asset=qrf_asset,
        metallicity_asset=metallicity_asset,
    )
    monkeypatch.setattr(
        "goldilocks_core.ml.qrf.metallicity.load_metallicity_model",
        lambda path: {"checkpoint": Path(path).read_bytes()},
    )
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: pytest.fail("network access attempted"),
    )

    resources = load_qrf_resources(config, asset_store=store)

    assert resources.model == {"kind": "qrf"}
    assert resources.metal_model == {"checkpoint": b"checkpoint"}
    assert Path(resources.atom_init).read_text() == "{}"


def test_explicit_local_resources_bypass_asset_store(
    monkeypatch, tmp_path: Path
) -> None:
    model_path = tmp_path / "model.joblib"
    joblib.dump({"kind": "local"}, model_path)
    checkpoint = tmp_path / "checkpoint"
    checkpoint.write_bytes(b"local checkpoint")
    atom_init = tmp_path / "atom_init.json"
    atom_init.write_text("{}")
    config = replace(
        load_default_qrf_config(),
        model=local_model(model_path),
        model_asset=None,
        metallicity_asset=None,
        metallicity_model=replace(
            load_default_qrf_config().metallicity_model,
            source="local",
            location=str(tmp_path),
        ),
        metallicity_checkpoint_file=checkpoint.name,
        metallicity_atom_init_file=atom_init.name,
    )
    monkeypatch.setattr(
        "goldilocks_core.ml.qrf.metallicity.load_metallicity_model",
        lambda path: Path(path).read_bytes(),
    )

    resources = load_qrf_resources(config, asset_store=AssetStore(tmp_path / "empty"))

    assert resources.model == {"kind": "local"}
    assert resources.metal_model == b"local checkpoint"
    assert resources.atom_init == str(atom_init)
