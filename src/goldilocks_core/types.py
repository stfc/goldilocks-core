from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

JsonDict = dict[str, Any]

PathLike = str | Path

CodeName = str

CalcTask = Literal[
    "scf_single_point",
    "dos",
    "band",
    "relax",
    "vc-relax",
    "phonon",
    "relax-phonon",
    "vc-relax-phonon",
]
"""``dos`` added v2 epic 9, #9. ``relax``/``vc-relax`` added v2 epic 10,
#10 -- both single-step (one ``pw.x`` run with ``calculation`` set
accordingly), unlike ``dos``'s three-step scf/nscf/dos.x sequence.
``band`` added #118: scf, pw.x along the band path, then bands.x.
``phonon``/``relax-phonon``/``vc-relax-phonon`` added #215: an scf, a
fixed-cell relax or a vc-relax, then ph.x on a q-point mesh, q2r.x, and
matdyn.x for the phonon DOS and for the dispersion along the band path."""

SmearingType = Literal["gaussian", "mp", "cold", "fd"]
"""QE's short names for its four smearing functions: Gaussian,
Methfessel-Paxton, Marzari-Vanderbilt and Fermi-Dirac (QE 7.3
``PW/src/set_occupations.f90:48-59``); pw.x stops on any other name.
Fixed occupations are an ``occupations`` value, not a smearing kind."""

ModelType = Literal["random_forest", "cgcnn", "xgboost", "mlp"]

PseudoAccuracy = Literal["efficiency", "precision"]

PseudoType = Literal["NC", "USPP", "PAW"]

RelativisticTreatment = Literal["scalar", "full", "non-relativistic"]

KPointGrid = tuple[int, int, int]

KPointShift = tuple[Literal[0, 1], Literal[0, 1], Literal[0, 1]]


Dimensionality = Literal["3d", "2d", "1d", "molecule", "unknown"]

VdwMethod = Literal["d3", "d3bj", "ts", "mbd"]
"""Code-agnostic labels mapped to code-specific keywords in Generate
(e.g. ``d3bj`` → QE ``vdw_corr='grimme-d3'`` with ``dftd3_version=4``)."""
