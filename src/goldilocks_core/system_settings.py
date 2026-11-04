"""``SystemSettings``: one material's resolved, concrete system-level
advice, bundled for a generation writer to consume.

New in v2 (v2 epic 7, #7); not named in this epic's issue text, but
needed by it. Epic 5 (#5, "advisors/: system-level parameters") built
eight independent advisors -- ``functional``, ``cutoffs``,
``electron_count``, ``pseudo_selection``/``magnetic_config``/
``vdw_method``/``hubbard_u``/``boundary`` -- each tested and returned on
its own, with nothing bundling their outputs together. ``StepSettings``
(v2 epic 6, #6) is the equivalent bundle one level down, for *per-step*
advice; this is that same idea one level up, for the *system-level*
advice every step of a task shares. Without it, ``generation/quantum_
espresso/scf.py`` would have to take eight separate positional
parameters instead of one settings object -- the same shape problem
``StepSettings``'s own docstring describes for per-step advice.

**Holds concrete values, not ``FieldState``-wrapped ones** -- same rule
as ``StepSettings``: by the time one of these is constructed, ``checks.py``
has already confirmed nothing it depends on is ``Blocked``, so a
``SystemSettings`` never carries a poison object.

**Not a pydantic model, not a wire type.** Like ``StepSettings``, this is
an internal assembly type consumed by generation, not a contract exposed
over HTTP/MCP -- those get a schema once epic 8 ("reconnect delivery
layers") needs one.

``pseudopotentials`` holds the *matched, real* metadata for every
element in the structure being generated (one entry per element, also
when the simulated cell ``MagneticConfigFacts.cell`` splits an element
into several species), i.e. ``pseudo_selection.py``'s
``select_metadata_for_elements`` output, not a raw selection record.
"""

from __future__ import annotations

from dataclasses import dataclass

from goldilocks_core.advisors.boundary import BoundaryFacts
from goldilocks_core.advisors.cutoffs import CutoffsDecision
from goldilocks_core.advisors.electron_count import ElectronCountDecision
from goldilocks_core.advisors.hubbard_u import HubbardUDecision
from goldilocks_core.advisors.magnetic_config import MagneticConfigFacts
from goldilocks_core.advisors.vdw_method import VdwFacts
from goldilocks_core.assets.pseudopotentials.upf import PseudoMetadata


@dataclass(frozen=True, slots=True)
class SystemSettings:
    functional: str
    cutoffs: CutoffsDecision
    electron_count: ElectronCountDecision
    pseudopotentials: tuple[PseudoMetadata, ...]
    magnetic: MagneticConfigFacts
    vdw: VdwFacts
    hubbard: HubbardUDecision
    boundary: BoundaryFacts
