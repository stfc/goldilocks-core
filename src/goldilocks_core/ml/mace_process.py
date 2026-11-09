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

The worker keeps much of a prediction's memory afterwards (#260). On Linux
(goldilocks-ml 0.3.3, glibc 2.36), from a 0.7 GB baseline, a 16-atom
prediction left it 0.45 GB higher and a 128-atom one 0.9-2.3 GB higher. None
of that is held by a Python object, and neither a heap trim
(``malloc_trim``, which also slowed large predictions by 30-60%), a garbage
collection, fewer malloc arenas, a fixed mmap threshold nor a later small
prediction reliably released it; only the process exiting does. So after a
prediction for more than ``_REPLACE_ABOVE_ATOMS`` atoms, the worker is
replaced by a fresh, warmed one once it has been idle for ``_IDLE_S``
seconds. A fresh worker took 3 s to load and warm up (12 s with a cold disk
cache), in the background, while calls kept going to the old one.
"""

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING, Any

from pymatgen.core import Lattice, Structure

from goldilocks_core.ml.predict import MlModelUnavailable
from goldilocks_core.worker_process import WorkerProcess

if TYPE_CHECKING:
    from pathlib import Path

_IS_MAGNETIC_WORKER = WorkerProcess()

_REPLACE_ABOVE_ATOMS = 16
"""A 16-atom prediction leaves the worker 0.45 GB above its baseline; more
atoms leave more (#260)."""

_IDLE_S = 30.0
"""How long the worker must be idle before it is replaced: long enough that
a user editing settings, each edit an explain, does not reload the model."""

_WARM_UP_CELL = Structure(
    Lattice.cubic(2.87), ["Fe", "Fe"], [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]]
)
"""Two-atom bcc Fe, predicted once by a fresh worker before it serves."""


def predict_is_magnetic(
    model_root: Path, checkpoint: Path, structure: Structure
) -> Any:
    """The ``ModelPrediction`` of the is_magnetic model installed at
    ``model_root``, with mMACE backbone ``checkpoint``, for ``structure``.

    Raises :class:`~goldilocks_core.ml.predict.MlModelUnavailable` if the
    worker cannot import mace-torch's magnetic models. Whatever loading
    or running the model raises is re-raised from the worker, and
    ``worker_process.WorkerDied`` if the worker dies.

    After a structure of more than ``_REPLACE_ABOVE_ATOMS`` atoms, schedules
    the worker's replacement once it is idle."""
    prediction = _IS_MAGNETIC_WORKER.run(
        _predict_is_magnetic, model_root, checkpoint, structure
    )
    if len(structure) > _REPLACE_ABOVE_ATOMS:
        _IS_MAGNETIC_WORKER.replace_when_idle(
            _IDLE_S, _predict_is_magnetic, model_root, checkpoint, _WARM_UP_CELL
        )
    return prediction


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
