"""Quantile Random Forest (QRF) k-distance advisor.

The QRF model predicts a VASP-style k-point distance (Å⁻¹) as three quantiles
(lower, median, upper). The median drives the concrete mesh; the interval and
the model's confidence level are recorded in provenance. This module holds the
model-agnostic post-prediction logic; feature extraction (which pulls heavy ML
dependencies) is supplied separately.
"""

from __future__ import annotations

import os
from dataclasses import replace

import numpy as np
from pymatgen.core import Structure

from goldilocks_core.contracts import (
    CalculationHints,
    KMeshAdvisor,
    KPointAdvice,
    KPointSelection,
    ModelSpec,
    Provenance,
    StructureFeatureVector,
)
from goldilocks_core.kmesh import k_distance_to_mesh, resolve_kpoints_from_advice

# Built-in default k-point model: the STFC QRF at 95% confidence, resolved from
# the Hugging Face Hub. Feature set names the extractor the model was trained on.
DEFAULT_KPOINTS_MODEL = ModelSpec(
    name="kpoints-goldilocks-QRF",
    version="QRF95",
    model_type="random_forest",
    target="k_distance",
    feature_set="qrf_comp_struct_soap_lattice_metal",
    source="huggingface",
    location="STFC-SCD/kpoints-goldilocks-QRF::QRF95.pkl",
    revision=None,
)

# Confidence level of the default model and the calibrated interval correction
# (widens the interval), from the trained QRF at 0.95. See the goldilocks
# k-distance reference implementation.
DEFAULT_KPOINTS_CONFIDENCE = 0.95
DEFAULT_KPOINTS_CORRECTION = -0.0016

# The QRF k-distance features include a CGCNN metallicity block. Its checkpoint
# and atom-embedding table are published to Hugging Face and resolved by default
# from this repo; local paths (env-overridable) take precedence for offline dev.
# When nothing resolves, the advisor falls back to heuristic advice.
DEFAULT_METALLICITY_REPO = "JunwenYin/metallicity-goldilocks-CGCNN"
_METALLICITY_CHECKPOINT_FILE = "is_metal.ckpt"
_METALLICITY_ATOM_INIT_FILE = "atom_init.json"


def predict_kdistance_quantiles(
    model: object,
    features: StructureFeatureVector,
    correction: float = DEFAULT_KPOINTS_CORRECTION,
) -> tuple[float, float, float]:
    """Return (median, lower, upper) k-distance in Å⁻¹ from a QRF prediction.

    The QRF returns three quantiles ``[lower, median, upper]`` for the single
    input row. ``correction`` calibrates (widens) the interval bounds.

    Raises:
        AttributeError: If the model has no ``predict`` method.
        ValueError: If the prediction does not yield three quantiles.
    """
    if not hasattr(model, "predict"):
        raise AttributeError("QRF model does not provide a 'predict' method.")

    raw = np.asarray(model.predict(features.values.reshape(1, -1)), dtype=float)
    if raw.size != 3:
        raise ValueError(
            f"Expected 3 quantiles from the QRF prediction; got {raw.size}."
        )

    lower, median, upper = raw.reshape(3, -1)[:, 0]
    return float(median), float(lower) - correction, float(upper) + correction


def kdistance_to_selection(
    structure: Structure,
    median: float,
    lower: float,
    upper: float,
    *,
    data_source: str,
    confidence: float = DEFAULT_KPOINTS_CONFIDENCE,
    mesh_type: str = "monkhorst-pack",
) -> KPointSelection:
    """Build a concrete k-point selection from a predicted k-distance interval.

    The median distance sets the mesh; the interval and confidence level are
    recorded in provenance so callers can judge the prediction.
    """
    return KPointSelection(
        grid=k_distance_to_mesh(structure, median),
        shift=(0, 0, 0),
        mesh_type=mesh_type,
        provenance=Provenance(
            source="model",
            reason=(
                f"ML-predicted k-point distance {median:.4f} Å⁻¹ "
                f"(interval {lower:.4f}-{upper:.4f} Å⁻¹)."
            ),
            data_source=data_source,
            confidence=confidence,
        ),
    )


def _heuristic_fallback(
    structure: Structure,
    hints: CalculationHints,
    advice: KPointAdvice,
    error: Exception,
) -> KPointSelection:
    """Resolve k-points from heuristic advice, flagging that the QRF was skipped.

    The mesh comes from the Advise stage, so its provenance source stays honest
    (``default``/``analysis``, never ``model``); a warning records that the ML
    model was attempted and could not be used.
    """
    detail = str(error) or error.__class__.__name__
    selection = resolve_kpoints_from_advice(structure, hints, advice)
    warning = (
        f"ML k-point model unavailable; used heuristic k-point advice ({detail})."
    )
    return replace(
        selection,
        provenance=replace(
            selection.provenance,
            warnings=(*selection.provenance.warnings, warning),
        ),
    )


def _resolve_metallicity_artifacts(
    checkpoint: str | None,
    atom_init: str | None,
    repo: str | None,
    revision: str | None,
) -> tuple[str, str]:
    """Resolve the metallicity checkpoint and atom-embedding table to local paths.

    Explicit local paths win; any path left as ``None`` is downloaded (and cached)
    from the Hugging Face ``repo``. Raising here is intentional — the caller runs
    this inside its guarded load so a download failure degrades to the heuristic.
    """
    if checkpoint is not None and atom_init is not None:
        return checkpoint, atom_init
    if repo is None:
        raise ValueError(
            "Metallicity artifacts unresolved: provide local paths or a HF repo."
        )
    from huggingface_hub import hf_hub_download

    checkpoint = checkpoint or hf_hub_download(
        repo, _METALLICITY_CHECKPOINT_FILE, revision=revision
    )
    atom_init = atom_init or hf_hub_download(
        repo, _METALLICITY_ATOM_INIT_FILE, revision=revision
    )
    return checkpoint, atom_init


def qrf_kdistance_advisor(
    metallicity_checkpoint: str | None = None,
    metallicity_atom_init: str | None = None,
    *,
    metallicity_repo: str | None = None,
    metallicity_revision: str | None = None,
    spec: ModelSpec = DEFAULT_KPOINTS_MODEL,
    correction: float = DEFAULT_KPOINTS_CORRECTION,
    confidence: float = DEFAULT_KPOINTS_CONFIDENCE,
) -> KMeshAdvisor:
    """Return a Kmesh-stage backend that predicts k-distance with the QRF.

    Loads the QRF and the CGCNN metallicity model once; the returned advisor
    reuses them. The metallicity checkpoint and atom-embedding table resolve from
    explicit local paths when given, otherwise from ``metallicity_repo`` on
    Hugging Face. An explicit ``k_grid`` or ``k_spacing`` hint bypasses the model
    and resolves from advice instead.

    Never hard-fails: if the models or their dependencies cannot be loaded (or
    downloaded), or a per-structure prediction raises, the advisor degrades to
    the heuristic advice and records the reason in provenance warnings.
    """
    from goldilocks_core.ml.kdistance_features import extract_qrf_features
    from goldilocks_core.ml.metallicity import load_metallicity_model
    from goldilocks_core.ml.models import load_model

    try:
        qrf = load_model(spec)
        checkpoint, atom_init = _resolve_metallicity_artifacts(
            metallicity_checkpoint,
            metallicity_atom_init,
            metallicity_repo,
            metallicity_revision,
        )
        metal_model = load_metallicity_model(checkpoint)
    except Exception as error:  # deps missing, download fails, bad checkpoint
        load_error = error  # bind outside the except scope for the closure

        def unavailable_advisor(structure, hints, kpoint_advice):
            if hints.k_grid is not None or hints.k_spacing is not None:
                return resolve_kpoints_from_advice(structure, hints, kpoint_advice)
            return _heuristic_fallback(structure, hints, kpoint_advice, load_error)

        return unavailable_advisor

    def advisor(structure, hints, kpoint_advice):
        if hints.k_grid is not None or hints.k_spacing is not None:
            return resolve_kpoints_from_advice(structure, hints, kpoint_advice)
        try:
            features = extract_qrf_features(structure, metal_model, atom_init)
            median, lower, upper = predict_kdistance_quantiles(
                qrf, features, correction
            )
        except Exception as predict_error:
            return _heuristic_fallback(
                structure, hints, kpoint_advice, predict_error
            )
        return kdistance_to_selection(
            structure,
            median,
            lower,
            upper,
            data_source=spec.name,
            confidence=confidence,
        )

    return advisor


def default_kmesh_advisor(
    *,
    metallicity_checkpoint: str | None = None,
    metallicity_atom_init: str | None = None,
    metallicity_repo: str | None = None,
) -> KMeshAdvisor:
    """Return the built-in default Kmesh backend: the QRF model with fallback.

    Resolves the QRF and the CGCNN metallicity model from Hugging Face
    (``DEFAULT_KPOINTS_MODEL`` and ``DEFAULT_METALLICITY_REPO``). For offline
    development, ``GOLDILOCKS_METALLICITY_CHECKPOINT`` /
    ``GOLDILOCKS_METALLICITY_ATOM_INIT`` point at local files, and
    ``GOLDILOCKS_METALLICITY_REPO`` overrides the source repo. This never
    hard-fails: if the models or their dependencies are unavailable, the advisor
    degrades to heuristic advice (see ``qrf_kdistance_advisor``).
    """
    checkpoint = metallicity_checkpoint or os.environ.get(
        "GOLDILOCKS_METALLICITY_CHECKPOINT"
    )
    atom_init = metallicity_atom_init or os.environ.get(
        "GOLDILOCKS_METALLICITY_ATOM_INIT"
    )
    repo = metallicity_repo or os.environ.get(
        "GOLDILOCKS_METALLICITY_REPO", DEFAULT_METALLICITY_REPO
    )
    return qrf_kdistance_advisor(
        checkpoint, atom_init, metallicity_repo=repo
    )
