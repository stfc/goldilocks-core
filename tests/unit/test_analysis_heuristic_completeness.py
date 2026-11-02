"""Closes the analysis/-scoped rows of stfc/goldilocks-core#175 (v2 epic 4,
#1): every analysis/ fact's heuristic tier must be attemptable with zero
external dependency -- no installed model, no network call, no agent. This
is a claim about *availability*, not about always resolving: is_metal,
symmetry, geometry, is_magnetic and local_moments all have real cases where
the honest answer is Unavailable (see their own test files) -- that is still "the
heuristic tier ran to completion," the thing #175 asks to guarantee.
Verified here as "calling every heuristic tier on a handful of structures
never raises." A disordered structure never reaches them: advice refuses it
first (``inputs.structure.require_ordered``, #224).
"""

from __future__ import annotations

from pymatgen.core import Lattice, Structure

from goldilocks_core.analysis.composition import composition
from goldilocks_core.analysis.geometry import geometry
from goldilocks_core.analysis.is_magnetic import is_magnetic
from goldilocks_core.analysis.is_metal import is_metal
from goldilocks_core.analysis.local_moments import local_moments
from goldilocks_core.analysis.needs_soc import needs_soc
from goldilocks_core.analysis.symmetry import symmetry
from goldilocks_core.resolution import Blocked, Resolved, Unavailable

_FIELD_STATE_TYPES = (Resolved, Unavailable, Blocked)

_SILICON = Structure(Lattice.cubic(5.43), ["Si", "Si"], [[0, 0, 0], [0.25, 0.25, 0.25]])
_ZINC_OXIDE = Structure(Lattice.cubic(4.0), ["Zn", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]])


def test_every_heuristic_tier_runs_to_completion_with_no_external_dependency() -> None:
    for structure in (_SILICON, _ZINC_OXIDE):
        composition_state = composition(structure)
        assert isinstance(composition_state, _FIELD_STATE_TYPES)
        assert composition_state.ok  # composition never fails, see its own tests

        assert isinstance(symmetry(structure), _FIELD_STATE_TYPES)
        assert isinstance(geometry(structure), _FIELD_STATE_TYPES)
        assert isinstance(is_metal(structure), _FIELD_STATE_TYPES)
        assert isinstance(is_magnetic(structure), _FIELD_STATE_TYPES)
        assert isinstance(local_moments(structure), _FIELD_STATE_TYPES)
        assert isinstance(needs_soc(composition_state), _FIELD_STATE_TYPES)
