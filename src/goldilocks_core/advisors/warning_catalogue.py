"""The full catalogue of warning codes every advisor can emit (v2 epic
8, #8) -- what ``capabilities()["warnings"]`` publishes so a frontend
can build a filter/legend without having to trigger every code first
(goldilocks-core-design.md S4.2: "warnings: [code, level, category] --
frontend builds a filter").

A dedicated aggregator, not ``capabilities.py`` importing each advisor
directly: this project's own import-surface ceiling
(``scripts/check_complexity.py``) would make a "god module" of a
capabilities builder that imports every advisor that emits warnings.
This module absorbs that cost instead -- it exists for no other
purpose -- while ``capabilities.py`` only ever imports this one name.
``ml.predict``'s entries are the warnings a model returns with a prediction,
one code per record a model decides (#156).
"""

from __future__ import annotations

from goldilocks_core.advisors.boundary import WARNING_CATALOGUE as _BOUNDARY
from goldilocks_core.advisors.convergence import WARNING_CATALOGUE as _CONVERGENCE
from goldilocks_core.advisors.cutoffs import WARNING_CATALOGUE as _CUTOFFS
from goldilocks_core.advisors.hubbard_u import WARNING_CATALOGUE as _HUBBARD
from goldilocks_core.advisors.job_resources import WARNING_CATALOGUE as _JOB
from goldilocks_core.advisors.k_path import WARNING_CATALOGUE as _K_PATH
from goldilocks_core.advisors.k_sampling import WARNING_CATALOGUE as _K_SAMPLING
from goldilocks_core.advisors.magnetic_config import WARNING_CATALOGUE as _MAGNETIC
from goldilocks_core.advisors.nbnd import WARNING_CATALOGUE as _NBND
from goldilocks_core.advisors.occupations import WARNING_CATALOGUE as _OCCUPATIONS
from goldilocks_core.advisors.parallelisation import (
    WARNING_CATALOGUE as _PARALLELISATION,
)
from goldilocks_core.advisors.phonon import WARNING_CATALOGUE as _PHONON
from goldilocks_core.advisors.q_sampling import WARNING_CATALOGUE as _Q_SAMPLING
from goldilocks_core.advisors.vdw_method import WARNING_CATALOGUE as _VDW
from goldilocks_core.ml.predict import WARNING_CATALOGUE as _MODEL

WARNING_CATALOGUE = (
    _BOUNDARY
    + _CONVERGENCE
    + _CUTOFFS
    + _HUBBARD
    + _JOB
    + _K_PATH
    + _K_SAMPLING
    + _MAGNETIC
    + _MODEL
    + _NBND
    + _OCCUPATIONS
    + _PARALLELISATION
    + _PHONON
    + _Q_SAMPLING
    + _VDW
)
