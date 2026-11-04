"""Tests for goldilocks_core.examples.structures (v2 epic 9, #9).

Trimmed to the bundling contract itself: the two tests this replaced
(``test_every_bundled_structure_runs_through_the_pipeline``,
``test_bundled_structures_exercise_distinct_advice_branches``) ran each
bundled structure through v1's whole ``compute()``/``ComputeRequest``
pipeline just to confirm Fe/Pt/Si produce visibly different advice
(metallicity, spin-orbit, magnetism) -- that exact claim is already
covered, against v2's real advisors directly, by
``tests/physics/test_dft_decisions.py`` (hardened for this in v2 epic
9's module 1). Rebuilding an ``advise()``-based equivalent here would
be new coverage, not a like-for-like port, so it's left as a possible
future addition rather than squeezed into this cutover.
"""

from __future__ import annotations

import pytest

from goldilocks_core.examples.structures import (
    available_structures,
    structure,
    structures_path,
)


def test_bundled_structures_are_installed_with_the_package() -> None:
    assert structures_path().is_dir()
    assert available_structures() == ("Fe_bcc.cif", "Pt_fcc.cif", "Si.cif")


def test_structure_rejects_an_unknown_name() -> None:
    with pytest.raises(FileNotFoundError) as error:
        structure("Unobtainium.cif")

    assert "Si.cif" in str(error.value)
