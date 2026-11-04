"""``SystemOverrides``, split out of ``_system.py`` (v2 epic 8, #8).

Purely a shape: the human/llm override object per system-level advisor,
typed against the same seven advisor modules ``_system.py`` already
calls. Kept in its own file so ``_system.py``'s own import surface only
pays for the *types* its calculations actually touch (``*Decision``/
``*Facts``), not the override-only ``*HumanInput``/``*LlmInput`` types
it merely forwards attribute-by-attribute -- the same import-surface
ceiling reason (``scripts/check_complexity.py``) ``_pseudo.py`` and the
``_step_kpoints.py``/``_step_resources.py`` split exist for.
"""

from __future__ import annotations

from dataclasses import dataclass

from goldilocks_core.advisors.boundary import BoundaryHumanInput, BoundaryLlmInput
from goldilocks_core.advisors.cutoffs import CutoffsHumanInput
from goldilocks_core.advisors.electron_count import ElectronCountHumanInput
from goldilocks_core.advisors.functional import FunctionalHumanInput, FunctionalLlmInput
from goldilocks_core.advisors.hubbard_u import HubbardUHumanInput, HubbardULlmInput
from goldilocks_core.advisors.magnetic_config import (
    MagneticConfigHumanInput,
    MagneticConfigLlmInput,
)
from goldilocks_core.advisors.vdw_method import VdwMethodHumanInput, VdwMethodLlmInput


@dataclass(frozen=True, slots=True)
class SystemOverrides:
    functional: FunctionalHumanInput | None = None
    functional_llm: FunctionalLlmInput | None = None
    pseudo_table_id: str | None = None
    cutoffs: CutoffsHumanInput | None = None
    electron_count: ElectronCountHumanInput | None = None
    magnetic: MagneticConfigHumanInput | None = None
    magnetic_llm: MagneticConfigLlmInput | None = None
    vdw: VdwMethodHumanInput | None = None
    vdw_llm: VdwMethodLlmInput | None = None
    hubbard: HubbardUHumanInput | None = None
    hubbard_llm: HubbardULlmInput | None = None
    boundary: BoundaryHumanInput | None = None
    boundary_llm: BoundaryLlmInput | None = None
