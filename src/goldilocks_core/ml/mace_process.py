"""mace_process: is_magnetic predictions, run on a worker process so mMACE's
process-wide side effects never reach the caller (#130).

mace builds its calculator under ``torch.set_default_dtype(torch.float64)``,
which applies to every thread in the process: a float32 model (the is_metal
CGCNN, QRF95's embedded CGCNN, the is_magnetic head itself) built on another
request's thread meanwhile gets float64 parameters and fails on its first
matrix product. Importing mace also prints to stdout and sets
``TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD`` in ``os.environ``.

Every is_magnetic prediction therefore runs on one long-lived
``worker_process.WorkerProcess``, which loads the model and the backbone once.
Concurrent callers queue for it. Ordering rankings, the other mMACE use, run
in a fresh process each (``advisors/magnetic_ordering_ml.py``), so a ranking
never holds up is_magnetic.
"""

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING, Any

from goldilocks_core.ml.predict import MlModelUnavailable
from goldilocks_core.worker_process import WorkerProcess

if TYPE_CHECKING:
    from pathlib import Path

    from pymatgen.core import Structure

_IS_MAGNETIC_WORKER = WorkerProcess()


def predict_is_magnetic(
    model_root: Path, checkpoint: Path, structure: Structure
) -> Any:
    """The ``ModelPrediction`` of the is_magnetic model installed at
    ``model_root``, with mMACE backbone ``checkpoint``, for ``structure``.

    Raises :class:`~goldilocks_core.ml.predict.MlModelUnavailable` if the
    worker cannot import mace-torch's magnetic models. Whatever loading
    or running the model raises is re-raised from the worker, and
    ``worker_process.WorkerDied`` if the worker dies."""
    return _IS_MAGNETIC_WORKER.run(
        _predict_is_magnetic, model_root, checkpoint, structure
    )


def _predict_is_magnetic(
    model_root: Path, checkpoint: Path, structure: Structure
) -> Any:
    """Worker side of :func:`predict_is_magnetic`."""
    try:
        from mace.calculators.mace import MagneticMACECalculator  # noqa: F401
        from mace.modules import MagneticSCFMACE  # noqa: F401
    except ImportError as error:
        # mace-torch before 0.3.17 has no magnetic models.
        raise MlModelUnavailable(
            "is_magnetic needs mace-torch 0.3.17 or later, with MagneticSCFMACE "
            f"(see docs/mmace-setup.md): {error}"
        ) from error
    return _is_magnetic_model(model_root, checkpoint).predict(structure)


@cache
def _is_magnetic_model(model_root: Path, checkpoint: Path) -> Any:
    """The is_magnetic model at ``model_root``, loaded once per worker
    process; goldilocks-ml loads the backbone on its first prediction."""
    from goldilocks_ml.inference import load_model

    return load_model(
        model_root,
        artifacts={"mace_backbone": checkpoint},
        artifact_directory=model_root,
    )
