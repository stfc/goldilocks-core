"""Model loading utilities for machine-learning inference."""

from __future__ import annotations

from pathlib import Path

import joblib

from goldilocks_core.contracts import ModelSpec


def load_model(spec: ModelSpec) -> object:
    """Load a trained model from a model specification.

    Sources
    -------
    ``local``
        ``spec.location`` is a filesystem path to a joblib artifact.
    ``huggingface``
        ``spec.location`` is ``"<repo_id>::<filename>"`` (e.g.
        ``"STFC-SCD/kpoints-goldilocks-QRF::QRF95.pkl"``). The file is
        downloaded from the Hub and cached locally, honoring ``spec.revision``
        when set.

    Returns
    -------
    object
        Loaded model object. The concrete type depends on the backend.

    Raises
    ------
    FileNotFoundError
        If a local model path does not exist.
    NotImplementedError
        If the requested model source is not supported.
    ValueError
        If a huggingface location is not ``"<repo_id>::<filename>"``.
    """
    if spec.source == "local":
        return _load_local(spec.location)

    if spec.source == "huggingface":
        return _load_huggingface(spec.location, spec.revision)

    raise NotImplementedError(f"Model source '{spec.source}' is not implemented yet.")


def _load_local(location: str) -> object:
    """Load a joblib model from a local filesystem path."""
    model_path = Path(location)
    if not model_path.exists():
        raise FileNotFoundError(f"Model file not found: {model_path}")

    return joblib.load(model_path)


def _load_huggingface(location: str, revision: str | None) -> object:
    """Download a joblib model from the Hugging Face Hub and load it."""
    from huggingface_hub import hf_hub_download

    repo_id, separator, filename = location.partition("::")
    if not separator or not filename:
        raise ValueError(
            "HuggingFace model location must be '<repo_id>::<filename>'; "
            f"got {location!r}"
        )

    model_path = hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        revision=revision,
    )
    return joblib.load(model_path)
